# Contracts Adoption Backplane Batch Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: use `superpowers:writing-plans` before implementation. Use `superpowers:test-driven-development` for code or executable behavior and `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: contracts-adoption-backplane-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-contracts-adoption-backplane-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread; implementation stays serial because the batch defines one shared application-facing contract composition seam.

## Goal

Make `src/opensquilla/contracts` ports more than passive DTO exports by adding an application-owned backplane that composes tool, session, provider, channel, and memory ports behind a stable boundary, preserving all public runtime behavior.

## Current-state audit

- Current HEAD: `b310183`.
- Worktree status: clean before this stage plan and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists outside this stage scope.
- Files inspected:
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-global-component-plugin-decoupling-audit.md`
  - `src/opensquilla/contracts/__init__.py`
  - `src/opensquilla/contracts/tool.py`
  - `src/opensquilla/contracts/session.py`
  - `src/opensquilla/contracts/provider.py`
  - `src/opensquilla/contracts/channel.py`
  - `src/opensquilla/contracts/memory.py`
  - `src/opensquilla/application/turn.py`
  - `src/opensquilla/application/__init__.py`
  - `src/opensquilla/tools/registry.py`
  - `src/opensquilla/session/services.py`
  - `src/opensquilla/provider/factory.py`
  - `src/opensquilla/channels/ingress.py`
  - `src/opensquilla/memory/protocols.py`
- Symbols or command surfaces inspected:
  - Serena overviews for contract port files, `application.turn`, `tools.registry`, `session.manager`, `provider.protocol`, `provider.factory`, `channels.ingress`, `gateway.channel_ingress`, and `memory.protocols`.
  - Static contract import grep showed only sparse direct consumers: `application.turn` plus attachment policy constants.
- Tests inspected:
  - `tests/test_contracts/test_contracts_import_boundary.py`
  - `tests/test_application/test_turn_use_case.py`
  - `tests/test_ci/test_architecture_import_contracts.py`
- Existing boundary pattern this stage follows:
  - `application.turn` already defines a use-case seam over contract DTOs; G005 adds a sibling backplane seam that wires cross-subsystem ports without importing concrete implementations.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; created fixed child worktree `../opensquilla-refactor-active` on branch `codex/refactor-contracts-adoption-backplane-batch`; ran `scripts/refactor_preflight.sh --expect-branch codex/refactor-contracts-adoption-backplane-batch --allow-dirty`.
- `superpowers:writing-plans`:
  - Evidence: read the skill; wrote this plan before adding the RED test or implementation.
- `superpowers:test-driven-development`:
  - Evidence: read the skill; first contract test run failed with `ModuleNotFoundError: No module named 'opensquilla.application.backplane'` before implementation, then the same focused coverage passed after adding the backplane.
- `superpowers:verification-before-completion`:
  - Evidence: read the skill; stage is not complete until RED/GREEN, focused tests, touched checks, child gate, merge gate, cleanup, and checkpoint evidence are recorded. Child worktree verification is recorded below; integration evidence remains pending until merge.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development` used: skills were read in G004; same-thread explore agents failed with 429 and this G005 implementation owns one shared composition file, so serial execution avoids conflicting application exports.
  - `spawn_agent` probe: unavailable/unreliable in this run due 429 failures.
  - External worker fallback: not used because the seam is intentionally a single application backplane rather than independent module edits.
- Historical evidence note:
  - G001 explicitly identified contracts as sparse and partly decorative outside attachment constants and `application.turn`; G005 addresses that gap.

## Boundary decision

- Module batch: application contracts adoption/backplane.
- Responsibilities moving out:
  - Cross-subsystem contract composition moves into `opensquilla.application.backplane` rather than ad-hoc consumer wiring.
- Responsibilities staying in place:
  - Concrete tools/session/provider/channel/memory implementations and public RPC/CLI behavior remain unchanged.
  - `contracts` remains implementation-free.
  - `application.turn` runtime orchestration remains unchanged.
- New module/file responsibility:
  - `opensquilla.application.backplane.ContractBackplane` owns optional contract ports for tools, sessions, providers, channels, and memory plus small helper methods that call those ports without concrete imports.
