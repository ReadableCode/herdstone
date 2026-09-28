"""Herd monitor TUI — a thin Textual layer over the engine.

All business logic lives in the engine package; this file only renders and
wires user actions to core functions. Styling follows the readablecode
"terminal navy" design system (dotfiles design/STYLE.md).
"""

from readable_utils.design_tokens import (
    GREEN_BRIGHT,
    HAIRLINE,
    MUTED,
    RED,
    terminal_navy_textual_theme,
)
from readable_utils.host_stats_tools import stats_renderable
from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Static

from ..inventory import parse_inventory
from ..models import Machine
from ..ping import ping_many
from ..stats import get_stats_one
from ..storage import get_storage_many


def _conn_summary(machine: Machine) -> str:
    """Connection summary, same shape as the CLI `hosts` output."""
    if machine.harness == "ssh":
        port_str = f" -p {machine.port}" if machine.port != 22 else ""
        via = f" (via {machine.jump})" if machine.jump else ""
        return f"ssh {machine.user}@{machine.hostname}{port_str}{via}"
    return f"{machine.harness}: {machine.hostname}" if machine.harness != "none" else "(no harness)"


def _fmt_bytes(n: float) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def _bar(use_percent: float, width: int = 20) -> str:
    """Filled/unfilled block bar, same idea as the CLI storage output."""
    filled = int(width * use_percent / 100)
    return "█" * filled + "░" * (width - filled)


class HerdMonitor(App):
    """The herd at a glance: ping everything, drill into a host's disks."""

    TITLE = "❯ herdstone"

    CSS = f"""
    Header {{
        background: $panel;
        color: $text;
    }}
    #body {{
        height: 1fr;
    }}
    #hosts {{
        width: 2fr;
    }}
    #storage-pane {{
        width: 1fr;
        border-left: solid {HAIRLINE};
        padding: 0 1;
        background: $surface;
    }}
    #storage {{
        height: auto;
    }}
    """

    BINDINGS = [
        ("p", "ping_all", "ping all"),
        ("s", "storage_selected", "storage"),
        ("r", "reload_inventory", "reload"),
        ("q", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.register_theme(terminal_navy_textual_theme())
        self.theme = "terminal-navy"
        self.machines: list[Machine] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield DataTable(id="hosts", cursor_type="row")
            with VerticalScroll(id="storage-pane"):
                yield Static("s fetches storage for the highlighted host.", id="storage")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("name", key="name", width=20)
        table.add_column("connection", key="connection", width=32)
        table.add_column("groups", key="groups")
        table.add_column("services", key="services")
        table.add_column("status", key="status", width=10)
        table.add_column("latency", key="latency", width=8)
        self._load_inventory()
        table.focus()

    # --- inventory ------------------------------------------------------------

    def _load_inventory(self) -> None:
        self.machines = parse_inventory()
        table = self.query_one(DataTable)
        table.clear()
        for machine in self.machines:
            table.add_row(
                machine.name,
                _conn_summary(machine),
                ", ".join(machine.groups),
                ", ".join(s.name for s in machine.services),
                f"[{MUTED}]—[/]",
                "",
                key=machine.id,
            )
        self.sub_title = f"{len(self.machines)} hosts"
        if not self.machines:
            self.notify("no inventory found — hosts.json or HERDSTONE_HOSTS.", severity="warning", timeout=8)

    def action_reload_inventory(self) -> None:
        self._load_inventory()
        self.notify("inventory reloaded.")

    # --- ping -----------------------------------------------------------------

    def _update_cell(self, row_key: str, column_key: str, value: str) -> None:
        try:
            self.query_one(DataTable).update_cell(row_key, column_key, value)
        except Exception:  # noqa: BLE001 — row may be gone after a reload
            pass

    def action_ping_all(self) -> None:
        self.ping_all()

    @work(exclusive=True, group="ping")
    async def ping_all(self) -> None:
        targets = [m for m in self.machines if m.harness != "none"]
        if not targets:
            self.notify("no pingable hosts.", severity="warning")
            return
        for machine in targets:
            self._update_cell(machine.id, "status", f"[{MUTED}]…[/]")
        results = await ping_many(targets)
        online = 0
        for result in results:
            if result.exit_code == 0:
                online += 1
                self._update_cell(result.machine_id, "status", f"[{GREEN_BRIGHT}]● online[/]")
            else:
                self._update_cell(result.machine_id, "status", f"[{RED}]✗ offline[/]")
            self._update_cell(result.machine_id, "latency", f"{result.duration_ms}ms")
        self.notify(f"{online}/{len(targets)} online.")

    # --- storage --------------------------------------------------------------

    def action_storage_selected(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.machines):
            return
        self.fetch_storage(self.machines[table.cursor_row])

    @work(exclusive=True, group="storage")
    async def fetch_storage(self, machine: Machine) -> None:
        panel = self.query_one("#storage", Static)
        panel.update(f"[{MUTED}]fetching {machine.name}…[/]")
        results = await get_storage_many([machine])
        drives = results.get(machine.id, [])

        lines = [
            f"[bold]{machine.name}[/]",
            f"[{MUTED}]{_conn_summary(machine)}[/]",
            "",
            f"[{GREEN_BRIGHT}]//[/] storage",
        ]
        if not drives:
            lines.append(f"[{RED}]✗[/] no data (unreachable or SSH failed)")
        for d in drives:
            lines.append(d.mount_point)
            lines.append(
                f"  \\[{_bar(d.use_percent)}] {d.use_percent:5.1f}%  "  # \[ — literal bracket, not markup
                f"{_fmt_bytes(d.used_bytes)} / {_fmt_bytes(d.size_bytes)}"
            )
        panel.update("\n".join(lines))

        # cpu/mem/disk-on-/ meters via the shared @@STATS@@ probe (Linux only)
        if machine.os != "linux":
            return
        stats = await get_stats_one(machine)
        panel.update(Group(Text.from_markup("\n".join(lines)), Text(), stats_renderable(stats)))


def run_tui() -> None:
    HerdMonitor().run()
