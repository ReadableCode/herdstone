"""Fan-out search/status/add across all configured instances.

This is the shared core both UIs call. Every function degrades gracefully:
an unreachable instance becomes an UNREACHABLE status entry, never an exception
that kills the whole search.
"""

import asyncio

from .clients import PlexClient, RadarrClient, SonarrClient
from .config import ArrInstance, MediaConfig, load_media_config
from .models import (
    AddResult,
    AggregatedResult,
    EpisodeDetail,
    InstanceStatus,
    MediaType,
    PresenceState,
)


def _client_for(instance: ArrInstance, media_type: MediaType) -> SonarrClient | RadarrClient:
    return SonarrClient(instance) if media_type == MediaType.TV else RadarrClient(instance)


def _external_key(item: dict, media_type: MediaType) -> str:
    if media_type == MediaType.TV and item.get("tvdbId"):
        return f"tvdb:{item['tvdbId']}"
    if media_type == MediaType.MOVIE and item.get("tmdbId"):
        return f"tmdb:{item['tmdbId']}"
    return f"title:{item.get('title', '').casefold()}:{item.get('year') or 0}"


def merge_lookups(
    per_instance: dict[str, list[dict] | Exception],
    media_type: MediaType,
    config: MediaConfig,
) -> list[AggregatedResult]:
    """Merge per-instance lookup results into one AggregatedResult per unique title.

    Merging is keyed on external IDs (TVDB/TMDB), not title strings, so
    similarly-named shows never collapse into one entry. Every configured
    instance gets a status row on every result: NOT_PRESENT when its search
    didn't have the title, UNREACHABLE when the instance itself errored.
    """
    merged: dict[str, AggregatedResult] = {}
    items_by_key: dict[str, dict[str, dict]] = {}  # key -> instance -> raw item

    for instance in config.arr_instances(media_type.value):
        results = per_instance.get(instance.name)
        if isinstance(results, Exception) or results is None:
            continue
        client = _client_for(instance, media_type)
        for item in results:
            key = _external_key(item, media_type)
            if key not in merged:
                merged[key] = AggregatedResult(result=client.to_search_result(item))
            items_by_key.setdefault(key, {})[instance.name] = item

    for aggregated_key, aggregated in merged.items():
        for instance in config.arr_instances(media_type.value):
            results = per_instance.get(instance.name)
            if isinstance(results, Exception):
                aggregated.statuses.append(
                    InstanceStatus(
                        instance=instance.name,
                        state=PresenceState.UNREACHABLE,
                        error=str(results),
                    )
                )
                continue
            client = _client_for(instance, media_type)
            item = items_by_key.get(aggregated_key, {}).get(instance.name)
            aggregated.statuses.append(client.to_status(item))

    return list(merged.values())


async def search_everywhere(
    query: str,
    media_type: MediaType,
    config: MediaConfig | None = None,
) -> list[AggregatedResult]:
    """Search all Sonarr (tv) or Radarr (movie) instances concurrently and merge."""
    if config is None:
        config = load_media_config()
    instances = config.arr_instances(media_type.value)
    if not instances:
        return []

    clients = [_client_for(i, media_type) for i in instances]
    results = await asyncio.gather(*(c.lookup(query) for c in clients), return_exceptions=True)
    per_instance: dict[str, list[dict] | Exception] = {
        c.name: r for c, r in zip(clients, results)  # type: ignore[misc]
    }
    return merge_lookups(per_instance, media_type, config)


async def check_plex_availability(
    aggregated: AggregatedResult,
    config: MediaConfig | None = None,
) -> AggregatedResult:
    """Annotate a result with watch-readiness across all Plex servers."""
    if config is None:
        config = load_media_config()
    clients = [PlexClient(s) for s in config.plex]
    aggregated.plex = list(await asyncio.gather(*(c.check_presence(aggregated.result) for c in clients)))
    return aggregated


async def refresh_status(
    aggregated: AggregatedResult,
    config: MediaConfig | None = None,
    include_plex: bool = True,
) -> AggregatedResult:
    """Re-poll every instance (and optionally Plex) for one title by its external ID."""
    if config is None:
        config = load_media_config()
    result = aggregated.result
    # tvdb:/tmdb: keys work as lookup terms; title-keyed results fall back to a title search
    term = result.title if result.external_key.startswith("title:") else result.external_key

    refreshed = await search_everywhere(term, result.media_type, config)
    for candidate in refreshed:
        if candidate.result.external_key == result.external_key:
            if include_plex:
                await check_plex_availability(candidate, config)
            return candidate

    # Nothing came back (e.g. all instances down) — keep what we had
    return aggregated


async def episodes_everywhere(
    aggregated: AggregatedResult,
    config: MediaConfig | None = None,
) -> dict[str, list[EpisodeDetail]]:
    """Fetch the full episode list from every instance that has the series.

    Returns instance name -> episodes; instances without the series (or that
    error) are omitted.
    """
    if config is None:
        config = load_media_config()
    if aggregated.result.media_type != MediaType.TV:
        return {}

    targets = [
        (instance, status.series_id)
        for instance in config.sonarr
        for status in [aggregated.status_for(instance.name)]
        if status is not None and status.series_id
    ]
    if not targets:
        return {}

    async def _fetch(instance: ArrInstance, series_id: int) -> list[EpisodeDetail]:
        return await SonarrClient(instance).get_episodes(series_id)

    results = await asyncio.gather(
        *(_fetch(i, sid) for i, sid in targets),
        return_exceptions=True,
    )
    return {
        instance.name: episodes
        for (instance, _), episodes in zip(targets, results)
        if not isinstance(episodes, BaseException)
    }


async def add_to_instance(
    aggregated: AggregatedResult,
    instance_name: str,
    config: MediaConfig | None = None,
    quality_profile: str = "",
) -> AddResult:
    """Add the title to one specific instance, using its default quality profile
    and root folder unless overridden."""
    if config is None:
        config = load_media_config()
    result = aggregated.result

    instance = next(
        (i for i in config.arr_instances(result.media_type.value) if i.name == instance_name),
        None,
    )
    if instance is None:
        return AddResult(instance=instance_name, ok=False, message=f"No such instance: {instance_name}")
    if quality_profile:
        instance.quality_profile = quality_profile

    client = _client_for(instance, result.media_type)
    try:
        if isinstance(client, SonarrClient):
            if not result.tvdb_id:
                return AddResult(instance=instance_name, ok=False, message="Result has no TVDB id")
            items = await client.lookup_by_tvdb(result.tvdb_id)
        else:
            if not result.tmdb_id:
                return AddResult(instance=instance_name, ok=False, message="Result has no TMDB id")
            items = await client.lookup_by_tmdb(result.tmdb_id)
        if not items:
            return AddResult(instance=instance_name, ok=False, message="Title not found by external id")
        item = items[0]
        if item.get("id"):
            return AddResult(instance=instance_name, ok=False, message="Already present on this instance")

        profile_id, root_folder = await client.resolve_add_defaults()
        if isinstance(client, SonarrClient):
            await client.add_series(item, profile_id, root_folder)
        else:
            await client.add_movie(item, profile_id, root_folder)
    except Exception as exc:  # noqa: BLE001 — surfaced to the UI as a failed add
        return AddResult(instance=instance_name, ok=False, message=str(exc))

    return AddResult(instance=instance_name, ok=True, message=f"Added '{result.title}' to {instance_name}")


def search_and_merge(query: str, media_type: MediaType, config: MediaConfig | None = None):
    """Sync convenience wrapper for CLI/scripts."""
    return asyncio.run(search_everywhere(query, media_type, config))
