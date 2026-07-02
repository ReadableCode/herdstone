# Media Remote — Design Document

## 1. Summary

A fast, native-feeling personal remote for a home media stack that spans multiple
self-hosted instances. It replaces the couch-side use case of "open the clunky
Sonarr/Radarr web UI on my phone" with a single, fast, unified interface that
answers one question quickly — **"is this show/movie already somewhere in my
setup, and if not, where should I add it?"** — and lets you act on the answer
immediately.

This is not a replacement for Sonarr, Radarr, or Plex. It is a thin, fast client
that sits on top of their existing APIs and aggregates across multiple instances
of each.

## 2. Motivating Problem

The household media stack currently consists of:

- 2x Sonarr instances
- 2x Radarr instances
- 2x Plex servers

All reachable over Tailscale. The existing web UIs for Sonarr/Radarr are slow
and unpleasant on mobile, and there is no single place to answer "is this show
on server A, server B, or neither?" without opening multiple tabs and manually
cross-referencing.

## 3. Goals

- Search for a show or movie once, see its status across **all** configured
  instances of the relevant type (Sonarr x2 or Radarr x2), in one view.
- See, per instance: not present / monitored+downloading / fully available /
  missing episodes (for TV).
- Add a show/movie to a specific instance directly from the result view,
  without needing to know which instance to use ahead of time.
- Cross-check against Plex libraries to confirm something is actually
  watch-ready (present in Sonarr/Radarr ≠ watchable yet; present in Plex = done).
- Fast enough and pretty enough to use casually, one-handed, on a couch.
- Usable from **both** a TUI (for desktop/laptop/SSH use) and a web UI (for
  phone/tablet use) without maintaining two separate implementations of the
  business logic.
- Runs entirely on existing home hardware, reachable only over the Tailscale
  mesh. No cloud dependency, no AI dependency at runtime.

## 4. Non-Goals

- Not a media server. Not a download client. Not a *arr replacement.
- Not a general homelab dashboard — scope is intentionally narrow.
- Not building authentication/user-management infrastructure — this is a
  single-user (household) tool gated by Tailscale network membership.
- Not building a public multi-tenant product in v1 (see §12 for what a public
  version would require).

## 5. Architecture Principle: Shared Core, No Internal API Surface

The explicit design constraint: **there should be no separate backend REST API
that the frontend calls over HTTP as a distinct service.** Both the TUI and the
web UI are presentation layers over the *same* Python package, calling the same
functions in-process.

```
                     ┌─────────────────────────┐
                     │        core/            │
                     │  (pure Python package)  │
                     │                          │
                     │  - config/servers.yaml   │
                     │  - clients (Sonarr,      │
                     │    Radarr, Plex)         │
                     │  - aggregation logic     │
                     │  - domain models         │
                     └─────────┬────────┬───────┘
                                │        │
                     imports directly, in-process
                                │        │
                 ┌──────────────┘        └──────────────┐
                 ▼                                        ▼
        ┌─────────────────┐                     ┌──────────────────┐
        │   tui/ (Textual) │                     │  web/ (NiceGUI)   │
        │  runs on laptop  │                     │  runs as a single │
        │  via SSH/local   │                     │  process on a     │
        └─────────────────┘                     │  home server,     │
                                                   │  serves browser   │
                                                   │  over Tailscale   │
                                                   └──────────────────┘
```

Key point on the web UI: **NiceGUI** (or an equivalent Python-native UI
framework — Reflex is a fallback option) is recommended specifically because it
lets you write server-rendered UI code that calls `core` functions directly, in
the same process, with no hand-built JSON API layer, no separate frontend
build step calling `fetch()` against your own endpoints. There is still, by
necessity, one process listening on a port to serve the browser — that is
unavoidable for a phone to reach it — but it is a single monolithic process,
not a client/server pair with a defined API contract between them. The TUI
process is entirely separate and never talks to the web process; both are
independent entry points into the same `core` package.

## 6. Core Package Design (`core/`)

### 6.1 Configuration

A single config file (`config.yaml`) defines the known instances:

