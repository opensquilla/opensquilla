# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others)
when working on code in this repository. It is the **orientation layer**: it
maps the whole repo and points at the per-module guides that own the depth. For
anything inside a module, read that module's docs rather than expecting full
detail here.

The sibling `CLAUDE.md` imports this file via `@AGENTS.md` so Claude Code and
other tools share one source of truth.

## What is OpenSquilla

OpenSquilla is a token-efficient, microkernel AI agent. A local model router
(SquillaRouter) sends each turn to the cheapest model that can handle it, while
persistent memory, a layered sandbox, built-in web search, and on-device
embeddings round out a single shared turn loop.

Every entry point — Web UI, CLI, terminal chat, and messaging channels
(Telegram, Slack, Feishu/Lark, Discord, DingTalk, WeCom, Matrix, QQ) — runs
through that same loop, so tool dispatch, retries, approvals, and decision
logging behave identically everywhere. A pluggable provider layer speaks to
TokenRhythm, OpenRouter, OpenAI, Anthropic, Ollama, DeepSeek, Gemini,
Qwen/DashScope, and 20+ other LLM providers with no code or config-schema
change.

OpenSquilla 0.5.0 Preview 3 is the current preview release.

For product-level orientation, start with
[`README.product.md`](README.product.md) and the
[`docs/README.md`](docs/README.md) documentation index.

## Repository Map

```
opensquilla/
├── AGENTS.md                      # This file — repo orientation for AI agents
├── CLAUDE.md                      # One-liner that imports AGENTS.md (Claude Code)
├── README.md / README.product.md  # Release & product-oriented READMEs (EN + 5 translations)
├── pyproject.toml                 # Python package, hatchling build, ruff/mypy config
├── uv.lock                        # Pinned transitive deps for uv
├── install.sh / install.ps1       # Cross-platform install scripts
├── start.sh / start.ps1           # Cross-platform launch scripts
├── compose.yaml                   # Docker Compose for home-server / NAS deployment
├── Dockerfile                     # Container image
├── opensquilla.toml.example       # Template for the user config file
├── src/opensquilla/               # Python package (the runtime)
│   ├── cli/                       # Typer CLI entry points: opensquilla, gateway
│   ├── gateway/                   # Local HTTP/WS server (Starlette) + control console
│   ├── engine/                    # Core turn runner, agent loop, streaming
│   ├── agents/                    # Durable agent profiles
│   ├── channels/                  # IM adapters (telegram, slack, feishu, discord, ...)
│   ├── mcp/                       # MCP tool registry consumed by the gateway
│   ├── mcp_server/                # stdio MCP server bridge (the [mcp] extra)
│   ├── skills/                    # Bundled + user skills (incl. bundled/, meta/, ...)
│   ├── squilla_router/            # Local model router (ONNX + LightGBM)
│   ├── provider/                  # LLM provider abstraction
│   ├── memory/                    # Durable memory + recall
│   ├── session/                   # Session store, transcript, replay
│   ├── scheduler/                 # APScheduler-backed cron
│   ├── tools/                     # Built-in tools (fs, shell, web, git, ...)
│   ├── sandbox/                   # Sandboxed execution posture
│   ├── safety/                    # Approvals, redaction
│   ├── persistence/               # SQLite store + yoyo migrations
│   ├── migrations/                # Hand-written SQL migrations (run by yoyo)
│   ├── observability/             # structlog + diagnostics surfaces
│   ├── onboarding/                # First-run wizard (`opensquilla onboard`)
│   ├── identity/                  # User identity + auth tokens
│   ├── contrib/                   # Vendored helpers (compat, redactors, ...)
│   ├── eval/                      # Benchmarks + golden tasks
│   └── ui.py                      # Shared rich/console helpers
├── desktop/                       # Electron desktop shell (Vue control console)
├── opensquilla-webui/             # Vue 3 control console served by the gateway
├── service-units/                 # OS service definitions (systemd / launchd / Windows svc)
├── Formula/                       # Homebrew tap formula
├── migrations/                    # SQL migrations mirrored into the wheel
├── scripts/                       # Maintenance, codegen, bench, replay, experiments
├── tests/                         # Pytest tree (auto-discovered; marker-gated live tests)
├── docs/                          # User-facing docs (gateway, channels, sessions, features/...)
│   ├── README.md                  # Docs index
│   ├── features/                  # One page per product feature
│   ├── authoring/                 # Meta-skill authoring rules
│   ├── releases/                  # Per-release notes
│   └── diagrams/                  # Long-form architecture sources (puml, drawio)
└── .github/                       # Issue + PR templates, CI workflows
```

