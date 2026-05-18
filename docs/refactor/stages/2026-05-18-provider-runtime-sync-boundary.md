# Provider Runtime Sync Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move provider/runtime synchronization helpers out of `gateway/rpc_config.py` while preserving config mutation behavior, provider selector sync, runtime-only secret handling, and image-generation runtime sync.

**Architecture:** Add `opensquilla.gateway.provider_runtime_sync` as the focused boundary for runtime-only provider side effects. Keep `rpc_config.py` as the RPC handler and config mutation owner, with compatibility wrappers for existing private helper imports.

**Tech Stack:** Python, Starlette gateway RPC, GatewayConfig, provider selector runtime config, pytest, ruff, mypy.

---

## Stage

- Name: provider-runtime-sync-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-runtime-sync-boundary`
- Child worktree: `../opensquilla-refactor-provider-runtime-sync-boundary`
- Owner: Codex main thread. Parallel worker dispatch was retried after agent thread-limit cleanup, but workers did not produce filesystem changes; this slice is implemented directly from current git and Serena symbol evidence.

## Goal

Extract provider runtime side-effect helpers from `rpc_config.py` into a dedicated gateway boundary without changing config patch/set/apply payloads, persisted TOML redaction behavior, provider selector defaults, OpenRouter provider routing, direct-provider env resolution, or image generation runtime sync.

## Current-State Audit

- Current HEAD: `3f67726`.
- Worktree status: clean before test generation.
- AGENTS.md files in scope: `AGENTS.md`; template-only `src/opensquilla/identity/templates/bootstrap/AGENTS.md` is outside this stage's target files.
- Serena project: `opensquilla-refactor-integration` was activated for symbol-level inspection at the same HEAD before editing the child worktree.
- Symbols inspected with Serena:
  - `_inherit_runtime_secrets`
  - `_clear_runtime_secret_paths`
  - `_sync_provider_selector`
  - `_sync_image_generation`
- Files inspected:
  - `AGENTS.md`
  - `src/opensquilla/gateway/rpc_config.py`
  - `tests/test_gateway/test_boot_provider_env.py`
- Existing behavior tests inspected:
  - `test_runtime_config_sync_resolves_selected_provider_env`
  - `test_config_patch_runtime_env_key_is_not_persisted`
  - OpenRouter provider routing tests in `tests/test_gateway/test_boot_provider_env.py`

## Boundary Decision

- Responsibilities moving out:
  - Runtime-only secret inheritance.
  - Clearing runtime-only secret paths when explicit config paths are updated.
  - Syncing `provider_selector.sync_primary(...)` from the effective runtime config.
  - Syncing image-generation runtime state from config.
- Responsibilities staying in `rpc_config.py`:
  - RPC method registration.
  - Config mutation, merge, validation, redaction restore, persistence, and response payload construction.
  - Compatibility wrappers `_inherit_runtime_secrets`, `_clear_runtime_secret_paths`, `_sync_provider_selector`, and `_sync_image_generation`.
- New module/file responsibility:
  - `src/opensquilla/gateway/provider_runtime_sync.py` owns runtime provider side effects.
- Public behavior that must not change:
  - Config `set`, `patch`, `patchSafe`, and `apply` payload shapes.
  - TOML persistence and runtime secret redaction behavior.
  - Provider selector default model/API/base URL/proxy/provider routing sync.
  - OpenRouter default provider routing and direct provider env resolution.
  - Image generation runtime sync.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_boot_provider_env.py::test_rpc_config_delegates_provider_runtime_sync_to_gateway_boundary -q`
- Expected red failure:
  - Failed because `src/opensquilla/gateway/provider_runtime_sync.py` did not exist.
- Minimal implementation:
  - Create `opensquilla.gateway.provider_runtime_sync`.
  - Move provider runtime helper bodies into the new module.
  - Import boundary helpers in `rpc_config.py`.
  - Keep existing private compatibility wrappers as delegators.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_boot_provider_env.py::test_rpc_config_delegates_provider_runtime_sync_to_gateway_boundary tests/test_gateway/test_boot_provider_env.py::test_runtime_config_sync_resolves_selected_provider_env tests/test_gateway/test_boot_provider_env.py::test_config_patch_runtime_env_key_is_not_persisted -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_config.py src/opensquilla/gateway/provider_runtime_sync.py tests/test_gateway/test_boot_provider_env.py`
  - `uv run --extra dev pytest tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_config_memory_defaults.py tests/test_gateway/test_rpc_config_memory_embedding.py tests/test_gateway/test_config_concurrency.py -q`

## Files

- Create:
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `docs/refactor/stages/2026-05-18-provider-runtime-sync-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc_config.py`
  - `tests/test_gateway/test_boot_provider_env.py`

## Steps

- [x] Inspect current child/integration state, AGENTS.md, and target symbols with Serena.
- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-runtime-sync-boundary`.
- [x] Write the failing provider runtime sync boundary test.
- [x] Run the focused test and confirm expected failure.
- [x] Implement the smallest behavior-compatible change.
- [x] Run focused tests and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [ ] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [ ] Merge child into integration with `git merge --no-ff`.
- [ ] Run `scripts/refactor_gate.sh` in integration.
- [ ] Record child hash, integration hash, verification, and next slice.

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

- Revert the integration merge commit if config mutation or provider runtime behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: pending
- Integration merge:
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-runtime-sync-boundary` passed on branch `codex/refactor-provider-runtime-sync-boundary` at `3f67726`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_boot_provider_env.py::test_rpc_config_delegates_provider_runtime_sync_to_gateway_boundary -q` failed as expected because `provider_runtime_sync.py` did not exist.
  - Focused green: `uv run --extra dev pytest tests/test_gateway/test_boot_provider_env.py::test_rpc_config_delegates_provider_runtime_sync_to_gateway_boundary tests/test_gateway/test_boot_provider_env.py::test_runtime_config_sync_resolves_selected_provider_env tests/test_gateway/test_boot_provider_env.py::test_config_patch_runtime_env_key_is_not_persisted -q` passed, `3 passed in 0.43s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_config.py src/opensquilla/gateway/provider_runtime_sync.py tests/test_gateway/test_boot_provider_env.py` passed.
  - Touched tests: `uv run --extra dev pytest tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_config_memory_defaults.py tests/test_gateway/test_rpc_config_memory_embedding.py tests/test_gateway/test_config_concurrency.py -q` passed, `46 passed in 1.30s`.
  - Boundary test update: first child gate failed in `tests/test_provider_image_generation_runtime_boundary.py::test_gateway_configures_image_generation_runtime_boundary` because the old architecture test expected `rpc_config.py` to directly import `configure_image_generation`. The test was updated so `provider_runtime_sync.py` owns that direct provider-runtime import while `rpc_config.py` imports `sync_image_generation`.
  - Focused architecture retest: `uv run --extra dev pytest tests/test_provider_image_generation_runtime_boundary.py::test_gateway_configures_image_generation_runtime_boundary tests/test_gateway/test_boot_provider_env.py::test_rpc_config_delegates_provider_runtime_sync_to_gateway_boundary -q` passed, `2 passed in 0.44s`.
  - Final child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 485 source files; whitespace passed; pytest passed with `2397 passed, 8 skipped, 2 warnings in 25.28s`; gateway smoke start/status/stop passed on `127.0.0.1:53147`.
- Residual risk:
  - Pending integration merge and integration gate.
- Next recommended slice:
  - Continue Provider/Tools/Channels with concrete child worktree ownership, but prefer main-thread-created worktrees until worker execution is reliable.
