# Provider Runtime Config Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move provider credential/runtime config resolution from the gateway layer into the provider layer while preserving gateway compatibility imports and runtime behavior.

**Architecture:** Add `opensquilla.provider.runtime_config` as the owner for `LlmRuntimeConfig`, provider-specific env/base-url resolution, and OpenRouter default provider routing. Keep `opensquilla.gateway.llm_runtime` as a compatibility facade, and update gateway runtime assembly/sync boundaries to consume the provider-owned module directly.

**Tech Stack:** Python, GatewayConfig, provider registry metadata, provider selector/runtime assembly, pytest AST boundary tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: provider-runtime-config-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-runtime-composition-boundary`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread. `spawn_agent` was re-verified for this stage and still fails with `collab spawn failed: agent thread limit reached`, so this larger slice uses the documented sequential fallback with one fixed active child worktree.

## Goal

Separate provider runtime config resolution from gateway boot/sync code without changing provider env precedence, provider-specific base URL env handling, OpenRouter default provider routing, runtime secret marking, selector sync behavior, image-generation sync behavior, or gateway smoke behavior.

## Current-State Audit

- Current HEAD: `7a08230`.
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-tools-execution-surface-boundary.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/llm_runtime.py`
  - `src/opensquilla/gateway/provider_bootstrap.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `src/opensquilla/gateway/rpc_config.py`
  - `src/opensquilla/gateway/rpc_onboarding.py`
  - `src/opensquilla/gateway/rpc_onboarding_providers.py`
  - `src/opensquilla/provider/__init__.py`
  - `src/opensquilla/provider/registry.py`
  - `src/opensquilla/provider/selector.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_provider_factory.py`
  - `tests/test_provider_runtime_status.py`
- Symbols or command surfaces inspected:
  - `LlmRuntimeConfig`
  - `OPENROUTER_DEFAULT_PROVIDER_ROUTING`
  - `provider_base_url_env_name`
  - `resolve_llm_runtime_config`
  - `build_provider_runtime_services`
  - `sync_provider_selector`
  - `build_provider_selector_from_runtime`
  - `GatewayConfig`
- Tests inspected:
  - Provider runtime assembly boundary tests.
  - Provider runtime sync boundary tests.
  - Gateway provider env tests.
  - Provider factory/status tests.
  - Onboarding runtime config references.
- Existing boundary pattern this stage follows:
  - `gateway.provider_runtime_assembly` owns gateway startup composition.
  - `gateway.provider_runtime_sync` owns gateway RPC selector/image runtime synchronization.
  - `provider.runtime_status`, `provider.model_listing`, and `provider.model_catalog` already own provider-facing payload/report behavior.

## Boundary Decision

- Responsibilities moving out:
  - Runtime LLM config dataclass.
  - Provider-specific API key/base URL env resolution.
  - OpenRouter default provider routing merge.
  - Runtime secret path marking for effective API keys.
- Responsibilities staying in place:
  - Gateway boot still calls `build_provider_runtime_services`.
  - Gateway config/onboarding RPCs still call `sync_provider_selector` and `sync_image_generation`.
  - `gateway.llm_runtime` remains import-compatible for existing callers and tests.
  - Provider selector creation and image-generation sync stay in the gateway runtime sync/assembly layer for now.
- New module/file responsibility:
  - `src/opensquilla/provider/runtime_config.py` owns provider runtime config resolution.
- Public behavior that must not change:
  - `from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config` keeps working.
  - Direct provider env keys still override empty config values.
  - Explicit config API keys still win before standard env keys.
  - Direct providers do not inherit OpenRouter provider routing defaults.
  - OpenRouter default provider routing still merges configured overrides.
  - Runtime env API keys remain excluded from persisted TOML.
- Files explicitly out of scope:
  - Provider adapter implementation internals.
  - Provider status/model-listing payload ownership.
  - Web UI provider views.
  - Gateway service container wiring beyond updated imports.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_provider_runtime_config_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.provider.runtime_config'`.
  - `gateway/llm_runtime.py` still owns the runtime config dataclass/functions.