## Service Topology

OpenSquilla is structured as one local Python runtime plus optional
co-located services. The smallest viable install is a single process.

| Component            | Default port | Role                                              |
| -------------------- | ------------ | ------------------------------------------------- |
| **Gateway**          | `18791`      | Starlette HTTP + WebSocket. Web UI, RPC, channels. |
| **Gateway WS**       | `18791/ws`   | Streaming RPC used by CLI, MCP bridge, channels.   |
| **Desktop app**      | —            | Electron shell that spawns/owns the gateway.       |
| **Web UI**           | `18791/`     | Vue 3 control console served by the gateway.       |
| **Cron scheduler**   | in-process   | APScheduler-driven, persists jobs to SQLite.       |

`gateway run --listen 0.0.0.0` exposes the gateway to other hosts — only do
this behind a trusted network boundary and explicit token auth.

## Per-Module Docs

For depth, follow the per-module docs. Each `docs/<module>.md` is the user-facing
guide; the source tree under `src/opensquilla/<module>/` owns the runtime.

- [`docs/gateway.md`](docs/gateway.md) — gateway lifecycle, host/port, graceful drain.
- [`docs/channels.md`](docs/channels.md) — IM adapters (Telegram, Slack, Feishu, ...).
- [`docs/sessions.md`](docs/sessions.md) — durable conversations, resume, abort, export.
- [`docs/agents.md`](docs/agents.md) — durable named agent profiles.
- [`docs/mcp-server.md`](docs/mcp-server.md) — stdio MCP bridge for MCP-capable clients.
- [`docs/cli.md`](docs/cli.md) — command groups and common workflows.
- [`docs/tui.md`](docs/tui.md) — terminal chat usage, slash commands.
- [`docs/web-ui.md`](docs/web-ui.md) — local control console.
- [`docs/configuration.md`](docs/configuration.md) — config file locations and keys.
- [`docs/providers-and-models.md`](docs/providers-and-models.md) — LLM provider catalog.
- [`docs/tools-and-sandbox.md`](docs/tools-and-sandbox.md) — built-in tools and sandbox posture.
- [`docs/approvals-and-permissions.md`](docs/approvals-and-permissions.md) — permissions + approvals.
- [`docs/usage-and-cost.md`](docs/usage-and-cost.md) — token usage and cost reports.
- [`docs/diagnostics-and-replay.md`](docs/diagnostics-and-replay.md) — diagnostics + read-only replay.
- [`docs/scheduling.md`](docs/scheduling.md) — cron-style scheduled runs.
- [`docs/docker.md`](docs/docker.md) — Docker / Compose deployment.
- [`docs/operations.md`](docs/operations.md) — operational commands (doctor, migrate, ...).
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — common install/runtime issues.
- [`docs/glossary.md`](docs/glossary.md) — user-facing terminology.

### Feature deep-dives

- [`docs/features.md`](docs/features.md) — feature catalog.
- [`docs/features/squilla-router.md`](docs/features/squilla-router.md) — local model router.
- [`docs/features/tui-frontend.md`](docs/features/tui-frontend.md) — TUI backends + plugin slots.
- [`docs/features/tool-compression.md`](docs/features/tool-compression.md) — compact tool results.
- [`docs/features/skills.md`](docs/features/skills.md) — skill discovery + lifecycle.
- [`docs/features/meta-skills.md`](docs/features/meta-skills.md) — composable multi-step workflows.
- [`docs/features/memory.md`](docs/features/memory.md) — durable recall.
- [`docs/features/compaction-and-cache.md`](docs/features/compaction-and-cache.md) — long-session continuity.
- [`docs/diagrams/architecture.md`](docs/diagrams/architecture.md) — long-form puml/drawio sources.

## Commands

The repo is a uv-managed Python project. Use `uv` for everything; `pip` is not
the supported workflow.

| Task                        | Command                                                                                          |
| --------------------------- | ------------------------------------------------------------------------------------------------ |
| Install (dev)               | `uv sync`                                                                                        |
| Run CLI                     | `uv run opensquilla <cmd>`                                                                       |
| Run gateway                 | `uv run opensquilla gateway run`                                                                 |
| Lint                        | `uv run ruff check`                                                                              |
| Format                      | `uv run ruff format`                                                                             |
| Type check                  | `uv run mypy`                                                                                    |
| Tests (offline)             | `uv run pytest -m "not llm and not live_channel and not live_search"`                            |
| Tests (live, gated)         | `uv run pytest -m "llm_smoke"` (and the other `llm_*` markers in `pyproject.toml`)               |
| Doctor                      | `uv run opensquilla doctor`                                                                      |
| TUI replay bench            | `uv run python scripts/bench_tui_replay.py --renderer opentui --fixture long-stream`             |

Marker-gated tests (LLM, channel, search) are opt-in; see the `markers` table in
`pyproject.toml` for the full list.

## Cross-Cutting Conventions

**Python style.** `ruff` with `target-version = "py312"`, `line-length = 100`,
rule selection `E F I N W UP`. Some long-line scripts under
`src/opensquilla/skills/bundled/*/scripts/` and a vendored `video-merger/src/`
have intentional `E501` ignores — leave those alone. `mypy` is strict
(`warn_return_any = true`); many third-party modules are in
`[[tool.mypy.overrides]]` with `ignore_missing_imports = true`.

**Tests.** Pytest with `asyncio_mode = "auto"`. The tests tree lives at the
repo root; `tests/_private`, `tests/fixtures`, `.omx`, `.codex`, `.claude` are
excluded. Use the `llm_*`, `live_channel`, `live_search`, `webui_browser`,
`tui_real_terminal`, and `local_golden` markers to gate anything that touches
the network, the browser, a real terminal, or a slow synthetic golden task.

**Dependencies.** Required dependencies and optional extras (`mcp`, `msg`,
`memory`, `recommended`, `matrix`, `matrix-e2e`, `document-extras`, `swebench`)
are declared in `pyproject.toml`. The default install uses the `recommended`
extra (SquillaRouter + memory + local models). `OPENSQUILLA_INSTALL_PROFILE=core`
omits the router deps for a minimal install.

**Migrations.** SQL files under `migrations/` are mirrored into the wheel at
`opensquilla/_migrations/` via `[tool.hatch.build.targets.wheel.force-include]`
and run by `yoyo-migrations` on gateway startup. Do not hand-edit migrations
that have already shipped — add a new file.

**Skills.** Bundled user-facing skills live under
`src/opensquilla/skills/bundled/`. `src/opensquilla/skills/exp/` is excluded
from the wheel. New meta-skills follow
[`docs/authoring/meta-skills.md`](docs/authoring/meta-skills.md).

**Channels.** Adding a new channel adapter means implementing the adapter
contract under `src/opensquilla/channels/` and registering it in
`opensquilla channels types`. Webhook-mode channels (Slack webhook, WeCom)
need a publicly reachable gateway URL.

**Docs.** Documentation lives under `docs/`. The docs site is markdown-only;
rendered previews go through GitHub. See
[`docs/contributing-docs.md`](docs/contributing-docs.md) for the doc-only
checklist. Independent features stay on independent pages under
`docs/features/`. Read the diagrams index at
[`docs/diagrams/architecture.md`](docs/diagrams/architecture.md) before adding
or editing any `architecture.puml` / `architecture.drawio` source.

**Logging.** `structlog` is the standard logger. Use bound context
(`log.bind(...)`) for per-turn / per-session fields; avoid print-style
formatting.

**Safety.** Public gateway bind (`--listen 0.0.0.0`) is opt-in and requires
explicit token auth. Provider keys, channel secrets, and MCP-client config
must never appear in checked-in examples or fixtures. Redaction happens in
`src/opensquilla/safety/` and `src/opensquilla/redaction.py`.

## When in doubt

- Read the linked docs first.
- For runtime behavior, prefer `opensquilla doctor` and `opensquilla diagnostics on`
  before diving into source.
- Open an issue using the appropriate template (`.github/ISSUE_TEMPLATE/`) before
  a large change.
- For agent-specific tasks (Claude Code, Codex), follow this file plus the
  module guide that owns the area you are touching.