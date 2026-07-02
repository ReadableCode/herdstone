"""Media remote TUI — a thin Textual layer over engine.media.

All business logic lives in engine/media; this file only renders and wires
user actions to core functions.
"""

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from ..media.aggregation import add_to_instance, check_plex_availability, search_everywhere
from ..media.config import load_media_config
from ..media.models import AggregatedResult, MediaType, PresenceState

STATE_GLYPHS = {
    PresenceState.MONITORED_COMPLETE: "[green]●[/]",
    PresenceState.MONITORED_INCOMPLETE: "[yellow]◐[/]",
    PresenceState.NOT_PRESENT: "[dim]○[/]",
    PresenceState.UNREACHABLE: "[red]✗[/]",
}

STATE_LABELS = {
    PresenceState.MONITORED_COMPLETE: "complete",
    PresenceState.MONITORED_INCOMPLETE: "incomplete",
    PresenceState.NOT_PRESENT: "not present",
    PresenceState.UNREACHABLE: "unreachable",
}


class MediaRemote(App):
    """Search once, see status across every instance, add where you choose."""

    TITLE = "Herdstone Media Remote"

    CSS = """
    #search {
        dock: top;
        margin: 0 1;
    }
    #body {
        height: 1fr;
    }
    #results {
        width: 2fr;
    }
    #detail-pane {
        width: 1fr;
        border-left: solid $primary;
        padding: 0 1;
    }
    #detail {
        height: auto;
    }
    #actions Button {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("t", "toggle_type", "TV/Movie"),
        ("r", "refresh_selected", "Refresh"),
        ("escape", "focus_search", "Search"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.media_type = MediaType.TV
        self.config = load_media_config()
        self.results: dict[str, AggregatedResult] = {}
        self._search_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search shows… (t toggles TV/Movie)", id="search")
        with Horizontal(id="body"):
            yield DataTable(id="results", cursor_type="row")
            with VerticalScroll(id="detail-pane"):
                yield Static("Type to search.", id="detail")
                yield Vertical(id="actions")
        yield Footer()

    def on_mount(self) -> None:
        self._update_subtitle()
        table = self.query_one(DataTable)
        table.add_column("Title", key="title", width=40)
        table.add_column("Year", key="year", width=6)
        for instance in self.config.arr_instances(self.media_type.value):
            table.add_column(instance.name, key=instance.name)
        for warning in self.config.warnings:
            self.notify(warning, severity="warning", timeout=8)
        self.query_one(Input).focus()

    def _update_subtitle(self) -> None:
        instances = self.config.arr_instances(self.media_type.value)
        self.sub_title = f"{self.media_type.value.upper()} — {len(instances)} instances, {len(self.config.plex)} plex"

    def _rebuild_columns(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_column("Title", key="title", width=40)
        table.add_column("Year", key="year", width=6)
        for instance in self.config.arr_instances(self.media_type.value):
            table.add_column(instance.name, key=instance.name)

    # --- search -------------------------------------------------------------

    @on(Input.Changed, "#search")
    def debounce_search(self, event: Input.Changed) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
        query = event.value.strip()
        if len(query) < 2:
            return
        self._search_timer = self.set_timer(0.5, lambda: self.run_search(query))

    @on(Input.Submitted, "#search")
    def submit_search(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if query:
            self.run_search(query)
        self.query_one(DataTable).focus()

    @work(exclusive=True, group="search")
    async def run_search(self, query: str) -> None:
        results = await search_everywhere(query, self.media_type, self.config)
        self.results = {r.result.external_key: r for r in results[:20]}

        table = self.query_one(DataTable)
        table.clear()
        for key, aggregated in self.results.items():
            row = [aggregated.result.title, str(aggregated.result.year or "")]
            for instance in self.config.arr_instances(self.media_type.value):
                status = aggregated.status_for(instance.name)
                row.append(STATE_GLYPHS[status.state] if status else "?")
            table.add_row(*row, key=key)
        if self.results:
            table.focus()
        else:
            self.query_one("#detail", Static).update("No results.")

    # --- detail / plex ------------------------------------------------------

    @on(DataTable.RowHighlighted)
    def show_detail(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value not in self.results:
            return
        aggregated = self.results[event.row_key.value]
        self._render_detail(aggregated)
        self.check_plex(aggregated)

    @work(exclusive=True, group="plex")
    async def check_plex(self, aggregated: AggregatedResult) -> None:
        if not self.config.plex or aggregated.plex:
            return
        await check_plex_availability(aggregated, self.config)
        self._render_detail(aggregated)

    def _render_detail(self, aggregated: AggregatedResult) -> None:
        r = aggregated.result
        lines = [f"[bold]{r.title}[/] ({r.year or '?'})"]
        meta = " · ".join(
            x
            for x in (
                r.network,
                r.status,
                f"{r.season_count} seasons" if r.season_count else "",
                f"{r.runtime}m" if r.runtime else "",
            )
            if x
        )
        if meta:
            lines.append(f"[dim]{meta}[/]")
        if r.genres:
            lines.append(f"[dim]{', '.join(r.genres[:4])}[/]")
        lines.append("")
        for status in aggregated.statuses:
            glyph = STATE_GLYPHS[status.state]
            line = f"{glyph} {status.instance}: {STATE_LABELS[status.state]}"
            if status.state == PresenceState.MONITORED_INCOMPLETE and status.missing_episode_count is not None:
                line += f" — missing {status.missing_episode_count}/{status.total_episode_count} eps"
            lines.append(line)
            for season in sorted(status.seasons, key=lambda s: (s.season_number == 0, s.season_number)):
                label = "SP" if season.season_number == 0 else f"S{season.season_number}"
                mark = "[green]✓[/]" if season.monitored else "[dim]✗[/]"
                counts = f"{season.episode_file_count}/{season.episode_count}" if season.episode_count else "—"
                lines.append(f"    {mark} {label:<4} {counts}")
        if aggregated.plex:
            lines.append("")
            for plex in aggregated.plex:
                glyph = "[green]▶[/]" if plex.available else "[dim]·[/]"
                note = "watch-ready" if plex.available else ("error" if plex.error else "not in Plex")
                lines.append(f"{glyph} {plex.server}: {note}")
        elif self.config.plex:
            lines.append("\n[dim]checking plex…[/]")
        if r.overview:
            lines.append(f"\n[dim]{r.overview[:400]}[/]")
        self.query_one("#detail", Static).update("\n".join(lines))
        self._render_actions(aggregated)

    def _render_actions(self, aggregated: AggregatedResult) -> None:
        actions = self.query_one("#actions", Vertical)
        actions.remove_children()
        for status in aggregated.statuses:
            if status.state == PresenceState.NOT_PRESENT:
                button = Button(f"Add to {status.instance}", variant="success")
                button.instance_name = status.instance  # type: ignore[attr-defined]
                button.result_key = aggregated.result.external_key  # type: ignore[attr-defined]
                actions.mount(button)

    # --- actions ------------------------------------------------------------

    @on(Button.Pressed)
    def add_pressed(self, event: Button.Pressed) -> None:
        instance = getattr(event.button, "instance_name", None)
        key = getattr(event.button, "result_key", None)
        if instance and key and key in self.results:
            event.button.disabled = True
            self.do_add(self.results[key], instance)

    @work(group="add")
    async def do_add(self, aggregated: AggregatedResult, instance: str) -> None:
        result = await add_to_instance(aggregated, instance, self.config)
        if result.ok:
            self.notify(result.message)
            await self._refresh_result(aggregated)
        else:
            self.notify(result.message, severity="error", timeout=8)

    def action_toggle_type(self) -> None:
        self.media_type = MediaType.MOVIE if self.media_type == MediaType.TV else MediaType.TV
        self._update_subtitle()
        self.results = {}
        self._rebuild_columns()
        self.query_one("#detail", Static).update("Type to search.")
        self.query_one("#actions", Vertical).remove_children()
        query = self.query_one(Input).value.strip()
        if len(query) >= 2:
            self.run_search(query)

    def action_refresh_selected(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is None or not self.results:
            return
        row_key = list(self.results)[table.cursor_row] if table.cursor_row < len(self.results) else None
        if row_key:
            self.refresh_row(self.results[row_key])

    @work(exclusive=True, group="refresh")
    async def refresh_row(self, aggregated: AggregatedResult) -> None:
        await self._refresh_result(aggregated)
        self.notify("Refreshed.")

    async def _refresh_result(self, aggregated: AggregatedResult) -> None:
        from ..media.aggregation import refresh_status

        updated = await refresh_status(aggregated, self.config, include_plex=bool(self.config.plex))
        key = updated.result.external_key
        self.results[key] = updated

        table = self.query_one(DataTable)
        for instance in self.config.arr_instances(self.media_type.value):
            status = updated.status_for(instance.name)
            if status:
                try:
                    table.update_cell(key, instance.name, STATE_GLYPHS[status.state])
                except Exception:  # noqa: BLE001 — row may be gone after a new search
                    pass
        self._render_detail(updated)

    def action_focus_search(self) -> None:
        self.query_one(Input).focus()


def run_tui() -> None:
    MediaRemote().run()
