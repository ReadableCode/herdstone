"""Herd monitor web UI — a thin NiceGUI layer over the engine.

Single process, server-rendered, calls core functions in-process (no internal
REST API). Meant to run on an always-on box, bound to the Tailscale interface.
All business logic lives in the engine package; this file only renders.
Styling follows the readablecode "terminal navy" design system (dotfiles
design/STYLE.md) — tokens live in _TOKENS_CSS, Quasar brand colors are mapped
onto them in index().
"""

from ..inventory import parse_inventory
from ..models import Machine
from ..ping import ping_many
from ..storage import get_storage_many

# readablecode "terminal navy" tokens (dotfiles design/tokens.css) plus the
# Quasar overrides that map the existing markup onto them. This block is the
# whole theme — don't add hex values elsewhere.
#
# NiceGUI loads Quasar's CSS into cascade layers, so layered !important
# utility classes (text-white, bg-green, text-grey, ...) beat anything we
# write here, even with !important. These rules therefore stay unlayered and
# normal (they win over Quasar's layered normal declarations), and the markup
# avoids Quasar color utilities in favor of the state-*/muted classes below.
_TOKENS_CSS = """
:root {
  --bg: #0d1420;
  --surface: #121b2a;
  --surface-2: #182333;
  --border: rgba(148, 163, 184, 0.16);
  --ink: #dbe4f0;
  --ink-2: #9fb0c3;
  --muted: #7d8b9e;
  --green: #2ea043;
  --green-bright: #56d364;
  --amber: #b8860b;
  --amber-bright: #e3b341;
  --dot-red: #f87171;
  --radius: 8px;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas,
    monospace;
}

body, body.body--dark {
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-mono);
}
.q-field__native, .q-field__input, .q-btn, .q-badge, .q-toggle,
.q-notification, .q-tooltip {
  font-family: var(--font-mono);
}

/* cards as stat pills: surface, hairline border, 8px radius, no shadows */
.q-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: none;
  color: var(--ink);
}

/* badges: quiet pills, state carried by text color */
.q-badge {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--ink-2);
}

/* semantic state / text colors (replace Quasar text-* utilities) */
.muted { color: var(--muted); }
.state-complete { color: var(--green-bright); }
.state-partial { color: var(--amber-bright); }
.state-absent { color: var(--muted); }
.state-error { color: var(--dot-red); }

.q-btn {
  border-radius: var(--radius);
  box-shadow: none;
  text-transform: none;
}
.q-btn.bg-positive { font-weight: 700; }
.q-btn-group { border: 1px solid var(--border); box-shadow: none; }

.q-field--outlined .q-field__control {
  border-radius: var(--radius);
  background: var(--surface);
}
.q-field--outlined .q-field__control:before { border: 1px solid var(--border); }
.q-field--outlined.q-field--focused .q-field__control:after {
  border-color: var(--green);
  border-width: 1px;
}
.q-field__native { color: var(--ink); }
.q-field__native::placeholder { color: var(--muted); }

.q-notification { border-radius: var(--radius); }

/* signature pieces: ❯ brand, // section headers */
.brand-prompt { color: var(--green-bright); }
.section-h {
  width: 100%;
  border-bottom: 1px solid var(--border);
  padding-bottom: 2px;
  font-weight: 700;
  color: var(--ink);
}
.section-h .sh-slash { color: var(--green-bright); }
"""


def _conn_summary(machine: Machine) -> str:
    """Connection summary, same shape as the CLI `hosts` output."""
    if machine.harness == "ssh":
        port_str = f" -p {machine.port}" if machine.port != 22 else ""
        return f"ssh {machine.user}@{machine.hostname}{port_str}"
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


def run_web(host: str = "127.0.0.1", port: int = 8787) -> None:
    from nicegui import ui

    @ui.page("/")
    def index() -> None:
        ui.colors(
            primary="#2ea043",
            secondary="#182333",
            accent="#56d364",
            dark="#121b2a",
            dark_page="#0d1420",
            positive="#2ea043",
            negative="#f87171",
            info="#9fb0c3",
            warning="#e3b341",
        )
        ui.add_css(_TOKENS_CSS)

        machines = parse_inventory()
        status_labels: dict[str, ui.label] = {}

        def _section(title: str) -> None:
            ui.html(f'<span class="sh-slash">//</span> {title}').classes("section-h")

        async def ping_all() -> None:
            targets = [m for m in machines if m.harness != "none"]
            if not targets:
                ui.notify("no pingable hosts.", color="warning", position="top")
                return
            spinner.visible = True
            try:
                results = await ping_many(targets)
            finally:
                spinner.visible = False
            for r in results:
                label = status_labels.get(r.machine_id)
                if label is None:
                    continue
                if r.exit_code == 0:
                    label.text = f"● online · {r.duration_ms}ms"
                    label.classes(replace="state-complete text-sm shrink-0")
                else:
                    label.text = "✗ offline"
                    label.classes(replace="state-error text-sm shrink-0")

        async def open_storage(machine: Machine) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-md"):
                ui.label(machine.name).classes("text-xl font-bold")
                ui.label(_conn_summary(machine)).classes("text-xs muted")
                _section("storage")
                body = ui.column().classes("w-full gap-1")
                with body:
                    fetching = ui.label("fetching…").classes("muted")
            dialog.open()

            results = await get_storage_many([machine])
            drives = results.get(machine.id, [])
            fetching.delete()
            with body:
                if not drives:
                    ui.label("✗ no data (unreachable or SSH failed)").classes("state-error")
                for d in drives:
                    ui.label(d.mount_point).classes("text-sm")
                    ui.label(
                        f"[{_bar(d.use_percent)}] {d.use_percent:5.1f}%  "
                        f"{_fmt_bytes(d.used_bytes)} / {_fmt_bytes(d.size_bytes)}"
                    ).classes("text-xs muted whitespace-pre")

        def _host_card(machine: Machine) -> None:
            with ui.card().classes("w-full cursor-pointer").on("click", lambda m=machine: open_storage(m)):
                with ui.row().classes("items-center no-wrap w-full gap-4"):
                    with ui.column().classes("gap-1 min-w-0 grow"):
                        ui.label(machine.name).classes("text-lg font-bold")
                        ui.label(_conn_summary(machine)).classes("text-xs muted")
                        with ui.row().classes("gap-1"):
                            for group in machine.groups:
                                ui.badge(group, color=None).classes("muted")
                            for service in machine.services:
                                ui.badge(service.name, color=None)
                    status_labels[machine.id] = ui.label("—").classes("muted text-sm shrink-0")

        # --- page layout ---
        with ui.column().classes("w-full max-w-2xl mx-auto p-4 gap-3"):
            with ui.row().classes("items-center w-full no-wrap gap-3"):
                ui.html('<span class="brand-prompt">❯</span> herdstone').classes("text-2xl font-bold grow")
                spinner = ui.spinner(size="lg")
                spinner.visible = False
                ui.button("ping all", on_click=ping_all).props("no-caps color=positive text-color=dark")
            _section("herd")
            if not machines:
                ui.label("no inventory found — expected hosts.json (see README) or HERDSTONE_HOSTS.").classes("muted")
            for machine in machines:
                _host_card(machine)

    print(f"Herdstone web UI on http://{host}:{port}  (bind your Tailscale IP with --host to share)")
    ui.run(host=host, port=port, title="❯ herdstone", dark=True, reload=False, show=False)
