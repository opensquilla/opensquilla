# Global Component/Plugin Decoupling Audit

> **For agentic workers:** This is an Ultragoal G001 audit artifact. It intentionally stops before implementation. Later code-changing batches must use `superpowers:using-git-worktrees`, `superpowers:writing-plans`, `superpowers:test-driven-development`, `superpowers:dispatching-parallel-agents` when split into lanes, and `superpowers:verification-before-completion` before completion claims.

## Stage

- Name: `global-component-plugin-decoupling-audit`
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: none; audit/documentation-only stage on integration branch
- Child worktree: none; execution batches will use `../opensquilla-refactor-active` or fixed external worker slots
- Owner: main Codex leader
- Ultragoal story: `G001-global-component-plugin-decoupling-audit`

## Goal

Classify every major OpenSquilla architecture family after the first broad refactor pass, identify where component/plugin decoupling still has leverage, select the first two coarse execution batches, and define ownership/test/parity strategy before source edits resume.

This audit deliberately favors larger module-family batches over helper-sized follow-ups. Same-class coupling problems are grouped into one stage plan and one comprehensive verification pass per batch.

## Current-state audit

- Current HEAD: `a746c48` on `codex/refactor-architecture`.
- `main` reference observed by the PRD: `94d9466`.
- Worktree status at audit start: `docs/refactor/overall-plan.md` modified; this is the expected durable cadence update adding coarser-stage constraints.
- AGENTS.md files in scope for this audit: `AGENTS.md`, `docs/AGENTS.md`; future source/test batches also inherit `src/AGENTS.md` and `tests/AGENTS.md`.
- Preflight evidence: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture --allow-dirty` exited `0`, reported branch `codex/refactor-architecture`, head `a746c48`, and the expected dirty `docs/refactor/overall-plan.md`.
- Broad repo evidence:
  - Source-family file counts include CLI 169, Gateway 192, Session 31, Provider 39, Router 43, Channels 44, Tools 58, MCP 10, Sandbox 28, Skills 106, Memory 45, Search 14, Scheduler 32, Agents 12, Contracts 12, Application 7, Web UI static 55.
  - Test-family signals include `tests/test_cli`, `tests/test_gateway`, `tests/test_session`, `tests/test_channels`, `tests/test_tools`, `tests/test_mcp`, `tests/test_sandbox`, `tests/test_security`, `tests/test_search`, `tests/test_scheduler`, `tests/test_agents`, `tests/test_contracts`, `tests/test_application`, plus top-level provider/memory/skills/router tests.
  - `git diff --name-only main..HEAD` reports 711 changed paths and 593 source/test changed paths across the refactor line; use targeted parity tests rather than diff inspection alone.
- Prior stage evidence inspected:
  - `docs/refactor/stages/2026-05-19-knowledge-services-rpc-cli-boundary-batch.md`
  - `docs/refactor/stages/2026-05-19-search-skills-runtime-boundary-batch.md`
  - `docs/refactor/stages/2026-05-19-channel-runtime-dispatch-boundary-batch.md`
  - `docs/refactor/stages/2026-05-19-channels-delivery-boundary.md`
  - `docs/refactor/stages/2026-05-19-provider-runtime-model-contract-batch.md`
  - `docs/refactor/stages/2026-05-19-provider-status-catalog-batch.md`
  - `docs/refactor/stages/2026-05-19-model-router-runtime-scoring-batch.md`
  - `docs/refactor/stages/2026-05-19-route-envelope-contract-batch.md`
  - `docs/refactor/stages/2026-05-19-tools-sandbox-security-execution-boundary-batch.md`
  - `docs/refactor/stages/2026-05-19-webui-rpc-view-state-contract-batch.md`
  - `docs/refactor/stages/2026-05-19-gateway-app-server-wiring-boundary.md`
  - `docs/refactor/stages/2026-05-19-task-runtime-lifecycle-boundary-batch.md`
- Existing boundary patterns this audit follows: `*_workflows.py`, `*_presenters.py`, `*_gateway_queries.py`, `*_config_mutations.py`, `*_rpc_payload.py`, `runtime/*` neutral contracts, and compatibility facades that preserve legacy public imports.

## Superpowers evidence

- `superpowers:using-superpowers`:
  - Evidence: skill was read at G001 start; this document records matching skills before audit completion.
- `superpowers:using-git-worktrees`:
  - Evidence: current worktree inventory was inspected. G001 is docs-only and does not create a child worktree. First code-changing batch will use `../opensquilla-refactor-active` or fixed external slots per repo instructions.
- `superpowers:writing-plans`:
  - Evidence: this audit is the plan artifact for subsequent implementation. It maps families, classifications, first two batches, worker ownership, public contracts, and focused commands.
- `superpowers:test-driven-development`:
  - Evidence: no production code changes in G001. TDD is deferred to code-changing G002/G003 lanes and required there with batch-level RED/GREEN tests before implementation.
- `superpowers:dispatching-parallel-agents`:
  - Evidence: three read-only same-thread audit lanes were dispatched for extension services, channels/external ingress, and provider/router/contracts. They were scoped as no-edit explorer lanes with concrete output requirements. If they remain timed out, this audit records leader fallback and execution batches must re-check same-thread health before code changes.
- `superpowers:verification-before-completion`:
  - Evidence: planned G001 verification uses fresh `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture --allow-dirty`, `git diff --check`, and a stage-document sanity check before checkpointing Ultragoal G001.

## Serena evidence

- Serena `initial_instructions` was read and the repository root was activated.
- Serena project memories read:
  - `refactor/multi_branch_parallel_refactor_preference`
  - `refactor/serena_usage_preference`
  - `refactor/substage_superpowers_evidence_requirement`
  - `refactor/superpowers_parallel_refactor_2026-05-19`
  - `refactor/superpowers_per_large_substage_project_requirement`
- Serena symbol/search evidence:
  - `src/opensquilla/application/turn.py` exposes application ports: `PromptAssemblerPort`, `ToolSurfaceBuilderPort`, `HistoryServicePort`, `MemoryOrchestratorPort`, `ProviderExecutorPort`, and `TurnUseCase`.
  - `src/opensquilla/contracts/__init__.py` is mostly re-export-only, while direct contract consumers are still sparse: `src/opensquilla/application/turn.py`, attachment constants in Gateway/Channels, and import-boundary tests.
  - `src/opensquilla/provider/registry.py` exposes provider specs/list/get functions; provider catalog/status/listing have dedicated prior stage tests.
  - `src/opensquilla/channels/manager.py` still owns lifecycle and dispatch coordination through `ChannelManager`, though dispatch/delivery have been split.
  - `src/opensquilla/skills/runtime.py`, `memory/runtime.py`, `search/runtime.py`, and `scheduler/engine.py` show separate runtimes, but the extension-service family still spans Gateway RPC, CLI, tools, static views, and scheduler/session lifecycle edges.

## Audit table

| Family | Main paths | Current boundary signal | Classification | Coupling class | Parity risk | Recommended action | Priority | Proposed batch grouping |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLI | `src/opensquilla/cli`, `tests/test_cli` | Many command families already split into workflows/presenters/gateway queries; 169 CLI files show heavy but patterned decomposition. | `backlog` | public contract leakage around command text/flags and residual command-family orchestration | Medium: CLI flags, text, JSON output | Do not reopen as first batch; audit residual command families only after higher-leverage plugin/component boundaries settle. | P4 | CLI command-family cleanup backlog, grouped by command family not helper. |
| Gateway/RPC/WebSocket | `src/opensquilla/gateway`, `tests/test_gateway` | Large prior stages split app/server, runtime wiring, channel manager wiring, WebSocket core, RPC payloads, and task runtime. | `backlog` | runtime lifecycle coupling and public RPC payload leakage | High where touched: RPC names/scopes, WS events, gateway smoke | Avoid broad Gateway rewrites now. Only touch Gateway files as adapter edges owned by selected batches. | P4 | Gateway adapter edges inside extension/channel/provider batches; standalone boot diagnostics later. |
| Session/runtime | `src/opensquilla/session`, gateway task runtime, `tests/test_session` | Lifecycle, persistence, flush, compaction, runtime facade, terminalization stages exist; residual facade helpers remain. | `backlog` | runtime lifecycle and persistence/state coupling | High: terminal state, cancellation, memory preservation | Keep session as supporting test surface for extension memory and route/contract batches; defer standalone runtime cleanup. | P5 | Session queue/running-state cleanup later, not first two batches. |
| Provider/router | `src/opensquilla/provider`, `src/opensquilla/squilla_router`, provider/router tests | Provider status/catalog/model contracts and router scoring have recent batch evidence; router/provider integration remains strategically important. | `boundary-refinement-needed` | registry/factory/plugin discovery plus routing/pricing state coupling | High: provider defaults, pricing, attribution, route class | Make this third execution batch after extension and channels, unless G002/G003 uncover provider regressions. | P3 | Provider/router integration batch (`G004`). |
| Channels | `src/opensquilla/channels`, gateway channel ingress/dispatch, `tests/test_channels` | Dispatch and delivery were split; prior docs say Channels should rest unless integration gates find regressions. Still fewer recent stages and high external-ingress value. | `boundary-refinement-needed` | transport/adapter config, dispatch/reply contract, external ingress coupling | High: inbound dedupe, replies, webhook/websocket protocols | Select as second execution batch to finish external ingress seams as one coarse stage, not tiny channel helpers. | P2 | Channels + external ingress batch (`G003`). |
| Tools/MCP/Sandbox/Security | `src/opensquilla/tools`, `mcp`, `sandbox`, related tests | Recent tools/sandbox/security batch completed service/policy/execution/web fetch boundaries; residual risk noted but not first priority. | `sufficient-skip` | security/policy coupling | Very high if touched; default policy and approvals | Skip for first two batches. Only reopen if extension/channel/provider work exposes a tool policy regression. | P6 | Security hardening backlog, evidence-gated only. |
| Skills/plugins/memory/search/scheduler | `src/opensquilla/skills`, `memory`, `search`, `scheduler`, related tests | Prior search/skills and knowledge-services batches exist, but this remains the user's central component/plugin decoupling target and spans runtime/hub/source/update/memory/search/schedule edges. | `boundary-refinement-needed` | registry/factory/plugin discovery, persistence/state coupling, runtime integration coupling | High: skill namespace/provenance, memory source/flush, scheduler delivery, search provider fallback | Select as first execution batch. Group skills/plugins + memory + search + scheduler into one extension-services boundary batch with four worker lanes. | P1 | Extension services boundary batch (`G002`). |
| Agents/contracts/application | `src/opensquilla/agents`, `contracts`, `application`, tests | `application.turn` uses explicit ports, but contracts are not yet broadly adopted; `contracts` ports look partly decorative outside attachment constants and import tests. | `boundary-refinement-needed` | application port/backplane adoption coupling | Medium-high: public imports, turn execution contract | Make this a later adoption/backplane batch after extension/channel/provider edges produce concrete ports to adopt. | P4 | Contracts adoption/backplane batch (`G005`). |
| Web UI | `src/opensquilla/gateway/static`, templates, static/browser tests | Static RPC/view-state and browser runtime contract stages exist; no UI redesign allowed. Browser E2E evidence exists. | `sufficient-skip` | UI/static contract coupling | Medium: load order, visible workflows | Skip implementation unless selected backend batches touch Web UI payloads; then add focused static tests only. | P6 | Static compatibility checks inside backend batches; final docs later. |
| Release/docs/scripts | `docs`, `scripts`, `.github`, release tests | Docs/stage/gate scripts are mature enough for ongoing refactor; final docs must wait for implementation evidence. | `backlog` | release/docs hygiene coupling | Medium: release gate, wheel, PR docs | Defer to final story after implementation evidence, ai-slop-cleaner, review, and full gate. | P6 | Release/docs final quality gate (`G006`). |

## First two execution batches

### Batch 1: Extension services boundary batch (`G002`)

**Rationale:** This is the highest-leverage user-facing target for component/plugin decoupling. It groups the same class of problems—extension discovery/runtime/update plus knowledge-service persistence and search/scheduler integration—into one large coherent stage instead of repeating micro-plans across skills, memory, search, and scheduler.

**Owned modules/files:**

- Skills lane: `src/opensquilla/skills/**`, `src/opensquilla/skills/hub/**`, `src/opensquilla/cli/skills*.py`, `src/opensquilla/gateway/rpc_skills.py`, `src/opensquilla/gateway/static/js/views/skills.js`, `src/opensquilla/gateway/static/css/views/skills.css`, related skills tests.
- Memory lane: `src/opensquilla/memory/**`, `src/opensquilla/gateway/rpc_memory.py`, `src/opensquilla/gateway/rpc_onboarding_memory.py`, `src/opensquilla/cli/memory_flush_cmd.py`, `src/opensquilla/tools/builtin/memory_tools.py`, memory/session/tool tests.
- Search lane: `src/opensquilla/search/**`, `src/opensquilla/search/providers/**`, `src/opensquilla/cli/search*.py`, `src/opensquilla/gateway/rpc_search.py`, `src/opensquilla/gateway/rpc_onboarding_search.py`, `src/opensquilla/tools/builtin/web.py` only for search compatibility, search/onboarding tests.
- Scheduler lane: `src/opensquilla/scheduler/**`, `src/opensquilla/gateway/rpc_cron.py`, `src/opensquilla/cli/cron_cmd.py`, `src/opensquilla/gateway/static/js/views/cron.js`, `src/opensquilla/gateway/static/css/views/cron.css`, scheduler/cron static tests.

**Forbidden/shared files:**

- Do not edit provider/router, channels, broad gateway boot/runtime, Web UI unrelated views, or tool policy/security files unless a focused RED test proves the need and the leader reassigns ownership.
- Shared Gateway static load-order/template files remain leader-owned.
- Session lifecycle files are test surfaces only unless memory preservation fails and leader widens scope.

**Worker split:** four lanes: skills-runtime-hub, memory-source-flush, search-runtime-cli, scheduler-cron.

**Public contracts at risk:** `skills.*`, `memory.*`, `search.*`, `cron.*` RPC names/scopes; CLI output; skill namespace/provenance; hub install/update/deps behavior; bundled skill assets; memory source/flush behavior; scheduler route inference/current-session binding/subscriptions/run history; Brave/DuckDuckGo fallback/diagnostics/proxy behavior; static skills/cron view payload assumptions.

**Focused tests:**

```bash
uv run --extra dev pytest tests/test_skills_*.py tests/test_skill_*.py tests/test_gateway_static_skills_view.py -q
uv run --extra dev pytest tests/test_memory_*.py tests/test_tools/test_memory_profile_guidance.py tests/test_session/test_session_lifecycle_memory.py tests/test_gateway/test_rpc_config_memory_embedding.py tests/test_gateway/test_config_memory_defaults.py -q
uv run --extra dev pytest tests/test_search tests/test_cli/test_search_cmd.py tests/test_onboarding/test_search_specs.py tests/test_skill_multi_search_engine.py -q
uv run --extra dev pytest tests/test_scheduler tests/test_gateway/test_rpc_cron_current_session.py tests/test_gateway/test_cron_view_static.py -q
scripts/refactor_gate.sh
```

**Main parity strategy:** before editing, inspect `main` public behavior for the exact RPC/CLI/static surfaces each lane touches and add tests for externally observable behavior, not internal helper names.

### Batch 2: Channels and external ingress batch (`G003`)

**Rationale:** Channels are external plugin-like ingress/egress components and remain a natural second coarse batch. Recent dispatch/delivery work lowered risk, so this batch should focus on adapter config, ingress normalization, transport protocols, dispatch/reply contracts, and channel-facing Gateway edges as one stage.

**Owned modules/files:**

- Adapter/config lane: `src/opensquilla/channels/entries.py`, `registry.py`, `types.py`, adapter modules (`slack.py`, `telegram.py`, `discord.py`, `feishu.py`, `dingtalk.py`, `wecom.py`, `matrix.py`, `msteams.py`, `qq.py`), `tests/test_channels/test_channel_gateway_boundary.py`, channel specs tests.
- Transport/ingress lane: `src/opensquilla/channels/transports.py`, `ingress.py`, `websocket.py`, `debounce.py`, webhook/websocket gateway touchpoints, transport tests.
- Dispatch/reply lane: `src/opensquilla/channels/manager.py`, `delivery.py`, `status_report.py`, `stream_policy.py`, gateway channel dispatch/inflight/channel ingress files only in channel-specific sections, dispatch/reply tests.
- Artifact/attachment lane if required: `src/opensquilla/channels/_attachment_io.py`, `_util.py`, contract attachment constants, focused attachment tests.

**Forbidden/shared files:**

- Provider/router, skills/memory/search/scheduler, broad session runtime, and Web UI redesign are out of scope.
- Shared Gateway `app.py`, boot wiring, and static templates are leader-owned unless the stage explicitly assigns a channel-specific adapter.

**Worker split:** three lanes by default: adapter-config, transport-ingress, dispatch-reply. Add attachment lane only if a RED parity test shows it is coupled to channel delivery.

**Public contracts at risk:** adapter config fields, webhook/websocket request/response shapes, dedupe behavior, session key contracts, outbound reply reasons, threaded Slack delivery, channel RPC status/logout/restart payloads, artifact/file metadata.

**Focused tests:**

```bash
uv run --extra dev pytest tests/test_channels -q
uv run --extra dev pytest tests/test_gateway/test_channel_* tests/test_gateway/test_rpc_channels.py -q
uv run --extra dev pytest tests/test_onboarding/test_channel_specs.py tests/functional/test_live_channel_telegram_smoke.py -q
scripts/refactor_gate.sh
```

**Main parity strategy:** lock observable channel reply/status/ingress behavior before refactoring internals. Default to offline deterministic tests; live channel smoke remains optional/skipped unless credentials are explicitly available.

## Backlog and skip table

| Backlog item | Why not first two | Re-entry condition | Suggested focused command |
| --- | --- | --- | --- |
| Provider/router integration (`G004`) | Important but less central than extension/channel component boundaries; recent provider/router stages already exist. | G002/G003 complete and no blocking provider regression remains. | `uv run --extra dev pytest tests/test_provider*.py tests/test_model_router*.py tests/test_engine/test_pricing.py -q` |
| Contracts adoption/backplane (`G005`) | Contracts are sparse; better after more concrete provider/channel/extension ports are known. | After G002-G004 define stable seams; then adopt contracts across real consumers. | `uv run --extra dev pytest tests/test_contracts tests/test_application tests/test_runtime_routing_contract.py -q` |
| CLI residual command-family thinning | Many prior splits; lower leverage than plugin/component boundaries. | Only when a selected batch touches the same CLI family. | `uv run --extra dev pytest tests/test_cli -q` |
| Gateway boot/runtime diagnostics | Recent boot/runtime stages; broad Gateway changes carry high public-surface risk. | Only if selected batches uncover adapter-edge duplication or smoke failures. | `uv run --extra dev pytest tests/test_gateway -q` |
| Session runtime queue/running-state cleanup | High concurrency risk; not plugin/component-first. | After extension memory/channel dispatch are stable. | `uv run --extra dev pytest tests/test_session tests/test_gateway/test_task_runtime* -q` |
| Tools/MCP/Sandbox security polish | Recent security batch passed; high risk if reopened. | Only for bug/security regression or final review blocker. | `uv run --extra dev pytest tests/test_tools tests/test_mcp tests/test_sandbox tests/test_security -q` |
| Web UI dynamic/browser coverage | Static/browser runtime stages exist; no UI redesign allowed. | If backend payloads or load order change. | `uv run --extra dev pytest tests/test_gateway/*static* tests/functional/test_webui_browser_chat_e2e.py -q` |
| Release/docs/scripts | Must reflect implemented evidence, not plans. | Final story after all implementation batches. | `scripts/refactor_gate.sh --wheel` when release-ready. |

## Audit stop condition satisfaction

- Classification row exists for every architecture family in the PRD Architecture Map.
- First two execution batches selected: G002 Extension Services, then G003 Channels/External Ingress.
- Each selected batch includes rationale, owned modules/files, forbidden/shared files, worker-lane split, public contracts at risk, focused test commands, and main parity strategy.
- Lower-priority/skipped findings are captured in the backlog table.
- No production source edits are included in G001; implementation must move to G002 instead of expanding this audit indefinitely.

## Verification plan for G001

Run before checkpointing G001:

```bash
scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture --allow-dirty
git diff --check
python - <<'PY'
from pathlib import Path
p = Path('docs/refactor/stages/2026-05-19-global-component-plugin-decoupling-audit.md')
text = p.read_text()
required = [
    '## Superpowers evidence',
    '## Serena evidence',
    '## Audit table',
    '## First two execution batches',
    'Extension services boundary batch',
    'Channels and external ingress batch',
    '## Backlog and skip table',
    '## Audit stop condition satisfaction',
]
missing = [item for item in required if item not in text]
assert not missing, missing
for family in ['CLI', 'Gateway/RPC/WebSocket', 'Session/runtime', 'Provider/router', 'Channels', 'Tools/MCP/Sandbox/Security', 'Skills/plugins/memory/search/scheduler', 'Agents/contracts/application', 'Web UI', 'Release/docs/scripts']:
    assert family in text, family
PY
```

Expected result: all commands exit `0`.