```yaml
sonarr_instances:
  - name: "sonarr-behemoth"
    base_url: "http://100.x.x.x:8989"
    api_key: "${SONARR_BEHEMOTH_API_KEY}"
  - name: "sonarr-secondary"
    base_url: "http://100.x.x.x:8989"
    api_key: "${SONARR_SECONDARY_API_KEY}"

radarr_instances:
  - name: "radarr-behemoth"
    base_url: "http://100.x.x.x:7878"
    api_key: "${RADARR_BEHEMOTH_API_KEY}"
  - name: "radarr-secondary"
    base_url: "http://100.x.x.x:7878"
    api_key: "${RADARR_SECONDARY_API_KEY}"

plex_servers:
  - name: "plex-behemoth"
    base_url: "http://100.x.x.x:32400"
    token: "${PLEX_BEHEMOTH_TOKEN}"
  - name: "plex-secondary"
    base_url: "http://100.x.x.x:32400"
    token: "${PLEX_SECONDARY_TOKEN}"
```

Secrets pulled from environment variables (`.env` locally), never hardcoded.
Config is a flat list per service type — deliberately designed so **adding a
third Sonarr instance later requires zero code changes**, only a config
addition.

### 6.2 Domain Models (pydantic)

- `MediaSearchResult` — normalized search hit (title, year, external IDs:
  TVDB/TMDB, poster URL)
- `InstanceStatus` — per-instance presence for a given title: `NOT_PRESENT`,
  `MONITORED_INCOMPLETE`, `MONITORED_COMPLETE`, with episode-level detail for
  TV (`missing_episode_count`, `total_episode_count`)
- `PlexAvailability` — per-Plex-server watch-readiness for a given title
- `AggregatedResult` — the single object the UI layers render: one title, with
  a status per Sonarr/Radarr instance and per Plex server

### 6.3 Service Clients

Thin async clients (using `httpx`) per service:

- `SonarrClient` — search, lookup by TVDB ID, get series status, get episode
  list/missing count, add series
- `RadarrClient` — search, lookup by TMDB ID, get movie status, add movie
- `PlexClient` — library search by title/external ID, presence check

Each client wraps the relevant service's existing REST API (Sonarr and Radarr
both expose well-documented REST APIs; Plex has an unofficial but
well-understood API accessed via `plexapi`, which is recommended over hand-
rolling HTTP calls).

### 6.4 Aggregation Layer

This is the actual "interesting" logic and the core value of the app:

- `search_everywhere(query: str) -> list[AggregatedResult]` — fan out a search
  across all configured Sonarr **or** Radarr instances concurrently
  (`asyncio.gather`), merge results by external ID (TVDB/TMDB — not by title
  string, to avoid false matches on similarly-named shows), and produce one
  `AggregatedResult` per unique title showing status across every instance.
- `check_plex_availability(result: AggregatedResult) -> AggregatedResult` —
  cross-reference against all Plex servers to annotate watch-readiness.
- `add_to_instance(result, instance_name, quality_profile) -> AddResult` —
  route an add action to a specific chosen instance.
- `refresh_status(result) -> AggregatedResult` — re-poll for updated
  download/episode status (used for a manual refresh action, not polling).

All of this lives in `core/` and is exercised identically by both UIs.

## 7. TUI Design (Textual)

- Single search bar at the top (fuzzy, debounced, hits `search_everywhere`)
- Results list below, each row showing: poster (ASCII/sixel if terminal
  supports it, otherwise skip), title, year, and a compact status glyph row —
  one glyph per configured instance (e.g. `●` = complete, `◐` = partial, `○` =
  not present), plus a Plex glyph for watch-ready
- Selecting a result opens a detail panel: full per-instance breakdown, missing
  episode count if applicable, and action buttons (`Add to sonarr-behemoth`,
  `Add to sonarr-secondary`, etc.) — buttons only appear for instances where
  the title is not already present
- Keyboard-driven throughout; no mouse required

## 8. Web UI Design (NiceGUI)

- Same information architecture as the TUI: search bar, result cards, detail
  view, add actions
