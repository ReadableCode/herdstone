# Herdstone

> A cross-platform machine herd monitor with a native menubar UI. See which machines are online, run commands across your herd, manage SSH keys, and monitor iOS devices.

---

## Vision

---

## Architecture

```
herdstone/
├── pyproject.toml           # Python project config (uv)
├── engine/                  # The Python package (import engine.models)
│   ├── __init__.py
│   ├── models.py            # Dataclasses: Machine, Group, CommandResult, etc.
│   ├── config.py            # App config, paths, defaults
│   ├── inventory.py         # Load/save/parse machine inventory (Ansible-compatible)
│   ├── ssh.py               # SSH harness: connect, run command, push keys
│   ├── ping.py              # ICMP ping, reachability checks
│   ├── discovery.py         # mDNS/Bonjour + Tailscale API discovery
│   ├── wol.py               # Wake-on-LAN magic packet sender
│   ├── health.py            # HTTP health endpoint polling
│   ├── ios_bridge.py        # iOS device state via iCloud/Shortcuts bridge
│   ├── command_runner.py    # Run commands across herd (single, group, all)
│   └── cli.py               # Typer CLI entry point
│
├── tests/
│   ├── test_inventory.py
│   ├── test_ssh.py
│   ├── test_ping.py
│   └── test_discovery.py
│
├── cli/
│   └── herdstone             # Shell script — calls `uv run` into project root
│
├── ui_mac/                  # SwiftUI macOS menubar app — Mac only
│   ├── HerdstoneApp.swift
│   ├── MenuBarView.swift
│   ├── MachineRowView.swift
│   ├── HerdDetailView.swift
│   ├── CommandPaletteView.swift
│   └── EngineClient.swift   # Calls CLI script, parses JSON stdout
│
├── docs/
│   ├── architecture.md      # Deeper architecture notes
│   ├── inventory_format.md  # Inventory file spec + Ansible compatibility
│   ├── ios_bridge.md        # How the iOS Shortcut bridge works
│   └── roadmap.md           # Versioned roadmap
│
├── .gitignore
└── README.md
```

---

## CLI as IPC Bridge

The UI layer (SwiftUI on Mac, PyQt on Linux/Windows) communicates with the engine by calling the CLI as a subprocess. All commands support a `--json` flag for machine-readable output. No server process, no ports, no daemon lifecycle.

### CLI commands

| Command | Description | Status |
|---|---|---|
| `herdstone hosts` | List all machines from inventory | ✅ |
| `herdstone hosts --json` | List all machines as JSON | ✅ |
| `herdstone ping {id}` | Ping a single machine | ✅ |
| `herdstone ping --group {name}` | Ping all machines in a group | ✅ |
| `herdstone ping --all` | Ping all machines concurrently | ✅ |
| `herdstone ping --all --json` | Ping all machines, JSON output | ✅ |
| `herdstone storage {id}` | Show disk usage for a single machine | ✅ |
| `herdstone storage --group {name}` | Show disk usage for a group | ✅ |
| `herdstone storage --all` | Show disk usage for all machines | ✅ |
| `herdstone storage --all --json` | Disk usage, JSON output | ✅ |
| `herdstone status --json` | List all machines with current status | planned |
| `herdstone machine {id} --json` | Get single machine detail | planned |
| `herdstone run {id} {command} --json` | Run a command on a machine | planned |
| `herdstone run --all {command} --json` | Run a command on all machines | planned |
| `herdstone run --group {name} {command} --json` | Run a command on a named group | planned |
| `herdstone push-key {id} --json` | Push a public key to a machine | planned |
| `herdstone discover --json` | Trigger mDNS/Tailscale discovery scan | planned |
| `herdstone ios --json` | Get iOS device states (battery, last seen) | planned |

All implemented commands support `--json` for machine-readable output.

#### Examples

```bash
# List all hosts from inventory
herdstone hosts

# Ping all machines concurrently (~1-2s regardless of host count)
herdstone ping --all

# Ping just the macs group
herdstone ping --group macs

# Ping a single host by alias
herdstone ping sshbehemoth

# JSON output (for scripting or UI consumption)
herdstone ping --group raspbian --json

# Show disk usage for all raspberry pis
herdstone storage --group raspbian

# Show disk usage for a single host
herdstone storage sshelite

# Show all disk usage as JSON
herdstone storage --all --json
```

The `cli/herdstone` script is a thin shell wrapper that runs `uv run` inside `engine/`. The SwiftUI app calls it via `Process()`, reads stdout, and parses JSON.

---

## Data Models

### Machine

```python
@dataclass
class Machine:
    id: str                          # UUID, stable across renames
    name: str                        # Human display name
    hostname: str                    # DNS name or IP
    user: str                        # SSH username
    port: int = 22                   # SSH port
    groups: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    identity_file: str | None = None # Path to SSH key
    harness: str = "ssh"             # ssh | ping_only | ios | http
    status: str = "unknown"          # online | offline | unknown
    last_seen: datetime | None = None
    metadata: dict = field(default_factory=dict)  # df -h output, battery, etc.
```

