# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

### Changed

### Fixed

## [0.3.1] - 2026-06-03

### Added

- Slack Socket Mode support now covers app mentions, self-targeting replies,
  channel metadata, and threaded response routing across onboarding and channel
  runtime paths.
- Short-drama and video helper workflows remain available in the bundled
  MetaSkill catalog, with stronger Windows-safe script handling and clearer
  review pauses for generated media flows.
- CI impact-surface gates classify docs, runtime, dependency, release, and test
  changes so pull requests can run the right checks without forcing the full
  matrix for every documentation-only edit.

### Changed

- WebChat and the Skills view now make MetaSkill readiness, active runs, and
  install visibility easier to inspect while workflows are being reviewed.
- Release install documentation and installer defaults now point to the 0.3.1
  wheel and Windows portable asset names.

### Fixed

- User chat bubbles preserve multiline text and read like authored messages
  instead of collapsing or visually blending with generated output.
- Slack onboarding and runtime paths now reject incomplete Socket Mode setup,
  preserve existing secrets, enforce webhook signing secrets where needed, and
  keep threaded reply channel context.
- Voice/audio workflows and clarification pauses are represented on the main
  release line, so release users get the same usable handoff and resume
  behavior already validated on integration branches.
- Provider request hardening keeps malformed tool-call history from reaching
  providers as invalid request state.

### Acknowledgements

- Thanks @openvictory for #123, #133, and #137, which helped bring visible
  running-state feedback plus short-drama and media helper workflows into the
  0.3.1 release line.
- Thanks @freeaccount-create for #142, which helped bring Slack Socket Mode and
  self-targeting replies into the channel workflow.
- Thanks @ruhook for #124, and thanks @qq712696307 for the authored commit in
  that pull request, which preserved user message newlines in WebChat.
- Thanks @Cola-Alex for #143, which increased tokenjuice summarize and
  failure-context windows for fallback tool-result projection.
- Thanks @nice-code-la for #165 and #166, which helped make voice workflows
  usable end to end and clarification pauses resume cleanly.

## [0.3.0] - 2026-05-31

### Added

- MetaSkills are now first-class workflow capabilities: bundled stable
  MetaSkills, composition parsing, step scheduling, pause/resume user-input
  flows, proposal gates, runtime history, and authoring documentation let
  repeatable multi-step work become reusable agent routines.
- `opensquilla doctor` and the WebUI Health view now provide actionable
  readiness diagnostics across provider, gateway, memory, logs, search, image
  generation, router, channels, sandbox, and embedding surfaces.
- Tokenjuice-backed tool-result projection now compacts large logs, diffs,
  JSON, test output, package-manager output, and other known tool shapes before
  they crowd out provider context.
- A task-oriented documentation set now covers quickstart, configuration,
  WebUI, CLI, tools and sandboxing, sessions, providers, usage and cost,
  memory, compaction, MetaSkills, tool compression, scheduling, channels, MCP,
  troubleshooting, and contribution guidance.

### Changed

- Tool-output context management now separates durable runtime results from
  provider-visible compact previews, records projection telemetry, and uses
  provider request proof/compaction before oversized payloads reach an LLM.
- WebChat, CLI chat, and terminal TUI internals now share more runtime-backed
  turn, stream, slash-command, artifact, attachment, and recovery behavior.
- Long-session memory and compaction flows now preserve raw archive evidence,
  checkpoint receipts, repair queues, and WebUI-safe compaction status instead
  of treating semantic memory quality and context safety as the same signal.
- Channel install extras now expose only real optional packages; Feishu,
  Telegram, DingTalk, WeCom, and QQ are included in the base install instead
  of being accepted as no-op extras.

### Fixed

- WebChat reliability fixes cover router replay, session restore gaps,
  duplicate compaction status, attachment and pasted-text rendering, artifact
  downloads, composer layout, model-router animation timing, and visible
  recovery during long turns.
- Provider and runtime hardening reduces malformed tool-call fallout, preserves
  configured model-switch intent, handles provider tool-choice requirements,
  and keeps oversized current-turn tool payloads from surfacing as bare
  internal failures.
- Cross-platform CI and Windows portability fixes stabilize CLI help rendering,
  sqlite fallback behavior, UTF-8 subprocess handling, Windows-only test
  fixtures, onboarding commands, and release-surface checks.

## [0.2.1] - 2026-05-21

### Changed

- WebUI diagnostics, transcript replay, and artifact presentation now retain
  more turn-usage evidence while keeping generated-file markers out of normal
  chat output.
- Long-running agent turns now expose softer recovery paths for exhausted tool
  budgets, repeated tool failures, large file-write attempts, and artifact
  delivery handoffs when the final model response degrades.
