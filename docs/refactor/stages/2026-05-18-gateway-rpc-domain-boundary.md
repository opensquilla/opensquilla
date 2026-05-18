# Gateway RPC Domain Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split provider and search RPC method registration out of the tools RPC module while preserving every public RPC method name, scope, payload, and CLI/Web UI behavior.

**Architecture:** Keep `rpc_tools.py` as the owner of `tools.catalog` and `tools.effective` only. Add `rpc_providers.py` for `providers.status` and `rpc_search.py` for `tools.search_provider`, `search.status`, and `search.query`, then register those modules in `gateway/rpc/__init__.py`.

**Tech Stack:** Python, Gateway RPC dispatcher, provider/search payload boundaries, pytest AST architecture tests, ruff, mypy, full refactor gate.

---

## Stage

- Name: gateway-rpc-domain-boundary
- Date: 2026-05-18
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-gateway-rpc-domain-boundary`
- Child worktree: `../opensquilla-refactor-gateway-rpc-domain-boundary`
- Owner: Codex main thread. A read-only explorer agent was attempted for this slice, but live `spawn_agent` returned `agent thread limit reached`; this stage proceeds sequentially with the fallback recorded here.

## Goal

Move provider and search RPC method registration into domain-specific Gateway RPC modules, leaving the tools RPC module as a tools-only adapter.

## Current-State Audit

- Current HEAD: `2fef810` (`Record Web UI HTTP access boundary merge`).
- Worktree status: clean before writing this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `src/opensquilla/gateway/rpc/__init__.py`
  - `src/opensquilla/gateway/rpc_tools.py`
  - `src/opensquilla/gateway/rpc_models.py`
  - `src/opensquilla/provider/runtime_status.py`
  - `src/opensquilla/search/execution.py`
  - `tests/test_gateway/test_rpc_product_cli_gaps.py`
  - `tests/test_gateway/test_rpc_models.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_search/test_search_runtime_boundary.py`
- Symbols or command surfaces inspected:
  - Serena `initial_instructions` and `activate_project` succeeded for the integration worktree.
  - Serena child activation for this new worktree failed with a stale cached historical child-worktree path; shell/git checks confirm the child worktree itself exists.
  - RPC method surfaces: `tools.catalog`, `tools.effective`, `tools.search_provider`, `providers.status`, `search.status`, `search.query`, and `models.list`.
- Tests inspected:
  - Provider runtime status architecture tests.
  - Search runtime boundary architecture tests.
  - Product RPC method behavior/scope tests.
  - Public RPC surface baseline tests.
- Existing boundary pattern this stage follows:
  - `rpc_models.py` already owns `models.list` separately from tools.
  - Provider runtime payload shape already lives in `provider.runtime_status`.
  - Search status/query payload shape already lives in `search.execution`.

## Boundary Decision

- Responsibilities moving out:
  - `providers.status` RPC registration from `rpc_tools.py` to `rpc_providers.py`.
  - `tools.search_provider`, `search.status`, and `search.query` RPC registration from `rpc_tools.py` to `rpc_search.py`.
- Responsibilities staying in place:
  - `rpc_tools.py` keeps `tools.catalog` and `tools.effective`.
  - Provider status payload construction remains in `opensquilla.provider.runtime_status`.
  - Search provider/status/query payload construction remains in `opensquilla.search.execution`.
  - Public method names, scopes, and payload shapes remain unchanged.
- New module/file responsibility:
  - `src/opensquilla/gateway/rpc_providers.py` owns provider RPC method registration.
  - `src/opensquilla/gateway/rpc_search.py` owns search RPC method registration, including the compatibility method name `tools.search_provider`.
- Public behavior that must not change:
  - `providers.status`, `tools.search_provider`, `search.status`, and `search.query` dispatch through the same method names and scopes.
  - CLI provider status and search status/query calls continue to work.
  - Web UI chat still calls `tools.search_provider`.
  - Public RPC surface baseline remains stable.
- Files explicitly out of scope:
  - Provider runtime status payload internals.
  - Search execution/runtime internals.
  - Tool catalog/effective payload logic.
  - CLI command surfaces and Web UI JavaScript.

## TDD Red/Green

- Failing test command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_domain_modules.py tests/test_provider_runtime_status.py::test_gateway_delegates_provider_status_wire_shape_to_provider_boundary tests/test_search/test_search_runtime_boundary.py::test_gateway_reads_search_provider_from_runtime_boundary tests/test_search/test_search_runtime_boundary.py::test_gateway_runs_search_queries_through_search_boundary -q`
- Expected red failure:
  - `rpc_providers.py` and `rpc_search.py` do not exist.
  - `rpc_tools.py` still registers provider/search RPC methods and imports provider/search payload helpers.
- Minimal implementation:
  - Create `rpc_providers.py` and `rpc_search.py`.
  - Move only method registration wrappers from `rpc_tools.py`.
  - Import the new modules from `gateway/rpc/__init__.py`.
  - Keep provider/search payload helpers unchanged.
- Focused green command:
  - `uv run --extra dev pytest tests/test_gateway/test_rpc_domain_modules.py tests/test_provider_runtime_status.py tests/test_search/test_search_runtime_boundary.py tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_gateway/test_rpc_tools_visibility.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/gateway/rpc_tools.py src/opensquilla/gateway/rpc_providers.py src/opensquilla/gateway/rpc_search.py tests/test_gateway/test_rpc_domain_modules.py tests/test_provider_runtime_status.py tests/test_search/test_search_runtime_boundary.py`
  - `git diff --check`

## Files

- Create:
  - `src/opensquilla/gateway/rpc_providers.py`
  - `src/opensquilla/gateway/rpc_search.py`
  - `tests/test_gateway/test_rpc_domain_modules.py`
  - `docs/refactor/stages/2026-05-18-gateway-rpc-domain-boundary.md`
- Modify:
  - `src/opensquilla/gateway/rpc/__init__.py`
  - `src/opensquilla/gateway/rpc_tools.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_search/test_search_runtime_boundary.py`
- Test:
  - `tests/test_gateway/test_rpc_domain_modules.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_search/test_search_runtime_boundary.py`
  - `tests/test_gateway/test_rpc_product_cli_gaps.py`
  - `tests/test_gateway/test_rpc_public_surface_baseline.py`
  - `tests/test_gateway/test_rpc_tools_visibility.py`
- Documentation:
  - `docs/refactor/stages/2026-05-18-gateway-rpc-domain-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-rpc-domain-boundary`.
- [x] Write the failing Gateway RPC domain architecture tests.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the smallest behavior-compatible RPC module split.
- [x] Run the focused test and touched-file checks.
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

- Revert the integration merge commit if RPC registration, scopes, or payloads regress.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Child commit:
- Integration merge:
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty --expect-branch codex/refactor-gateway-rpc-domain-boundary` passed on branch `codex/refactor-gateway-rpc-domain-boundary` at `2fef810`.
  - Red: `uv run --extra dev pytest tests/test_gateway/test_rpc_domain_modules.py tests/test_provider_runtime_status.py::test_gateway_delegates_provider_status_wire_shape_to_provider_boundary tests/test_search/test_search_runtime_boundary.py::test_gateway_reads_search_provider_from_runtime_boundary tests/test_search/test_search_runtime_boundary.py::test_gateway_runs_search_queries_through_search_boundary -q` failed as expected because `rpc_providers.py` and `rpc_search.py` did not exist, `rpc_tools.py` still imported provider/search payload helpers, and `gateway/rpc/__init__.py` did not import the new modules.
  - Minimal green: the same focused RED command passed, `5 passed in 0.38s`.
  - Focused domain group: `uv run --extra dev pytest tests/test_gateway/test_rpc_domain_modules.py tests/test_provider_runtime_status.py tests/test_search/test_search_runtime_boundary.py tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_gateway/test_rpc_public_surface_baseline.py tests/test_gateway/test_rpc_tools_visibility.py -q` passed, `37 passed in 5.70s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/gateway/rpc_tools.py src/opensquilla/gateway/rpc_providers.py src/opensquilla/gateway/rpc_search.py tests/test_gateway/test_rpc_domain_modules.py tests/test_provider_runtime_status.py tests/test_search/test_search_runtime_boundary.py` passed after `ruff check --fix` normalized the new test import block.
  - Release hygiene spot check: `uv run --extra dev pytest tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths -q` passed, `1 passed in 0.39s`.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 490 source files; whitespace passed; pytest passed with `2408 passed, 8 skipped, 2 warnings in 55.86s`; gateway smoke start/status/stop passed on `127.0.0.1:61076`.
- Residual risk:
  - Low. This slice moves only RPC registration wrappers; provider/search payload construction and public RPC method names/scopes remain unchanged and are covered by product RPC, public surface, provider, search, and tools visibility tests.
- Next recommended slice:
  - Continue Gateway module cleanup with diagnostics/logs or sessions task-runtime families, or pivot to a larger Provider runtime/config module consolidation.