- Optimized for one-handed phone use: large tap targets, minimal chrome,
  instant search-as-you-type against `search_everywhere`
- Runs as a single process on one home server (Behemoth is the natural choice
  as the always-on box), bound to the Tailscale interface only — not exposed
  to the public internet
- No login system in v1: access control is "you're on the tailnet or you're
  not." (See §11 for a lightweight upgrade path if that's ever insufficient.)

## 9. Typical Flow: "Is this show already downloaded somewhere?"

1. User opens web UI on phone (or TUI on laptop), types show name.
2. `search_everywhere()` fans out to both Sonarr instances concurrently,
   normalizes and merges results by TVDB ID.
3. UI renders one card per unique show with a status glyph per instance.
4. User taps the card → detail view fires `check_plex_availability()` to
   annotate both Plex servers.
5. If not present anywhere: user taps "Add to sonarr-secondary" →
   `add_to_instance()` is called, confirmation shown inline.
6. If present but incomplete: missing episode count shown directly, no action
   needed beyond visibility.

## 10. Repository Structure

```
media-remote/
├── core/
│   ├── config.py          # loads + validates config.yaml
│   ├── models.py          # pydantic domain models
│   ├── clients/
│   │   ├── sonarr.py
│   │   ├── radarr.py
│   │   └── plex.py
│   └── aggregation.py     # search_everywhere, add_to_instance, etc.
├── tui/
│   └── app.py              # Textual entry point, imports core directly
├── web/
│   └── app.py              # NiceGUI entry point, imports core directly
├── config.yaml
├── .env.example
├── pyproject.toml
└── README.md
```

Both `tui/app.py` and `web/app.py` are thin — their only job is rendering and
wiring user actions to `core` functions. Neither contains business logic.

## 11. Security Notes

- All services bound to Tailscale interfaces only, never `0.0.0.0` on a
  publicly routable interface.
- API keys/tokens loaded from environment, never committed.
- Given single-user/household scope and Tailscale-only exposure, no
  additional auth layer is planned for v1. If this is ever run somewhere
  reachable beyond the tailnet, a simple shared-token check should be added
  to the NiceGUI entry point before that happens — noted here so it isn't
  forgotten later, not because it's needed now.

## 12. Path to Public/Shareable (Optional, Not v1)

If this were ever generalized for others:

- Config becomes user-supplied (already designed as a flat list, so this is
  mostly already true)
- Would need per-user config isolation and basic auth
- Aggregation logic (`core/`) is already service-agnostic enough to publish
  as a standalone library independent of the UI layers
- Not a goal for the initial 3-4 day build — noted only so early decisions
  (like the flat instance-list config) don't paint us into a corner

## 13. Suggested Build Order (3–4 Days)

**Day 1 — Core plumbing**
- Config loading + models
- Sonarr and Radarr clients (search, status, add) against real instances
- `search_everywhere` + merge-by-external-ID logic, tested against real data

**Day 2 — Plex + aggregation polish**
- Plex client, `check_plex_availability`
- Edge cases: title collisions, instances offline/unreachable (must degrade
  gracefully — one instance being down shouldn't break the whole search)
- Manual CLI smoke test of `core` with no UI yet

**Day 3 — TUI**
- Textual app wired to `core`
- Search, result list, detail view, add action, refresh action

**Day 4 — Web UI**
- NiceGUI app wired to `core`, mirroring TUI feature set
- Mobile layout pass
- Deploy as a long-running process on Behemoth (systemd unit or Docker
  container with explicit `container_name`, per existing homelab convention)

## 14. Open Questions for Fable to Flag Back

- Exact Sonarr/Radarr API versions in use (v3 API assumed; confirm against
  actual instance versions before building clients).
- Whether `plexapi` is preferred over raw HTTP for the Plex client (recommended
  default: yes, use `plexapi`).
- Whether quality profile selection needs to be exposed at add-time in v1, or
  whether a sane default profile per instance is acceptable initially.
- Confirm episode-level "missing" detection approach (Sonarr exposes this
  directly per series; no need to compute manually).
