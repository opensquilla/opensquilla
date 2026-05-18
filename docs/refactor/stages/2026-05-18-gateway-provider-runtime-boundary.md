# Gateway Provider Runtime Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize Gateway provider runtime selector materialization behind `gateway/provider_runtime_sync.py` while preserving provider boot, config RPC, onboarding RPC, and public provider defaults.

**Architecture:** `gateway/provider_runtime_sync.py` becomes the Gateway module that knows how to turn effective LLM runtime config into provider selector/config objects. `gateway/boot.py`, `gateway/rpc_config.py`, and `gateway/rpc_onboarding.py` delegate to that boundary instead of constructing `ProviderConfig` directly. Public CLI/RPC method names, payloads, provider defaults, env-key resolution, and OpenRouter routing behavior remain unchanged.

**Tech Stack:** Python, Gateway boot/config/onboarding modules, Provider selector/config boundary, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-provider-runtime-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-provider-runtime-boundary`
- Child worktree: `../opensquilla-refactor-gateway-provider-runtime-boundary`
- Owner: Codex main thread. `spawn_agent` was retested for a Provider module probe and still returned `agent thread limit reached`; this stage proceeds sequentially with the fallback recorded here.

## Goal

Move Gateway provider selector construction and sync materialization into the existing provider runtime boundary so boot/config/onboarding code no longer duplicates `ProviderConfig` assembly.

## Current-State Audit

- Current HEAD: `827c41d` (`Record gateway RPC domain boundary merge`).
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/llm_runtime.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `src/opensquilla/gateway/rpc_config.py`
  - `src/opensquilla/gateway/rpc_onboarding.py`
  - `src/opensquilla/provider/config.py`
  - `src/opensquilla/provider/selector.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_gateway/test_rpc_onboarding.py`
- Symbols or command surfaces inspected:
  - Serena `get_symbols_overview` for provider selector, factory, registry, runtime status, CLI provider workflows, and gateway provider runtime sync.
  - Serena `find_symbol` for `ModelSelector` and Gateway provider sync functions.
  - Provider sync surfaces: `resolve_llm_runtime_config`, `sync_provider_selector`, `_sync_provider_selector`, `ModelSelector`, `ProviderConfig`, `SelectorConfig`.
- Tests inspected:
  - Gateway provider env/runtime sync tests.
  - RPC onboarding provider configure tests.
  - Provider factory/selector tests.
- Existing boundary pattern this stage follows:
  - `gateway/provider_runtime_sync.py` already owns `sync_provider_selector` for config RPCs.
  - `gateway/llm_runtime.py` already owns effective LLM runtime/env/default resolution.
  - Prior gateway RPC domain slices use AST tests to enforce module ownership without changing wire behavior.

## Boundary Decision

- Responsibilities moving out:
  - `gateway/boot.py` direct `ModelSelector`/`SelectorConfig`/`ProviderConfig` construction.
  - `gateway/rpc_onboarding.py` duplicated provider selector sync and direct `ProviderConfig` construction.
- Responsibilities staying in place:
  - Effective LLM runtime/env/default resolution stays in `gateway/llm_runtime.py`.
  - Provider selector behavior stays in `provider/selector.py`.
  - Config mutation semantics stay in `gateway/rpc_config.py` and `gateway/rpc_onboarding.py`.
  - Provider registry, model listing, and provider backend classes remain unchanged.
- New module/file responsibility:
  - `gateway/provider_runtime_sync.py` owns Gateway-facing provider selector materialization and sync.
- Public behavior that must not change:
  - Boot still creates a selector only when an effective API key exists.
  - Boot keeps the existing base URL normalization used before provider selector/model catalog startup.
  - Config RPC and onboarding RPC still sync env-resolved API keys and base URLs to the running selector without persisting runtime-only secrets.
  - Public RPC payloads and provider defaults stay stable.
- Files explicitly out of scope:
  - Provider backend implementations.
  - Provider registry/catalog defaults.
  - CLI provider command text.
  - Web UI JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_syncs_env_key_to_provider_selector -q`
