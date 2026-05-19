# Provider Runtime Status Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: provider-runtime-status-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-provider-runtime-status-boundary`
- Child worktree: `../opensquilla-refactor-agent-provider`
- Owner: External Codex worker for Provider runtime status/model listing boundary. This worker must not merge into integration or cleanup the worktree.

## Goal

Create a behavior-compatible Provider-domain boundary between runtime status model probing and provider model listing/catalog normalization, while keeping provider defaults, status payloads, model listing payloads, and gateway-facing behavior stable.

## Current-State Audit

- Current HEAD: `b7422a3`.
- Worktree status: clean at preflight; dirty after RED tests and implementation edits.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-provider-rpc-payload-facade.md`
  - `docs/refactor/stages/2026-05-19-provider-status-catalog-batch.md`
  - `docs/refactor/stages/2026-05-19-provider-runtime-model-contract-batch.md`
  - `src/opensquilla/provider/runtime_status.py`
  - `src/opensquilla/provider/model_listing.py`
  - `src/opensquilla/provider/__init__.py`
  - `src/opensquilla/gateway/provider_rpc_payloads.py`
  - `src/opensquilla/gateway/rpc_providers.py`
  - `src/opensquilla/gateway/rpc_models.py`
  - `tests/test_provider_runtime_status.py`
  - `tests/test_provider_model_listing.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_provider_rpc_payload_facade.py`
  - `tests/test_gateway/test_rpc_models.py`
- Symbols or command surfaces inspected:
  - `build_provider_status_report`
  - `build_provider_status_report_for_query`
  - `probe_provider_models`
  - `ProviderStatusQuery`
  - `ProviderModelQuery`
  - `list_provider_model_rows`
  - `list_provider_models_rpc_payload`
  - `providers.status`
  - `models.list`
- Tests inspected:
  - `tests/test_provider_runtime_status.py`
  - `tests/test_provider_model_listing.py`
  - `tests/test_gateway/test_provider_runtime_sync_boundary.py`
  - `tests/test_gateway/test_provider_rpc_payload_facade.py`
  - `tests/test_gateway/test_rpc_models.py`
- Existing boundary pattern this stage follows:
  - Gateway owns JSON/RPC request parsing and wire payload adaptation.
  - Provider owns domain reports, query/filter behavior, selector/catalog normalization, and compatibility wrappers.
  - Provider modules must not import Gateway facades.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; verified this worker is already in the requested isolated worktree `../opensquilla-refactor-agent-provider` on branch `codex/refactor-provider-runtime-status-boundary`; no new worktree was created.
- `superpowers:writing-plans`:
  - Evidence: read the skill; created this stage record from `docs/refactor/stage-template.md` before final verification and commit, with concrete ownership, TDD, and gate evidence.
- `superpowers:test-driven-development`:
  - Evidence: read the skill; wrote RED tests before provider implementation edits.
- `superpowers:verification-before-completion`:
  - Evidence: read the skill; completion requires focused tests, touched-file checks, `scripts/refactor_gate.sh` if feasible, commit hash, and this evidence record.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` or `superpowers:subagent-driven-development` used: not used in this worker turn; the user explicitly assigned this external worker a fixed branch and narrow file ownership.
  - `spawn_agent` probe: not run by this worker.
  - If same-thread agents were unavailable, external worker fallback: this worker itself is the external provider worker at `../opensquilla-refactor-agent-provider`.
- Historical evidence note:
  - Prior provider stages were inspected only as local refactor context. This record only claims Superpowers evidence observed in this worker.

## Boundary decision

- Module batch:
  - Provider runtime status/model listing domain boundary.
- Responsibilities moving out:
  - Runtime status model-probe counting no longer performs ad hoc model payload counting.
  - Selector model output normalization is centralized in a provider-owned model catalog snapshot.
- Responsibilities staying in place:
  - Provider status report construction and compatibility wrappers stay in `provider.runtime_status`.
  - Provider model row/query filtering and compatibility wrappers stay in `provider.model_listing`.
  - Gateway RPC request validation and wire conversion remain in `gateway.provider_rpc_payloads`.
- New module/file responsibility:
  - `ProviderModelCatalog` and `load_provider_model_catalog` in `provider.model_listing` own normalized provider model rows, filtering, and provider counts for provider-domain consumers.
- Public behavior that must not change:
  - `providers.status` and `models.list` payload shapes, method names, filters, pricing keys, model probe keys, selector failure semantics, and API key redaction.
  - Existing provider defaults and buildability checks.
  - Gateway route modules, websocket/session/channels/tools/web UI behavior.
