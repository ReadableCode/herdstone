"""Media remote web UI — a thin NiceGUI layer over engine.media.

Single process, server-rendered, calls core functions in-process (no internal
REST API). Meant to run on an always-on box, bound to the Tailscale interface.
All business logic lives in engine/media; this file only renders.
"""

from ..media.aggregation import (
    add_to_instance,
    check_plex_availability,
    enrich_tv_statuses,
    refresh_status,
    search_everywhere,
)
from ..media.config import MediaConfig, load_media_config
from ..media.models import AggregatedResult, MediaType, PresenceState

STATE_BADGE = {
    PresenceState.MONITORED_COMPLETE: ("● complete", "green"),
    PresenceState.MONITORED_INCOMPLETE: ("◐ partial", "orange"),
    PresenceState.NOT_PRESENT: ("○ not present", "grey"),
    PresenceState.UNREACHABLE: ("✗ unreachable", "red"),
}


def _short(instance_name: str) -> str:
    """Compact instance label for badges: 'sonarr-behemoth' -> 'behemoth'."""
    return instance_name.split("-", 1)[-1]


def run_web(host: str = "127.0.0.1", port: int = 8787) -> None:
    from nicegui import ui

    config: MediaConfig = load_media_config()

    @ui.page("/")
    def index() -> None:  # noqa: C901 — page builder wires the whole UI
        state: dict = {"media_type": MediaType.TV}

        async def do_search() -> None:
            query = (search_box.value or "").strip()
            if len(query) < 2:
                return
            spinner.visible = True
            try:
                results = await search_everywhere(query, state["media_type"], config)
            finally:
                spinner.visible = False
            render_results(results[:20])

        def render_results(results: list[AggregatedResult]) -> None:
            results_area.clear()
            with results_area:
                if not results:
                    ui.label("No results.").classes("text-grey")
                for aggregated in results:
                    _result_card(aggregated)

        def _result_card(aggregated: AggregatedResult) -> None:
            r = aggregated.result
            with (
                ui.card()
                .classes("w-full cursor-pointer")
                .on("click", lambda a=aggregated: open_detail(a))
            ):
                with ui.row().classes("items-center no-wrap w-full gap-4"):
                    if r.poster_url:
                        ui.image(r.poster_url).classes("w-16 rounded shrink-0")
                    with ui.column().classes("gap-1 min-w-0"):
                        year = f" ({r.year})" if r.year else ""
                        ui.label(f"{r.title}{year}").classes("text-lg font-bold")
                        with ui.row().classes("gap-1"):
                            for status in aggregated.statuses:
                                label, color = STATE_BADGE[status.state]
                                ui.badge(f"{_short(status.instance)} {label}", color=color)

        async def open_detail(aggregated: AggregatedResult) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-md"):
                r = aggregated.result
                year = f" ({r.year})" if r.year else ""
                with ui.row().classes("items-start no-wrap w-full gap-4"):
                    if r.poster_url:
                        ui.image(r.poster_url).classes("w-24 rounded shrink-0")
                    with ui.column().classes("gap-1 min-w-0"):
                        ui.label(f"{r.title}{year}").classes("text-xl font-bold")
                        meta = " · ".join(
                            x
                            for x in (
                                r.network,
                                r.status,
                                f"{r.season_count} seasons" if r.season_count else "",
                                ", ".join(r.genres[:3]),
                            )
                            if x
                        )
                        if meta:
                            ui.label(meta).classes("text-xs text-grey")
                        if r.overview:
                            ui.label(r.overview[:300]).classes("text-sm text-grey")

                status_area = ui.column().classes("w-full gap-1")
                plex_area = ui.column().classes("w-full gap-1")
                action_area = ui.column().classes("w-full gap-2")

                def render_statuses() -> None:
                    status_area.clear()
                    with status_area:
                        for status in aggregated.statuses:
                            label, color = STATE_BADGE[status.state]
                            line = f"{status.instance}: {label}"
                            if (
                                status.state == PresenceState.MONITORED_INCOMPLETE
                                and status.missing_episode_count is not None
                            ):
                                line += f" — missing {status.missing_episode_count}/{status.total_episode_count} eps"
                            ui.label(line).classes(f"text-{color}")
                            if status.seasons:
                                chips = "  ".join(
                                    f"{'✓' if s.monitored else '✗'}"
                                    f"{'SP' if s.season_number == 0 else 'S' + str(s.season_number)}"
                                    f" {s.episode_file_count}/{s.total_episode_count or s.episode_count}"
                                    for s in sorted(
                                        status.seasons, key=lambda s: (s.season_number == 0, s.season_number)
                                    )
                                    if s.total_episode_count or s.episode_count or s.monitored
                                )
                                if chips:
                                    ui.label(chips).classes("text-xs text-grey pl-4")

                    action_area.clear()
                    with action_area:
                        for status in aggregated.statuses:
                            if status.state == PresenceState.NOT_PRESENT:
                                ui.button(
                                    f"Add to {status.instance}",
                                    on_click=lambda s=status: do_add(s.instance),
                                ).classes("w-full").props("size=lg color=positive")

                def render_plex() -> None:
                    plex_area.clear()
                    with plex_area:
                        for plex in aggregated.plex:
                            if plex.available:
                                ui.label(f"▶ {plex.server}: watch-ready").classes("text-green font-bold")
                            elif plex.error:
                                ui.label(f"✗ {plex.server}: unreachable").classes("text-red")
                            else:
                                ui.label(f"· {plex.server}: not in library").classes("text-grey")

                async def do_add(instance_name: str) -> None:
                    add_result = await add_to_instance(aggregated, instance_name, config)
                    ui.notify(
                        add_result.message,
                        color="positive" if add_result.ok else "negative",
                        position="top",
                    )
                    if add_result.ok:
                        refreshed = await refresh_status(aggregated, config, include_plex=False)
                        aggregated.statuses = refreshed.statuses
                        render_statuses()

                render_statuses()
                render_plex()
            dialog.open()

            if any(s.series_id for s in aggregated.statuses):
                await enrich_tv_statuses(aggregated, config)
                render_statuses()
            if config.plex and not aggregated.plex:
                await check_plex_availability(aggregated, config)
                render_plex()

        async def on_toggle(e) -> None:
            state["media_type"] = e.value
            await do_search()

        # --- page layout ---
        with ui.column().classes("w-full max-w-2xl mx-auto p-4 gap-3"):
            with ui.row().classes("items-center w-full no-wrap gap-3"):
                ui.label("Herdstone Media").classes("text-2xl font-bold grow")
                ui.toggle(
                    {MediaType.TV: "TV", MediaType.MOVIE: "Movies"},
                    value=MediaType.TV,
                    on_change=on_toggle,
                ).props("no-caps")
            search_box = (
                ui.input(placeholder="Search…", on_change=do_search)
                .props('debounce=500 clearable outlined input-class="text-lg"')
                .classes("w-full")
            )
            spinner = ui.spinner(size="lg").classes("self-center")
            spinner.visible = False
            results_area = ui.column().classes("w-full gap-3")

            for warning in config.warnings:
                ui.notify(warning, color="warning", position="top")

    print(f"Herdstone Media web UI on http://{host}:{port}  (bind your Tailscale IP with --host to share)")
    ui.run(host=host, port=port, title="Herdstone Media", dark=True, reload=False, show=False)
