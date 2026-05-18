# Knowledge Services RPC CLI Boundary Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` for same-thread workers or `superpowers:executing-plans` if same-thread agents become unavailable. Each worker must also use `superpowers:test-driven-development` and record RED/GREEN evidence. This stage must record concrete Superpowers evidence, not only intent.

**Goal:** Refactor the knowledge-service module family into clearer behavior-compatible RPC/CLI/runtime boundaries while preserving scheduler, memory, skills, and search public behavior.

**Architecture:** Use four independent worker branches/worktrees for scheduler/cron, memory, skills, and search. Each worker owns one module family plus its Gateway RPC/CLI/static-view contracts. The main thread owns architecture boundaries, plan evidence, worker dispatch, review, child integration, full gates, integration merge, and cleanup.

**Tech Stack:** Python 3.12+, Typer CLI, Starlette Gateway RPC, scheduler/memory/skills/search domain modules, pytest AST and behavior contracts, Ruff, mypy, full `scripts/refactor_gate.sh`.

---

## Stage

- Name: knowledge-services-rpc-cli-boundary-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-knowledge-services-rpc-cli-boundary-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread for architecture, Superpowers evidence, worker dispatch, review, merge integration, full gates, stage record, and cleanup. Same-thread `spawn_agent` healthcheck succeeded with agent `019e3c19-ce5f-7973-97f2-f6e1fb45e1fa`.

## Goal

Refactor the knowledge-service surfaces as one coarse batch:

- keep scheduler/cron route payloads, RPC registration, CLI output, and Web UI contracts stable;
- keep memory source/flush/tool payloads and session lifecycle memory behavior stable;
- keep skills runtime, hub operations, CLI workflows, RPC payloads, and static skills view behavior stable;
- keep search runtime/provider execution, Gateway RPC, CLI search behavior, onboarding search specs, and bundled multi-search skill behavior stable.

## Current-state audit

