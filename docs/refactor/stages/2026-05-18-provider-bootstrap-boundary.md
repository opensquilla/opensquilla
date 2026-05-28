# Provider Bootstrap Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Gateway provider boot assembly out of `gateway/boot.py` into a Provider bootstrap facade while preserving provider selector startup, model catalog/pricing refresh, image-generation runtime sync, and public RPC/CLI behavior.

**Architecture:** Add `opensquilla.gateway.provider_bootstrap` as the Gateway-facing provider startup boundary. `boot.build_services()` delegates selector/catalog/image-generation startup to the facade and keeps service orchestration, tool registry wiring, session setup, memory, scheduler, search, and MCP startup in place.

**Tech Stack:** Python, Starlette gateway boot, GatewayConfig, provider runtime sync, provider model catalog, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: provider-bootstrap-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-bootstrap-boundary`
- Child worktree: `../opensquilla-refactor-active-provider-bootstrap`
- Owner: Codex main thread. A read-only Provider probe was spawned after stale agent handles were cleaned; main thread owns edits, merge, gate, and cleanup to keep only one active child directory.

## Goal

Extract Provider boot-time runtime startup from the large Gateway boot orchestrator without changing any externally visible provider defaults, config mutation behavior, model listing behavior, image-generation tool visibility, CLI/RPC payloads, or gateway smoke behavior.

## Current-State Audit

- Current HEAD: `e613ace`.
- Worktree status: clean before writing this plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-provider-runtime-sync-boundary.md`
  - `docs/refactor/stages/2026-05-18-gateway-provider-runtime-boundary.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for `gateway/boot.py` and `gateway/provider_runtime_sync.py`.
  - Serena `find_symbol` for `boot.build_services`, `boot.build_flush_service`, `provider_runtime_sync.provider_config_from_runtime`, `provider_runtime_sync.build_provider_selector_from_runtime`, `provider_runtime_sync.sync_provider_selector`, and `provider_runtime_sync.sync_image_generation`.
- Tests inspected:
  - Gateway provider env/runtime sync tests.
  - Provider runtime sync boundary tests.
  - Image-generation runtime boundary tests.
- Existing boundary pattern this stage follows:
  - Provider runtime selector materialization already lives in `gateway/provider_runtime_sync.py`.
  - Prior Gateway slices use AST boundary tests plus focused behavior tests before full child/integration gates.

## Boundary Decision

- Responsibilities moving out:
  - `boot.build_services()` direct provider selector startup.
  - `boot.build_services()` direct model catalog creation and OpenRouter model/pricing refresh.
  - `boot.build_services()` direct image-generation runtime configuration.
- Responsibilities staying in place:
  - Effective LLM runtime/env/default resolution stays in `gateway/llm_runtime.py`.
  - Provider selector/config materialization stays in `gateway/provider_runtime_sync.py`.
  - ServiceContainer shape, gateway service orchestration, session manager boot, tool registry boot, memory/scheduler/search/MCP boot, and flush service wiring stay in `gateway/boot.py`.
  - Provider backend implementations, model catalog internals, and registry defaults stay in `provider/`.
- New module/file responsibility:
  - `src/opensquilla/gateway/provider_bootstrap.py` owns Gateway provider boot assembly and returns a small runtime services bundle to boot.
- Public behavior that must not change:
  - Boot creates a provider selector only when an effective API key exists.
  - Boot normalizes provider base URLs ending in `/v1` before selector/model catalog startup.
  - OpenRouter model catalog and live pricing refresh behavior remains best-effort and non-fatal.
  - Image-generation runtime sync remains best-effort and non-fatal.
  - Public RPC payloads, provider defaults, env-key behavior, CLI text, and WebSocket events remain unchanged.
- Files explicitly out of scope:
  - Provider backend implementations.
  - CLI provider command text.
  - Web UI JavaScript.
  - Session/Channel/Tools behavior unrelated to provider boot.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py::test_provider_runtime_sync_owns_gateway_selector_materialization -q`