- Expected red failure:
  - `build_provider_selector_from_runtime` does not exist in `gateway/provider_runtime_sync.py`.
  - `gateway/boot.py` still directly imports and constructs provider selector/config classes.
  - `gateway/rpc_onboarding.py` still owns duplicated runtime sync logic and accepts only an LLM config object.
- Minimal implementation:
  - Add `build_provider_selector_from_runtime` to `gateway/provider_runtime_sync.py`.
  - Reuse that boundary from `gateway/boot.py`.
  - Make `gateway/rpc_onboarding.py` delegate provider selector sync to `gateway/provider_runtime_sync.sync_provider_selector`.
  - Preserve existing base URL and runtime secret semantics.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_syncs_env_key_to_provider_selector tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_calls_provider_selector_sync tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_does_not_persist_runtime_api_key -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/provider_runtime_sync.py src/opensquilla/gateway/rpc_onboarding.py tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `git diff --check`

## Files

- Create:
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `docs/refactor/stages/2026-05-18-gateway-provider-runtime-boundary.md`
- Modify:
  - `src/opensquilla/gateway/boot.py`
  - `src/opensquilla/gateway/provider_runtime_sync.py`
  - `src/opensquilla/gateway/rpc_onboarding.py`
- Test:
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_boot_provider_env.py`
  - `tests/test_gateway/test_rpc_onboarding.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-provider-runtime-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-provider-runtime-boundary`.
- [x] Write the failing Gateway provider runtime boundary tests.
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

- Revert the integration merge commit if provider boot, config RPC, onboarding RPC, or runtime-secret behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit: `eb7df2f`
- Integration merge: `aab5643`
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-provider-runtime-boundary` passed on branch `codex/refactor-gateway-provider-runtime-boundary` at `827c41d`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_syncs_env_key_to_provider_selector -q` failed as expected with an import error because `build_provider_selector_from_runtime` did not exist in `gateway/provider_runtime_sync.py`.
  - Minimal green: `uv run --extra dev pytest tests/test_gateway/test_provider_runtime_sync_boundary.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_syncs_env_key_to_provider_selector tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_calls_provider_selector_sync tests/test_gateway/test_rpc_onboarding.py::test_provider_configure_does_not_persist_runtime_api_key -q` passed, `14 passed in 0.52s`.
  - Focused onboarding/provider group: `uv run --extra dev pytest tests/test_gateway/test_rpc_onboarding.py tests/test_gateway/test_boot_provider_env.py tests/test_gateway/test_provider_runtime_sync_boundary.py -q` passed, `39 passed in 1.48s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/boot.py src/opensquilla/gateway/provider_runtime_sync.py src/opensquilla/gateway/rpc_onboarding.py tests/test_gateway/test_provider_runtime_sync_boundary.py` passed after ruff normalized the new test import block.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 490 source files; whitespace passed; pytest passed with `2411 passed, 8 skipped, 2 warnings in 53.01s`; gateway smoke start/status/stop passed on `127.0.0.1:62762`.
  - Integration preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-architecture` passed on branch `codex/refactor-architecture` at `827c41d`.
  - Integration merge: `git merge --no-ff codex/refactor-gateway-provider-runtime-boundary` produced merge commit `aab5643`.
  - Integration gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 490 source files; whitespace passed; pytest passed with `2413 passed, 6 skipped, 2 warnings in 27.02s`; gateway smoke start/status/stop passed on `127.0.0.1:62928`.
- Residual risk:
  - Low. This slice moves provider selector materialization to an existing Gateway boundary; effective runtime resolution, provider selector behavior, provider backends, RPC method names, and persisted config semantics remain unchanged and are covered by focused onboarding/boot tests plus the full gate.
- Next recommended slice:
  - Continue with a larger Gateway sessions task-runtime consolidation or Provider factory/config facade cleanup, keeping the same module-level ownership style rather than helper-by-helper extraction.