### CommandResult

```python
@dataclass
class CommandResult:
    machine_id: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timestamp: datetime
```

---

## Connection Harnesses

Herdstone supports multiple harness types per machine. The harness defines how Herdstone communicates with a device.

| Harness | Use Case | Status |
|---|---|---|
| `ssh` | Linux servers, remote Macs, VMs, Raspberry Pi | v1 |
| `ping` | Any reachable host, no credentials needed | v1 |
| `mdns` | Local network auto-discovery via Bonjour/Avahi | v1 |
| `tailscale` | Machines on a Tailscale network, auto-inventory | v2 |
| `http` | Services exposing a `/health` endpoint | v2 |
| `wol` | Wake sleeping machines on LAN | v2 |
| `ios` | iOS devices via Shortcuts + iCloud bridge | v3 |

---

## Inventory Format

Herdstone uses an extended YAML format that is a superset of Ansible's YAML inventory. An existing Ansible inventory can be imported directly.

```yaml
# herdstone_inventory.yaml

groups:
  servers:
    hosts:
      web01:
        hostname: web01.example.com
        user: ubuntu
        identity_file: ~/.ssh/id_ed25519
        harness: ssh
        tags:
          env: production
          role: web

      pi-home:
        hostname: 192.168.1.42
        user: pi
        harness: ssh
        tags:
          env: home
          role: media

  macs:
    hosts:
      macbook-work:
        hostname: macbook-work.local
        user: dev
        harness: ssh

  ios_devices:
    hosts:
      iphone-personal:
        harness: ios
        icloud_key: iphone_personal_state   # key in shared iCloud KV file
```

---

## Versioned Roadmap

### v1 — Core SSH Herd Monitor (Mac menubar)

- [ ] Python engine: inventory load/save, SSH harness, ping harness
- [ ] CLI: ping all, run command on one/all/group, push SSH key, `--json` output
- [ ] SwiftUI menubar app: online/offline status per machine (calls CLI as subprocess)
- [ ] Run preset or custom command on one machine, a group, or all
- [ ] Push public SSH key from one machine to another
- [ ] `df -h`, `uptime`, `uname` quick commands built in
- [ ] Import Ansible INI/YAML inventory

### v2 — Discovery + Integrations

- [ ] mDNS/Bonjour local network auto-discovery
- [ ] Tailscale API integration (auto-populate herd from Tailscale)
- [ ] HTTP health endpoint polling
- [ ] Wake-on-LAN
- [ ] Alert on machine going offline (Mac notification)
- [ ] Command history with output viewer

### v3 — iOS + Multi-platform

- [ ] iOS device state via Shortcut + iCloud bridge (battery, last seen, device name)
- [ ] Linux tray app (PyQt or TUI)
- [ ] Windows tray app

### v4 — Polish + App Store

- [ ] Mac App Store submission
- [ ] Onboarding flow for new users
- [ ] Settings UI (manage inventory, SSH keys, groups)
- [ ] Dark/light mode, menubar icon states

---

## Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Engine | Python 3.14+ | Cross-platform, mature SSH/networking libs, existing author expertise |
| SSH | `asyncssh` | Async, well-maintained, no native dependency headaches |
| Ping | `icmplib` | Cross-platform ICMP, clean API |
| mDNS | `zeroconf` | Cross-platform Bonjour/Avahi |
| CLI | `typer` | CLI wraps engine, doubles as IPC bridge for SwiftUI via `--json` |
| Dependency mgmt | `uv` | Author's existing standard |
| Mac UI | SwiftUI | Native Mac menubar, App Store compatible |
| Linux/Win UI | PyQt6 (future) | Reuses Python engine directly |

---

## Development Setup

```bash
# Clone
git clone git@github.com:ReadableCode/herdstone.git
cd herdstone

# Install Python dependencies
uv sync

# Run the CLI (start here, no UI needed)
./cli/herdstone --help

# Run tests
uv run pytest
```

---

## Build Order for Claude Code

If picking this up fresh, build in this order:

1. `engine/models.py` — dataclasses only, no logic
2. `engine/config.py` — paths, defaults, config file loading
3. `engine/inventory.py` — load/save YAML inventory, Ansible import
4. `engine/ping.py` — ICMP ping, async, returns `CommandResult`
5. `engine/ssh.py` — connect, run command, push key, async
6. `engine/command_runner.py` — fan out commands to one/group/all machines concurrently
7. `engine/cli.py` — Typer CLI entry point, `--json` flag on all commands
8. `cli/herdstone` — shell script wrapper calling `uv run`
9. `tests/` — unit tests for each engine module
10. `ui_mac/` — SwiftUI menubar app, calls CLI script and parses JSON stdout

Do not start the SwiftUI layer until the engine passes all tests and the CLI is fully functional. The UI should never contain business logic.

---