- Expected red failure:
  - `test_boot_delegates_provider_runtime_startup_to_provider_bootstrap` fails because `src/opensquilla/gateway/provider_bootstrap.py` does not exist and `boot.build_services()` still directly imports provider startup dependencies.
- Minimal implementation:
  - Create `opensquilla.gateway.provider_bootstrap`.
  - Move provider selector startup, model catalog/pricing refresh, and image-generation runtime sync out of `boot.build_services()`.
  - Keep provider selector config construction delegated to `gateway/provider_runtime_sync.py`.
  - Update boundary tests so `boot.py` delegates provider startup to the new facade.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_provider_image_generation_runtime_boundary.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/provider_bootstrap.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/provider_bootstrap.py`
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
  - `docs/refactor/stages/2026-05-18-provider-bootstrap-boundary.md`
- Modify:
  - `src/opensquilla/gateway/boot.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
- Test:
  - `tests/test_gateway/test_provider_bootstrap_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_provider_image_generation_runtime_boundary.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-provider-bootstrap-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-bootstrap-boundary`.
- [x] Write the failing Provider bootstrap boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible boundary move.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.

## Child Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration Gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if provider boot, model catalog, image generation runtime, or gateway smoke behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `053e04b` (`Extract gateway provider bootstrap boundary`)
- Integration merge: `1e861be` (`Merge provider bootstrap boundary`)
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-bootstrap-boundary` passed on branch `codex/refactor-provider-bootstrap-boundary` at `e613ace`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py::test_provider_runtime_sync_owns_gateway_selector_materialization -q` failed as expected with `3 failed` because `src/opensquilla/gateway/provider_bootstrap.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_provider_image_generation_runtime_boundary.py -q` passed, `18 passed in 0.59s`, after updating the image-generation runtime architecture contract for the new `boot.py -> provider_bootstrap -> provider_runtime_sync` delegation.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/provider_bootstrap.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_provider_image_generation_runtime_boundary.py` passed.
  - Whitespace: `git diff --check` passed.
  - Broader Provider/Gateway boot tests: `uv run --extra dev pytest tests/test_gateway/test_router_boot.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_provider_bootstrap_boundary.py tests/test_provider_image_generation_runtime_boundary.py tests/test_provider_runtime_status.py tests/test_provider_model_catalog.py tests/test_provider_model_listing.py -q` passed, `51 passed in 1.25s`.
  - First child gate caught a mypy issue: `provider_bootstrap.py` passed `str | None` to `ModelCatalog.fetch_openrouter(...)`; fixed by normalizing absent runtime proxy to `""`.
  - Final child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 495 source files; whitespace passed; pytest passed with `2422 passed, 8 skipped, 2 warnings in 50.57s`; gateway smoke start/status/stop passed on `127.0.0.1:61347`.
  - Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `e613ace`.
  - Integration merge: `git merge --no-ff codex/refactor-provider-bootstrap-boundary` produced merge commit `1e861be`.
  - First integration gate caught a release hygiene issue because the stage doc contained a local absolute worktree path; fixed by recording the worktree path as `../opensquilla-refactor-active-provider-bootstrap`.
  - Focused release hygiene retest: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.32s`.
  - Final integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 495 source files; whitespace passed; pytest passed with `2424 passed, 6 skipped, 2 warnings in 28.71s`; gateway smoke start/status/stop passed on `127.0.0.1:61673`.
- Residual risk:
  - Low. The slice moves boot-time provider assembly behind a Gateway facade, while selector materialization, runtime secret sync, provider defaults, catalog/pricing best-effort behavior, and image-generation runtime sync retain focused coverage plus the full gate.
- Next recommended slice:
  - Continue Provider cleanup at module granularity: either move direct onboarding image-generation sync behind `provider_runtime_sync` or consolidate Provider model catalog/runtime-status query facades, using one active child worktree and cleaning it immediately after merge.