- Public behavior that must not change:
  - Existing imports from `opensquilla.application` keep working.
  - Contract package import boundary remains implementation-free.
  - No RPC method names, CLI output, WebSocket events, provider defaults, or channel replies change.
- Files explicitly out of scope:
  - Concrete tool registry internals, session storage internals, provider adapter payloads, channel dispatch loop, memory retrieval implementation, web UI.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_application/test_contract_backplane.py tests/test_contracts/test_contracts_import_boundary.py -q`
- Expected red failure:
  - `ModuleNotFoundError: No module named 'opensquilla.application.backplane'`.
- Red evidence:
  - Command above failed as expected with `ModuleNotFoundError: No module named 'opensquilla.application.backplane'`.
- Behavior compatibility coverage:
  - Backplane tests use fake implementations of `ToolRegistryPort`, `ToolPolicyPort`, `SessionStorePort`, `ProviderFactoryPort`, `ChannelIngressPort`, and `MemoryPort` to prove the application seam calls each port.
  - Contract import-boundary tests prove `contracts` remains independent from implementation packages.
  - Architecture import-contract tests prove no new forbidden package edges.
- Module-batch implementation:
  - Add `src/opensquilla/application/backplane.py`.
  - Export `ContractBackplane` from `src/opensquilla/application/__init__.py`.
  - Add `tests/test_application/test_contract_backplane.py`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_application/test_contract_backplane.py tests/test_application/test_turn_use_case.py tests/test_contracts/test_contracts_import_boundary.py tests/test_ci/test_architecture_import_contracts.py -q`
- Focused green evidence:
  - `9 passed in 1.73s`.
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/application/backplane.py src/opensquilla/application/__init__.py tests/test_application/test_contract_backplane.py`
    - `All checks passed!`
  - `uv run --extra dev mypy src/opensquilla/application/backplane.py --show-error-codes`
    - `Success: no issues found in 1 source file`
  - `git diff --check`
    - exit 0.

## Files

- Create:
  - `src/opensquilla/application/backplane.py`
  - `tests/test_application/test_contract_backplane.py`
- Modify:
  - `src/opensquilla/application/__init__.py`
  - `docs/refactor/stages/2026-05-19-contracts-adoption-backplane-batch.md`
- Test:
  - `tests/test_application/test_contract_backplane.py`
  - `tests/test_application/test_turn_use_case.py`
  - `tests/test_contracts/test_contracts_import_boundary.py`
  - `tests/test_ci/test_architecture_import_contracts.py`

## Steps

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-contracts-adoption-backplane-batch --allow-dirty`.
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
- [x] Remove `../opensquilla-refactor-active`, run `git worktree prune`, and verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check HEAD^ HEAD`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Rollback

- Revert the integration merge commit if the slice regresses application exports, contract import independence, or public runtime behavior.
- Keep the child branch for diagnosis until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit: `7d9b630`.
- Integration merge: `2c00a7c`.
- Verification evidence:
  - Child focused tests: `9 passed in 1.73s`.
  - Child touched checks:
    - Ruff touched files: `All checks passed!`
    - Mypy touched backplane: `Success: no issues found in 1 source file`
    - `git diff --check`: exit 0.
  - Child full gate: `scripts/refactor_gate.sh` completed with `2836 passed, 8 skipped, 2 warnings` and gateway smoke passed on port `65468`.
  - Integration full gate: `scripts/refactor_gate.sh` completed with `2838 passed, 6 skipped, 2 warnings` and gateway smoke passed on port `49238`.
  - Cleanup: `git worktree remove ../opensquilla-refactor-active` and `git worktree prune` completed; `git worktree list` shows only the integration worktree for the refactor line.
- Residual risk:
  - This stage introduces a composition seam and export only; concrete subsystem consumers are not migrated wholesale in this slice to avoid changing public runtime behavior. Future slices can inject `ContractBackplane` where application-level assembly needs a single contract port bundle.
- Next recommended slice:
  - G006 release/docs convergence and final quality gate: reconcile stage evidence, run final main-parity/release checks, and close the ultragoal only after a fresh integration gate.
