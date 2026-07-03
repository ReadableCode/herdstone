# Herdstone

> A cross-platform machine herd monitor **and household media remote**. See which
> machines are online, run commands across your herd, and search/add shows and
> movies across every Sonarr/Radarr/Plex instance you run — from one CLI, TUI,
> or phone-friendly web UI.

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
│   │   ├── media/                # media remote core (shared by CLI/TUI/web)
│   │   │   ├── config.py             # builds instance list from hosts.json services + .env
│   │   │   ├── models.py             # pydantic domain models (AggregatedResult, ...)
│   │   │   ├── aggregation.py        # search_everywhere, add_to_instance, plex checks
│   │   │   ├── clients/              # httpx async clients: sonarr, radarr, plex
│   │   │   └── tui/app.py            # Textual TUI (couch/SSH use) — media-only, so it lives under media/
│   │   └── web/app.py            # NiceGUI web UI (phone use, Tailscale-bound)
│   └── tests/
├── cli/herdstone             # shell wrapper: uv run into backends/python
├── .env -> ../personal_credentials/personal.env   # symlink, gitignored
├── .env.example              # API key placeholders
└── README.md

../personal_credentials/hosts.json   # THE inventory — machines + services they offer
../personal_credentials/personal.env # API keys/tokens referenced by hosts.json
```

---

## Inventory: `hosts.json`

One JSON file is the single source of truth for the herd. Each host declares
how to reach it (`harness`: `ssh` / `ping` / `none`) and, crucially, **which
services it offers**. Adding another Sonarr/Radarr/Plex instance is a
config-only change — no code.

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

Optional service fields: `scheme` (default `http`), `base_url` (full override),
`quality_profile` and `root_folder` (preferred add-time defaults; first
available on the server otherwise).

Search order: `$HERDSTONE_HOSTS` → `../personal_credentials/hosts.json`
(canonical — it carries internal IPs/usernames, so it lives in the private
credentials repo) → repo-root `hosts.json` → `~/.config/herdstone/hosts.json` →
`~/herdstone_hosts.json`.

Secrets never live in the inventory — each service names the env var
(`api_key_env`) that holds its key/token. `.env` in this repo is a gitignored
symlink to `../personal_credentials/personal.env` (see `.env.example` for the
expected keys). Migrating from an Ansible INI inventory:

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
| `herdstone run ...` | Run a command across the herd *(planned)* |
| `herdstone push-key {id}` | Push your SSH public key to a machine |
| `herdstone import-ansible {path}` | Convert an Ansible INI inventory to hosts.json |
| `herdstone media instances` | Show configured Sonarr/Radarr/Plex instances |
| `herdstone media search "title" [-t tv\|movie] [--plex]` | Search every instance, one merged status view |
| `herdstone media seasons "title" [--episodes]` | Per-season (and per-episode) monitored/on-disk breakdown |
| `herdstone media add "title" --to {instance}` | Add the top result to a chosen instance |
| `herdstone media tui` | Launch the media remote TUI (Textual) |
| `herdstone web [--host IP] [--port 8787]` | Launch the media remote web UI (NiceGUI) |

All data commands support `--json`, which is how native UI shells (SwiftUI
menubar app, etc.) consume the engine as a subprocess.

### Media remote in 30 seconds

```bash
herdstone media instances     # verify what's configured (keys come from .env)
herdstone media search "severance" --plex
#   Severance (2022)  [tvdb:371980]
#     ● sonarr-behemoth      monitored_complete
#     ○ sonarr-elitedesk     not_present
#     ▶ plex-behemoth        watch-ready
herdstone media add "severance" --to sonarr-elitedesk
```

Statuses merge by TVDB/TMDB id (never by title string), one instance being
down degrades to a `✗ unreachable` row instead of breaking the search, and
Plex rows tell you whether it's actually watch-ready.

### Web UI deployment

Runs as a single process; bind it to your Tailscale IP on an always-on box so
phones on the tailnet can reach it. Never expose it publicly — there is no
auth layer by design (tailnet membership is the auth).

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

---

## Versioned Roadmap

### v1 — Core herd monitor + media remote

- [x] JSON inventory (`hosts.json`) with per-host services
- [x] Ansible INI import
- [x] Concurrent ping, disk usage, SSH key push, `--json` everywhere
- [x] Media core: multi-instance Sonarr/Radarr search/status/add, Plex watch-readiness
- [x] Media TUI (Textual) and mobile web UI (NiceGUI)
- [ ] `herdstone run` command runner (one/group/all)
- [ ] SwiftUI menubar app (calls CLI as subprocess)

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
| HTTP clients | `httpx` (async) | Concurrent fan-out to all instances |
| Domain models | `pydantic` | Validated media models, clean JSON serialization |
| Secrets | `python-dotenv` | `.env`-based keys referenced from hosts.json |
| TUI | `textual` | Keyboard-driven couch/SSH interface |
| Web UI | `nicegui` | Server-rendered, calls engine in-process — no hand-built API layer |
| Mac UI (planned) | SwiftUI | Native menubar, App Store compatible |