- Files explicitly out of scope:
  - Gateway websocket, session, channels, tools, and Web UI.
  - Provider adapter request internals.
  - CLI provider/model command text.
  - Integration merge and worktree cleanup.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_provider_model_listing.py tests/test_provider_runtime_status.py -q`
- Expected red failure:
  - Collection fails with `ImportError: cannot import name 'ProviderModelCatalog' from 'opensquilla.provider.model_listing'`.
- Behavior compatibility coverage:
  - `ProviderModelCatalog` normalizes dict and `ModelInfo` selector outputs.
  - `ProviderModelCatalog.filter` preserves `ProviderModelQuery` provider/capability filtering.
  - `ProviderModelCatalog.count_provider` provides the runtime status probe count.
  - `list_provider_model_rows` still returns `[]` for missing/failing selectors.
  - `probe_provider_models` still returns `status="error"` for selector exceptions and `status="unavailable"` for missing selectors.
- Module-batch implementation:
  - Add provider-owned model catalog snapshot.
  - Delegate provider row listing through the snapshot.
  - Delegate runtime status model probe counting through the snapshot.
- Focused green command:
  - `uv run --extra dev pytest tests/test_provider_model_listing.py tests/test_provider_runtime_status.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/provider/model_listing.py src/opensquilla/provider/runtime_status.py tests/test_provider_model_listing.py tests/test_provider_runtime_status.py`
  - `uv run --extra dev mypy src/opensquilla/provider/model_listing.py src/opensquilla/provider/runtime_status.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `docs/refactor/stages/2026-05-19-provider-runtime-status-boundary.md`
- Modify:
  - `src/opensquilla/provider/model_listing.py`
  - `src/opensquilla/provider/runtime_status.py`
- Test:
  - `tests/test_provider_model_listing.py`
  - `tests/test_provider_runtime_status.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-provider-runtime-status-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
- [x] Run `scripts/refactor_gate.sh` in integration.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove `../opensquilla-refactor-active`, run
      `git worktree prune`, and verify no extra refactor worktree directories
      remain beyond `../opensquilla-refactor-integration`.

The child worker left integration and cleanup to the main integration owner; the
main thread has since merged the child branch, run the integration gate, and
removed the worker worktree/branch.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- Integration merge: `01e8151` (`Merge provider runtime status boundary`).
- Batch focused verification after merging Channels, Provider, Session,
  Gateway, and Web UI: focused pytest group passed with `110 passed`.
- Full integration gate after the coarse batch and stage-record path cleanup:
  `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues
  in 577 source files; whitespace passed; pytest `2822 passed, 6 skipped, 2
  warnings`; gateway smoke start/status/stop/status passed on
  `127.0.0.1:61875`; final line `Refactor gate complete.`
- Cleanup evidence: the Provider worker worktree and child branch were removed,
  `git worktree prune` was run, and no `opensquilla-refactor-agent-*`
  worktrees remained after cleanup.

## Rollback

- Revert the child commit if provider status model probing or provider model listing behavior regresses.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main`, integration, or unrelated worktrees.

## Completion record

- Child commits:
  - `3d6726e` (`Refactor provider runtime status boundary`).
  - `bddaa62` (`Record provider runtime status boundary`).
- Integration merge: `01e8151` (`Merge provider runtime status boundary`).
- Verification evidence:
  - Preflight: `scripts/refactor_preflight.sh --allow-dirty` passed on branch `codex/refactor-provider-runtime-status-boundary` at `b7422a3`.
  - Red: `uv run --extra dev pytest tests/test_provider_model_listing.py tests/test_provider_runtime_status.py -q` failed during collection with `ImportError: cannot import name 'ProviderModelCatalog' from 'opensquilla.provider.model_listing'`.
  - First focused green: `uv run --extra dev pytest tests/test_provider_model_listing.py tests/test_provider_runtime_status.py -q` passed with `15 passed in 0.14s`.
  - Focused compatibility group: `uv run --extra dev pytest tests/test_provider_model_listing.py tests/test_provider_runtime_status.py tests/test_gateway/test_provider_rpc_payload_facade.py tests/test_gateway/test_rpc_models.py tests/test_gateway/test_provider_runtime_sync_boundary.py -q` passed with `25 passed in 4.96s`.
  - Touched ruff: `uv run --extra dev ruff check src/opensquilla/provider/model_listing.py src/opensquilla/provider/runtime_status.py tests/test_provider_model_listing.py tests/test_provider_runtime_status.py` passed.
  - Touched mypy: `uv run --extra dev mypy src/opensquilla/provider/model_listing.py src/opensquilla/provider/runtime_status.py --show-error-codes` passed with no issues in 2 source files.
  - Whitespace: `git diff --check` passed.
  - Full child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed with no issues in 574 source files; whitespace passed; pytest passed with `2806 passed, 8 skipped, 2 warnings in 66.63s`; gateway smoke start/status/stop/status passed on `127.0.0.1:60964`.
- Residual risk:
  - Low. The new model catalog snapshot centralizes provider model normalization/counting for Provider consumers, and focused plus child and integration full gates cover status payloads, model listing payloads, gateway RPC facade behavior, provider runtime sync boundary, and gateway smoke behavior.
- Integration verification:
  - Coarse-batch focused tests passed with `110 passed`.
  - Full integration gate passed with ruff, mypy over 577 source files,
    whitespace, pytest `2822 passed, 6 skipped, 2 warnings`, gateway smoke on
    `127.0.0.1:61875`, and final line `Refactor gate complete.`
- Cleanup evidence:
  - Provider worker branch/worktree were removed and `git worktree prune`
    completed; only the integration refactor worktree remained for this refactor
    line.
- Next recommended slice:
  - Continue with the next coarse module batch only after checking that its
    ownership boundaries do not overlap already merged Channels, Provider,
    Session, Gateway, Web UI, or Tools files.