- Minimal implementation:
  - Create `opensquilla.provider.runtime_config`.
  - Move the runtime config dataclass and resolver helpers into it.
  - Replace `opensquilla.gateway.llm_runtime` with a compatibility facade.
  - Update `gateway.provider_runtime_assembly` and `gateway.provider_runtime_sync` to import from `opensquilla.provider.runtime_config`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_provider_runtime_config_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_router_boot.py tests/test_onboarding/test_config_store.py tests/test_onboarding/test_mutations.py tests/test_onboarding/test_status.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/provider/runtime_config.py src/opensquilla/gateway/llm_runtime.py src/opensquilla/gateway/provider_runtime_assembly.py src/opensquilla/gateway/provider_runtime_sync.py tests/test_provider_runtime_config_boundary.py`
  - `uv run --extra dev mypy src/opensquilla/provider src/opensquilla/gateway/llm_runtime.py src/opensquilla/gateway/provider_runtime_assembly.py src/opensquilla/gateway/provider_runtime_sync.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/provider/runtime_config.py`
  - `tests/test_provider_runtime_config_boundary.py`
  - `docs/refactor/stages/2026-05-18-provider-runtime-config-boundary.md`
- Modify:
  - `src/opensquilla/gateway/llm_runtime.py`
  - `src/opensquilla/gateway/provider_runtime_assembly.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
- Test:
  - `tests/test_provider_runtime_config_boundary.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_gateway/test_provider_runtime_assembly_boundary.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_router_boot.py`
  - `tests/test_onboarding/test_config_store.py`
  - `tests/test_onboarding/test_mutations.py`
  - `tests/test_onboarding/test_status.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-provider-runtime-config-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-provider-runtime-composition-boundary`.
- [x] Write the failing provider runtime config boundary tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the behavior-compatible provider runtime config boundary.
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

- Revert the integration merge commit if runtime provider env precedence, provider routing, runtime secret marking, selector sync, provider runtime assembly, or gateway smoke behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `3c525cfb31433192c24b5aa4df385ca7087b2665` (`3c525cf`, `Extract provider runtime config boundary`).
- Integration merge: `9cf825bb4d27085dcc63791db96b7c50e1df1de5` (`9cf825b`, `Merge provider runtime config boundary`).
- Verification evidence:
- Red: `uv run --extra dev pytest tests/test_provider_runtime_config_boundary.py -q` failed during collection with `ModuleNotFoundError: No module named 'opensquilla.provider.runtime_config'`.
- Focused green: `uv run --extra dev pytest tests/test_provider_runtime_config_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_provider_runtime_assembly_boundary.py tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_router_boot.py tests/test_onboarding/test_config_store.py tests/test_onboarding/test_mutations.py tests/test_onboarding/test_status.py -q` passed with `103 passed in 1.61s`.
- Touched ruff: `uv run --extra dev ruff check src/opensquilla/provider/runtime_config.py src/opensquilla/gateway/llm_runtime.py src/opensquilla/gateway/provider_runtime_assembly.py src/opensquilla/gateway/provider_runtime_sync.py tests/test_provider_runtime_config_boundary.py` passed.
- Touched mypy: `uv run --extra dev mypy src/opensquilla/provider src/opensquilla/gateway/llm_runtime.py src/opensquilla/gateway/provider_runtime_assembly.py src/opensquilla/gateway/provider_runtime_sync.py --show-error-codes` passed with no issues in 26 source files.
- Whitespace: `git diff --check` passed.
- Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 511 source files; whitespace passed; pytest passed with `2459 passed, 8 skipped, 2 warnings in 48.86s`; gateway smoke start/status/stop passed on port `55073`.
- Integration preflight: `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` passed at `9cf825b`.
- Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 511 source files; whitespace passed; pytest passed with `2461 passed, 6 skipped, 2 warnings in 26.59s`; gateway smoke start/status/stop passed on port `55214`.
- Directory hygiene target: remove `../opensquilla-refactor-active` after this record commit, then run `git worktree prune` and verify no extra `opensquilla-refactor-*` worktrees remain beyond integration.
- Residual risk: gateway compatibility imports from `opensquilla.gateway.llm_runtime` are intentionally preserved until all older callers can be audited; future provider slices should avoid deleting the facade without a public import sweep.
- Next recommended slice: move provider selector/materialization ownership into the provider layer while keeping gateway runtime sync as the RPC-facing composition boundary.