- Release metadata, installer defaults, and documented wheel URLs now point to
  the 0.2.1 release line.

### Fixed

- Windows portable startup now includes a stronger Visual C++ runtime bootstrap
  path for the bundled ONNX router.
- Memory semantic recall now normalizes stored and query embeddings before
  sqlite-vec search, and high-confidence lexical matches are preserved even
  when vector scoring is weak.
- Generated artifact placeholder text is removed from WebChat history and
  channel-facing output after files have already been delivered.
- Tool dispatch and result budgeting reduce bare internal budget failures by
  returning model-visible recovery context when a turn can still continue.

### Acknowledgements

- Thanks @nice-code-la for the portable Windows VC++ runtime bootstrap work in
  #52.

## [0.2.0] - 2026-05-20

### Added

- `opensquilla migrate` imports existing OpenClaw/Hermes homes into OpenSquilla
  with dry-run previews, explicit `--apply`, source auto-detection, migration
  reports, memory/persona conflict handling, skill compatibility reporting, and
  MCP/channel config mapping.
- `opensquilla chat` is now an early usable interactive CLI chat surface with a
  persistent terminal UI, streaming output, queued input, slash-mode discovery,
  prompt/status chrome, tool-call feedback, inline approval handling, and
  deterministic live prompt output.
- Cron automation now spans CLI, WebUI, RPC, channel, and webhook surfaces:
  structured schedule creation, timezone-aware cron/every/at schedules,
  exact/jitter controls, manual runs, channel delivery, webhook delivery, and
  failure destinations.
- Feishu and Discord channel support now includes capability manifests, safer
  DM/group policy metadata, native file/artifact paths, attachment ingestion,
  Feishu websocket/webhook handling, Discord thread/group handling, and clearer
  channel health/status reporting.
- OpenSquilla can run as an inbound MCP server bridge for session workflows:
  clients can list sessions, resolve/read conversation history, send messages,
  and wait for session events through the gateway.
- Generated artifact delivery is more complete across WebUI and channels,
  including traceable generated-file delivery, recovered fallback delivery,
  channel-safe artifact text, and Unicode-safe PDF report rendering.
- Memory surfaces now separate curated memory from raw transcript search, recall
  prior-session evidence, keep manual Dream runs on configured memory
  workspaces, and let compaction continue when memory flush degrades.
- Release/install support now includes versioned release URLs,
  latest-download aliases, reproducible wheel/portable release guidance,
  source install scripts, Windows portable hardening, ONNX/router recovery
  messaging, and Docker/compose alignment on the gateway port.

### Changed

- Release installation docs now use 0.2.0 release asset URLs and
  `/releases/latest/download/` aliases for the current wheel and Windows
  portable zip.
- Cron tool calls now require structured schedule input (`{kind, ...}`) instead
  of backend natural-language schedule parsing. CLI cron flags still accept
  standard user-facing forms such as `--cron`, `--every`, `--at`, and
  `--expression` through RPC compatibility paths.
- Tool dispatch now runs through a policy pipeline with side-effect-aware
  concurrency: safe/read-only tools can batch, while mutating or
  side-effecting tools stay serialized, keyed, or capped.
- Long-running agent turns now use staged `TurnRunner` execution, provider
  request-budget compaction, prompt-cache anchor preservation, bounded
  tool-result storage, approval-aware retry handling, and recovery paths for
  malformed or non-executable tool calls.
- Channel adapters now declare normalized capability and error-taxonomy
  metadata so unsupported, degraded, retryable, and fatal channel behavior is
  surfaced more consistently.
- WebUI chat, sessions, usage, setup, cron, and search surfaces now share more
  runtime-backed state for recency ordering, per-turn token metrics, provider
  badges, setup form behavior, and session cancellation/readback.
- The default gateway/release documentation now centers on port `18791`, and
  release download paths use the current 0.2.0 assets.

### Fixed

- Failed or aborted turns are kept out of later provider context, reducing
  cascading failures after a bad turn.
- Approval-gated tool retries wait for operator decisions instead of exposing
  pending approval state as ordinary model-visible tool output.
- Provider-context tool markers are protected from becoming executable tool
  state.
- High-volume tool and chat turns recover more reliably from request-tail bloat,
  current-turn tool overflow, and provider payload budget pressure.
- Channel replies avoid leaking provider compaction markers, and channel cron
  delivery now reports failures explicitly.
- WebUI reliability fixes cover recency ordering, table boundaries, mobile and
  composer layout, duplicate visible toasts, setup form resilience, search
  provider badges, and session cancellation counters.
- Generated files that were omitted from normal delivery can be recovered
  through the artifact fallback path.
- Feishu-delivered PDF reports now render Unicode text instead of black or
  placeholder glyph blocks.

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
