# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

### Changed

### Fixed

## [0.1.0rc1] - 2026-05-12

### Added

- OOTB startup path: `compose.yaml` + `start.sh` + `start.ps1` + Quickstart section in README.
- Legacy `memory.*` config fields: 16 deprecated keys silently dropped with a single aggregated `DeprecationWarning`.
- Agent CLI no-key error: three-section actionable panel (Symptom / Cause / Next steps).
- Tool concurrency: same-turn safe `tool_calls` dispatched concurrently via `asyncio.gather` (22 safe tools enrolled in `_SAFE_TOOL_NAMES`; mutex tools remain serial).
- PID file lock to prevent two gateway instances from sharing the same state directory.
- Core observability counters: `opensquilla_queue_depth`, `in_flight_turns_total`, `turn_cancellations_total`, `queue_full_errors_total`.
- CI matrix on `ubuntu-latest` and `windows-latest` × Python 3.11/3.12, including a metric-name drift check and a tracemalloc leak smoke step.
- Per-channel-adapter in-flight reply cap (`_ChannelInFlightSet`) so a single channel cannot exhaust the global concurrency budget.
- Cross-session fair queueing: sessions sharing an `agent_id` round-robin available slots by completion count.
- Session epoch counter so events from a pre-reset turn are discarded by the frontend after `session.reset`.
- Atomic write helper for transcript attachments (`_atomic_write_bytes`): tmp + fsync + `os.replace`.
- Concurrency env overrides — `OPENSQUILLA_TASK_MAX_CONCURRENCY` and `OPENSQUILLA_CHANNEL_INFLIGHT_CAP` — with invalid-value fallback and warning logs.

### Changed

- Internal SquillaRouter package moved from `opensquilla.contrib.squilla_router`
  to `opensquilla.squilla_router`; bundled model assets now live under
  `src/opensquilla/squilla_router/models/`.
- `TurnRunner` and `TaskRuntime` share a single per-session `asyncio.Lock` (injected via `session_lock_provider`), removing the two-layer lock dictionary and the reverse-acquire risk it created.

### Fixed

- Channel adapter ghost-turn bug: a `TaskQueueFullError` no longer leaves a dangling user message in the transcript.
- `TaskRuntime` terminal-state dictionary leak across `_tasks`, `_session_locks`, and `_pending_by_session`.