- Current HEAD: `fb673de`.
- Worktree status: clean before creating this stage plan.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-tools-sandbox-security-execution-boundary-batch.md`
  - `docs/refactor/overall-plan.md`
  - `src/opensquilla/scheduler/*`
  - `src/opensquilla/memory/*`
  - `src/opensquilla/skills/*`
  - `src/opensquilla/skills/hub/*`
  - `src/opensquilla/search/*`
  - `src/opensquilla/search/providers/*`
  - `src/opensquilla/gateway/rpc_cron.py`
  - `src/opensquilla/gateway/rpc_memory.py`
  - `src/opensquilla/gateway/rpc_skills.py`
  - `src/opensquilla/gateway/rpc_search.py`
  - `src/opensquilla/gateway/rpc_onboarding_search.py`
  - `src/opensquilla/cli/cron_cmd.py`
  - `src/opensquilla/cli/memory_flush_cmd.py`
  - `src/opensquilla/cli/skills_cmd.py`
  - `src/opensquilla/cli/search_cmd.py`
  - `src/opensquilla/gateway/static/js/views/cron.js`
  - `src/opensquilla/gateway/static/js/views/skills.js`
- Symbols or command surfaces inspected:
  - Scheduler RPC handlers in `gateway/rpc_cron.py`
  - Memory source RPC helpers in `memory/source_rpc.py`
  - Skills RPC payload helpers in `skills/rpc_payload.py`
  - Search runtime/execution helpers in `search/runtime.py` and `search/execution.py`
  - CLI entrypoints for cron, memory flush, skills, and search.
- Tests inspected:
  - `tests/test_scheduler/*`
  - `tests/test_search/*`
  - `tests/test_memory_*.py`
  - `tests/test_tools/test_memory_profile_guidance.py`
  - `tests/test_session/test_session_lifecycle_memory.py`
  - `tests/test_skills_*.py`
  - `tests/test_skill_*.py`
  - `tests/test_gateway/test_rpc_cron_current_session.py`
  - `tests/test_gateway/test_cron_view_static.py`
  - `tests/test_gateway_static_skills_view.py`
  - `tests/test_cli/test_search_cmd.py`
- Existing boundary pattern this stage follows:
  - Gateway RPC files should stay thin and delegate payload/wire logic into domain modules.
  - Domain `rpc_payload.py` helpers own public wire shapes.
  - Runtime modules own process-wide mutable search/skills services.
  - CLI command files should delegate to gateway query/workflow/presenter modules when the command grows beyond thin Typer glue.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; verified previous temporary refactor worktrees were removed; created fixed active child worktree with `git worktree add /Users/cwan0785/opensquilla-refactor-active -b codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
- `superpowers:writing-plans`:
  - Evidence: read the skill; created this stage plan before worker implementation; plan includes files, ownership, TDD commands, gates, merge review, and cleanup.
- `superpowers:test-driven-development`:
  - Evidence: read the skill; every worker must write a failing boundary/behavior test first and record the expected failure before production edits.
- `superpowers:verification-before-completion`:
  - Evidence: read the skill; stage cannot be claimed complete until focused worker tests, touched-file checks, child `scripts/refactor_gate.sh`, integration `scripts/refactor_gate.sh`, and cleanup audit are recorded.
- `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development`:
  - Evidence: read both skills; same-thread `spawn_agent` healthcheck succeeded with agent `019e3c19-ce5f-7973-97f2-f6e1fb45e1fa`; this stage will dispatch four independent worker agents with separate branches/worktrees.
- Parallelism decision:
  - Use multi-agent, multi-branch parallel execution because scheduler/cron, memory, skills, and search have disjoint primary modules and focused test suites.
  - Each worker must create/use only its assigned sibling worker worktree and branch, then commit with the required trailer.
  - If same-thread spawning fails later, use `scripts/refactor_external_agent.sh` fixed worker slots before sequential fallback.
- Historical evidence note:
  - The user explicitly required every large refactor substage to use and record Superpowers. Treat missing per-worker evidence as a stage-record gap.

## Boundary decision

- Module batch:
  - `knowledge-services-rpc-cli-boundary-batch`
- Responsibilities moving out or clarifying:
  - Scheduler/cron request parsing, route payload, and RPC/CLI presentation boundaries.
  - Memory source/flush/tool RPC payload and CLI/session lifecycle boundaries.
  - Skills runtime/hub operations, RPC payload, CLI workflow, and static view contracts.
  - Search runtime/provider execution, RPC payload, CLI query/presenter, onboarding sync, and bundled search skill contracts.
- Responsibilities staying in place:
  - Public RPC method names/scopes and camelCase wire keys.
  - CLI command names, option names, and user-facing output.
  - Runtime mutable state ownership in `skills.runtime` and `search.runtime`.
  - Existing Gateway service orchestration and session lifecycle memory boundaries unless a worker proves a narrow compatibility move.
- New module/file responsibility:
  - Workers may add focused helper modules only when a RED boundary test proves the new ownership and compatibility imports preserve existing behavior.
  - Workers should prefer clarifying ownership around already-existing `rpc_payload`, `runtime`, workflow, and presenter modules before introducing new broad abstractions.
- Public behavior that must not change:
  - `cron.*`, `memory.*`, `skills.*`, `tools.search_provider`, `search.status`, and `search.query` RPC method names/scopes.
  - Scheduler route inference, current-session binding, subscriptions, run history, and Web UI cron payloads.
  - Memory source list/search/show payloads, memory flush behavior, memory tools behavior, and session lifecycle memory preservation.
  - Skills loader namespace/provenance behavior, hub install/update/uninstall/deps behavior, skill search payloads, and bundled skill assets.
  - Search provider fallback, diagnostics, Brave config handling, no-network test discipline, CLI output, and onboarding search config sync.
- Files explicitly out of scope:
  - Provider runtime/model routing.
  - Channel runtime dispatch.
  - Tools/sandbox/security surfaces completed in the previous batch.
  - Session lifecycle internals except memory-facing regression tests.
  - Web UI redesign; static cron/skills tests may be touched only to preserve existing contracts.

## Parallel Worker Ownership

- Worker `scheduler-cron-boundary` owns:
  - `src/opensquilla/scheduler/*`
  - `src/opensquilla/gateway/rpc_cron.py`
  - `src/opensquilla/cli/cron_cmd.py`
  - `src/opensquilla/gateway/static/js/views/cron.js`
  - `src/opensquilla/gateway/static/css/views/cron.css`
  - Tests:
    - `tests/test_scheduler/*`
    - `tests/test_gateway/test_rpc_cron_current_session.py`
    - `tests/test_gateway/test_cron_view_static.py`
- Worker `memory-source-flush-boundary` owns:
  - `src/opensquilla/memory/*`
  - `src/opensquilla/gateway/rpc_memory.py`
  - `src/opensquilla/gateway/rpc_onboarding_memory.py`
  - `src/opensquilla/cli/memory_flush_cmd.py`
  - `src/opensquilla/tools/builtin/memory_tools.py`
  - Tests:
    - `tests/test_memory_*.py`
    - `tests/test_tools/test_memory_profile_guidance.py`
    - `tests/test_session/test_session_lifecycle_memory.py`
    - `tests/test_gateway/test_rpc_config_memory_embedding.py`
    - `tests/test_gateway/test_config_memory_defaults.py`
- Worker `skills-runtime-hub-boundary` owns:
  - `src/opensquilla/skills/*`
  - `src/opensquilla/skills/hub/*`
  - `src/opensquilla/cli/skills*.py`
  - `src/opensquilla/gateway/rpc_skills.py`
  - `src/opensquilla/gateway/static/js/views/skills.js`
  - `src/opensquilla/gateway/static/css/views/skills.css`
  - Tests:
    - `tests/test_skills_*.py`
    - `tests/test_skill_*.py`
    - `tests/test_gateway_static_skills_view.py`
- Worker `search-runtime-cli-boundary` owns:
  - `src/opensquilla/search/*`
  - `src/opensquilla/search/providers/*`
  - `src/opensquilla/cli/search*.py`
  - `src/opensquilla/gateway/rpc_search.py`
  - `src/opensquilla/gateway/rpc_onboarding_search.py`
  - `src/opensquilla/tools/builtin/web.py` only if preserving the search tool boundary requires it.
  - Tests:
    - `tests/test_search/*`
    - `tests/test_cli/test_search_cmd.py`
    - `tests/test_onboarding/test_search_specs.py`
    - `tests/test_skill_multi_search_engine.py`

Workers are not alone in the codebase. Each worker must preserve other workers' edits, avoid shared-file changes outside its ownership, and not revert unrelated changes. If a worker needs a shared file outside ownership, it must stop and report the proposed change instead of editing it.

## TDD Red/Green

- Failing test commands:
  - Scheduler: `uv run --extra dev pytest tests/test_scheduler tests/test_gateway/test_rpc_cron_current_session.py tests/test_gateway/test_cron_view_static.py -q`
  - Memory: `uv run --extra dev pytest tests/test_memory_*.py tests/test_tools/test_memory_profile_guidance.py tests/test_session/test_session_lifecycle_memory.py tests/test_gateway/test_rpc_config_memory_embedding.py tests/test_gateway/test_config_memory_defaults.py -q`
  - Skills: `uv run --extra dev pytest tests/test_skills_*.py tests/test_skill_*.py tests/test_gateway_static_skills_view.py -q`
  - Search: `uv run --extra dev pytest tests/test_search tests/test_cli/test_search_cmd.py tests/test_onboarding/test_search_specs.py tests/test_skill_multi_search_engine.py -q`
- Expected red failures:
  - New boundary tests fail because request parsing, payload construction, runtime ownership, or CLI presentation still lives in the previous module.
  - If a worker only clarifies an existing boundary, it must add an AST/import/behavior contract that fails on current ownership before implementation.
- Behavior compatibility coverage:
  - Scheduler, memory, skills, and search focused suites above.
  - Public RPC surface baseline and product CLI completeness tests if a worker touches RPC names/scopes or CLI help/output.
- Module-batch implementation:
  - Move or clarify one coherent ownership boundary per worker.
  - Preserve compatibility imports when downstream tests or public modules currently import private names.
  - Keep worker changes within ownership.
- Focused green command:
  - `uv run --extra dev pytest tests/test_scheduler tests/test_gateway/test_rpc_cron_current_session.py tests/test_gateway/test_cron_view_static.py tests/test_memory_*.py tests/test_tools/test_memory_profile_guidance.py tests/test_session/test_session_lifecycle_memory.py tests/test_gateway/test_rpc_config_memory_embedding.py tests/test_gateway/test_config_memory_defaults.py tests/test_skills_*.py tests/test_skill_*.py tests/test_gateway_static_skills_view.py tests/test_search tests/test_cli/test_search_cmd.py tests/test_onboarding/test_search_specs.py tests/test_skill_multi_search_engine.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/scheduler src/opensquilla/memory src/opensquilla/skills src/opensquilla/search src/opensquilla/gateway/rpc_cron.py src/opensquilla/gateway/rpc_memory.py src/opensquilla/gateway/rpc_skills.py src/opensquilla/gateway/rpc_search.py src/opensquilla/cli/cron_cmd.py src/opensquilla/cli/memory_flush_cmd.py src/opensquilla/cli/skills_cmd.py src/opensquilla/cli/search_cmd.py tests/test_scheduler tests/test_search tests`
  - `uv run --extra dev mypy src/opensquilla/scheduler src/opensquilla/memory src/opensquilla/skills src/opensquilla/search --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - Worker-specific boundary modules and boundary tests as justified by RED tests.
- Modify:
  - This stage file.
  - Worker-owned files listed in Parallel Worker Ownership.
- Test:
  - Worker tests listed in Parallel Worker Ownership.
- Documentation:
  - This stage file records Superpowers, TDD, merge, gate, and cleanup evidence.

## Detailed Superpowers Implementation Plan

### Task 1: Baseline, Evidence, and Stage Plan

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` from integration.
- [x] Confirm `spawn_agent` status.
  - Observed: same-thread healthcheck succeeded.
- [x] Read required Superpowers skills:
  - `superpowers:using-superpowers`
  - `superpowers:using-git-worktrees`
  - `superpowers:writing-plans`
  - `superpowers:dispatching-parallel-agents`
  - `superpowers:subagent-driven-development`
  - `superpowers:test-driven-development`
  - `superpowers:verification-before-completion`
- [x] Use Serena project activation and initial instructions.
- [x] Create fixed active worktree on `codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
- [x] Write this stage plan before implementation.
- [ ] Commit this stage plan as the worker base.

### Task 2: Worker `scheduler-cron-boundary`

- [ ] Create an independent worker worktree/branch.
- [ ] Write RED boundary tests for scheduler/cron RPC/CLI ownership.
- [ ] Run the worker RED command and record the expected failure.
- [ ] Implement one behavior-compatible scheduler/cron boundary move.
- [ ] Run worker focused tests and touched-file ruff.
- [ ] Commit with the required co-author trailer.

### Task 3: Worker `memory-source-flush-boundary`

- [ ] Create an independent worker worktree/branch.
- [ ] Write RED boundary tests for memory source/flush/tool ownership.
- [ ] Run the worker RED command and record the expected failure.
- [ ] Implement one behavior-compatible memory boundary move.
- [ ] Run worker focused tests and touched-file ruff.
- [ ] Commit with the required co-author trailer.

### Task 4: Worker `skills-runtime-hub-boundary`

- [ ] Create an independent worker worktree/branch.
- [ ] Write RED boundary tests for skills runtime/hub/RPC/CLI ownership.
- [ ] Run the worker RED command and record the expected failure.
- [ ] Implement one behavior-compatible skills boundary move.
- [ ] Run worker focused tests and touched-file ruff.
- [ ] Commit with the required co-author trailer.

### Task 5: Worker `search-runtime-cli-boundary`

- [x] Create an independent worker worktree/branch.
  - Evidence: verified `pwd` as `/Users/cwan0785/opensquilla-refactor-agent-search-runtime-cli` and branch as `codex/refactor-search-runtime-cli-boundary-batch`.
- [x] Write RED boundary tests for search runtime/provider/RPC/CLI ownership.
  - Evidence: added `tests/test_search/test_search_runtime_boundary.py::test_search_rpc_payload_boundary_owns_request_and_wire_shape` requiring `opensquilla.search.rpc_payload` to own RPC request/wire helpers.
- [x] Run the worker RED command and record the expected failure.
  - RED command: `uv run --extra dev pytest tests/test_search/test_search_runtime_boundary.py -q`
  - Expected failure: `SEARCH_RPC_PAYLOAD.exists()` was false and `src/opensquilla/gateway/rpc_search.py` still imported RPC payload helpers from `opensquilla.search.execution`.
- [x] Implement one behavior-compatible search boundary move.
  - Evidence: created `src/opensquilla/search/rpc_payload.py` for search provider/status/query RPC request parsing and wire payload shaping; kept provider execution and fallback behavior in `src/opensquilla/search/execution.py`; preserved compatibility re-exports from `opensquilla.search.execution`.
- [x] Run worker focused tests and touched-file ruff.
  - GREEN command: `uv run --extra dev pytest tests/test_search tests/test_cli/test_search_cmd.py tests/test_onboarding/test_search_specs.py tests/test_skill_multi_search_engine.py -q`
  - GREEN result: `30 passed in 0.69s`.
  - Ruff command: `uv run --extra dev ruff check src/opensquilla/search src/opensquilla/gateway/rpc_search.py src/opensquilla/cli/search_cmd.py src/opensquilla/cli/search_gateway_queries.py src/opensquilla/cli/search_workflows.py src/opensquilla/cli/search_presenters.py tests/test_search tests/test_cli/test_search_cmd.py tests/test_onboarding/test_search_specs.py tests/test_skill_multi_search_engine.py`
  - Ruff result: `All checks passed!`.
- [x] Commit with the required co-author trailer.
  - Evidence: worker branch HEAD includes the search boundary refactor commit with `Co-authored-by: Codex <noreply@openai.com>`.

### Task 6: Main Integration Review

- [ ] Wait for all worker branches and read summaries.
- [ ] Review each branch diff before merge.
- [ ] Merge worker branches into child branch one by one with `git merge --no-ff`.
- [ ] Resolve conflicts without reverting another worker's ownership.
- [ ] Run the focused batch green command.
- [ ] Run touched-file ruff, mypy, and `git diff --check`.
- [ ] Run full child `scripts/refactor_gate.sh`.
- [ ] Commit stage-record update with the required co-author trailer.

### Task 7: Integration Branch Merge and Cleanup

- [ ] Merge child into integration with `git merge --no-ff codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
- [ ] Run full integration `scripts/refactor_gate.sh`.
- [ ] Update this completion record with worker commits, child hash, integration hash, verification output, residual risk, and next recommended slice.
- [ ] Commit the stage record update on integration with the required co-author trailer.
- [ ] Remove `../opensquilla-refactor-active`.
- [ ] Remove worker worktrees created for this batch.
- [ ] Run `git worktree prune`.
- [ ] Verify no extra refactor worktree directories remain beyond `../opensquilla-refactor-integration`.

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

- Revert the integration merge commit if scheduler, memory, skills, search, RPC, CLI, or Web UI contract behavior regresses.
- Keep worker branches until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Worker commits:
  - `search-runtime-cli-boundary`: branch HEAD on `codex/refactor-search-runtime-cli-boundary-batch`; final worker handoff reports the exact hash.
- Child integration commits:
- Integration merge:
- Verification evidence:
  - `search-runtime-cli-boundary` RED: `uv run --extra dev pytest tests/test_search/test_search_runtime_boundary.py -q` failed as expected because the new `search.rpc_payload` boundary did not exist and `rpc_search.py` still imported from `search.execution`.
  - `search-runtime-cli-boundary` GREEN: `uv run --extra dev pytest tests/test_search tests/test_cli/test_search_cmd.py tests/test_onboarding/test_search_specs.py tests/test_skill_multi_search_engine.py -q` -> `30 passed in 0.69s`.
  - `search-runtime-cli-boundary` ruff: touched-file command above -> `All checks passed!`.
- Residual risk:
  - `search-runtime-cli-boundary`: only focused search/CLI/onboarding/multi-search coverage run in this worker; full child and integration gates remain with the main integration thread.
- Next recommended slice:
