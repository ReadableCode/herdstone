# Herdstone

> A cross-platform machine herd monitor. See which machines are online, check
> their disks, push SSH keys, and import your Ansible inventory — from one
> CLI, TUI, or phone-friendly web UI.

Looking for the media remote (Sonarr/Radarr/Plex search/status/add)? It moved
to the **Sync_Plex** repo along with its design docs — `syncplex media ...`,
web UI on port 8788.

---

## Architecture

One Python engine, three thin presentation layers. There is no internal REST
API — the CLI, TUI, and web UI all import the same `engine` package and call
the same functions in-process.

```plaintext
herdstone/
├── backends/python/
│   ├── pyproject.toml        # Python project config (uv)
│   ├── engine/               # The engine package
│   │   ├── models.py             # Machine, Service, CommandResult dataclasses
│   │   ├── config.py             # hosts.json search path, .env loading
│   │   ├── inventory.py          # hosts.json parser + Ansible INI importer
│   │   ├── ping.py               # concurrent ICMP reachability
│   │   ├── ssh.py                # run commands over SSH (or locally)
│   │   ├── storage.py            # disk usage (df / PowerShell, OS-aware)
│   │   ├── cli.py                # Typer entry point (doubles as IPC bridge, --json everywhere)
│   │   ├── tui/app.py            # Textual TUI (couch/SSH use)
│   │   └── web/app.py            # NiceGUI web UI (phone use, Tailscale-bound)
│   └── tests/
├── cli/herdstone             # shell wrapper: uv run into backends/python
├── .env -> ../personal_credentials/personal.env   # symlink, gitignored
├── .env.example              # placeholder file (no keys needed today)
└── README.md

../personal_credentials/hosts.json   # THE inventory — machines + services they offer
../personal_credentials/personal.env # env vars referenced by hosts.json (if any)
```

---

## Inventory: `hosts.json`

Each host declares how to reach it (`harness`: `ssh` / `ping` / `none`) and,
optionally, **which services it offers**. Adding another instance of anything
is a config-only change — no code.

The herd is **multi-context**: every sibling `*_credentials` repo may
contribute a `<context>_hosts.json` (legacy `hosts.json` accepted), the same
discovery the status_board repo uses — clone a context's credentials repo and
its machines join the herd. All discovered inventories merge; the first
definition of a name wins. The shared discovery/ssh plumbing lives in the
`readable-utils` package (git-pinned, see `[tool.uv.sources]`).

```json
{
  "hosts": [
    {
      "name": "behemoth",
      "hostname": "192.168.86.31",
      "user": "root",
      "os": "linux",
      "harness": "ssh",
      "groups": ["unraid"],
      "aliases": ["sshbehemoth"],
      "services": [
        { "type": "sonarr", "name": "sonarr-behemoth", "port": 8989,  "api_key_env": "SONARR_BEHEMOTH_API_KEY" },
        { "type": "radarr", "name": "radarr-behemoth", "port": 7878,  "api_key_env": "RADARR_BEHEMOTH_API_KEY" },
        { "type": "plex",   "name": "plex-behemoth",   "port": 32400, "api_key_env": "PLEX_BEHEMOTH_TOKEN" }
      ]
    }
  ]
}
```

Optional host fields: `identity_file` (ssh `-i`) and `jump` — the name/alias
of another inventory host to hop through, injected as `ssh -J user@host:port`
so the chain lives entirely in the inventory, **deliberately not in any
machine's `~/.ssh/config`**. The hop is skipped automatically when herdstone
runs on the jump machine itself, and commands targeting *this* machine run
locally with no ssh at all.

Optional service fields: `scheme` (default `http`), `base_url` (full override),
`quality_profile` and `root_folder` (preferred add-time defaults; first
available on the server otherwise). Herdstone itself only displays services;
consumers like Sync_Plex read the same inventory to talk to them.

Search order: `$HERDSTONE_HOSTS` (single file, overrides everything) →
`../<context>_credentials/<context>_hosts.json` for every sibling credentials
repo (the personal one is canonical — inventories carry internal
IPs/usernames, so they live in the private credentials repos) → repo-root
`hosts.json` → `~/.config/herdstone/hosts.json` → `~/herdstone_hosts.json`.
Unlike the pre-v1.1 first-match-wins behavior, all existing files load and
merge.

Secrets never live in the inventory — each service names the env var
(`api_key_env`) that holds its key/token. `.env` in this repo is a gitignored
symlink to `../personal_credentials/personal.env` (herdstone needs no keys
today; see `.env.example`). Migrating from an Ansible INI inventory:

```bash
herdstone import-ansible ~/GitHub/dotfiles/inventory/hosts -o ../personal_credentials/hosts.json
```

---

## CLI

| Command | Description |
| --- | --- |
| `herdstone hosts` | List all machines (`--json` for machine-readable) |
| `herdstone ping {id\|--group g\|--all}` | Ping machines concurrently |
| `herdstone storage {id\|--group g\|--all}` | Disk usage per machine |
| `herdstone stats {id\|--group g\|--all}` | htop-style disk/cpu/mem meters (Linux hosts, nothing installed remotely) |
| `herdstone run ...` | Run a command across the herd *(planned)* |
| `herdstone push-key {id}` | Push your SSH public key to a machine |
| `herdstone import-ansible {path}` | Convert an Ansible INI inventory to hosts.json |
| `herdstone tui` | Launch the herd monitor TUI (Textual) |
| `herdstone web [--host IP] [--port 8787]` | Launch the herd monitor web UI (NiceGUI) |

All data commands support `--json`, which is how native UI shells (SwiftUI
menubar app, etc.) consume the engine as a subprocess.

### Web UI deployment

The web UI shows the herd — one card per host with its connection, groups,
and services; a "ping all" button that fans out concurrently and lights up
status dots; tap a host for its disk usage bars. Runs as a single process;
bind it to your Tailscale IP on an always-on box so phones on the tailnet can
reach it. Never expose it publicly — there is no auth layer by design
(tailnet membership is the auth).

```bash
herdstone web --host 100.x.x.x --port 8787
```

---

## Development Setup

```bash
git clone git@github.com:ReadableCode/herdstone.git
cd herdstone

uv python install 3.14
uv python pin 3.14

cd backends/python
uv sync
uv run herdstone --help
uv run pytest
uv run ruff check .
```

---

## Connection Harnesses

| Harness | Use Case | Status |
| --- | --- | --- |
| `ssh` | Linux servers, Macs, Windows (OpenSSH), Termux, Raspberry Pi | v1 |
| `ping` | Any reachable host, no credentials needed | v1 |
| `none` | Tracked-but-unreachable devices (IoT, consoles, iOS) | v1 |
| `mdns` | Local network auto-discovery via Bonjour/Avahi | v2 |
| `tailscale` | Auto-inventory from the Tailscale API | v2 |
| `http` | Services exposing a `/health` endpoint | v2 |
| `wol` | Wake sleeping machines on LAN | v2 |
| `ios` | iOS devices via Shortcuts + iCloud bridge | v3 |

For `ssh` hosts, reachability is ICMP ping **with a TCP fallback to the ssh
port**: Windows blocks inbound ICMP by default while sshd answers fine, so an
open ssh port counts as online (the result's command field says which method
decided).

---

## Versioned Roadmap

### v1 — Core herd monitor

- [x] JSON inventory (`hosts.json`) with per-host services
- [x] Ansible INI import
- [x] Concurrent ping, disk usage, SSH key push, `--json` everywhere
- [x] Herd TUI (Textual) and mobile web UI (NiceGUI)
- [ ] `herdstone run` command runner (one/group/all)
- [ ] SwiftUI menubar app (calls CLI as subprocess)

> The media remote (multi-instance Sonarr/Radarr search/status/add, Plex
> watch-readiness, its TUI and web UI) shipped here in v1 and then migrated
> to the Sync_Plex repo, where its roadmap continues.

### v2 — Discovery + Integrations

- [ ] mDNS/Bonjour local network auto-discovery
- [ ] Tailscale API integration (auto-populate herd)
- [ ] HTTP health endpoint polling
- [ ] Wake-on-LAN
- [ ] Offline alerts (Mac notification)

### v3 — iOS + Multi-platform

- [ ] iOS device state via Shortcut + iCloud bridge
- [ ] Linux/Windows tray apps

---

## Tech Stack

| Layer | Technology | Reason |
| --- | --- | --- |
| Engine | Python 3.14 + uv | Cross-platform, author's standard |
| CLI | `typer` | Doubles as IPC bridge via `--json` |
| SSH key push | `paramiko` | Password-auth key push where ssh-copy-id can't reach |
| Secrets | `python-dotenv` | `.env`-based keys referenced from hosts.json |
| TUI | `textual` | Keyboard-driven couch/SSH interface |
| Web UI | `nicegui` | Server-rendered, calls engine in-process — no hand-built API layer |
| Mac UI (planned) | SwiftUI | Native menubar, App Store compatible |
