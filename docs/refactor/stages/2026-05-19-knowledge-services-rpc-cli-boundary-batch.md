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
  - Evidence: read the skill; verified previous temporary refactor worktrees were removed; created fixed active child worktree at `../opensquilla-refactor-active` on branch `codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
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
- [x] Commit this stage plan as the worker base.
  - Commit: `a33b2eb Record knowledge services boundary batch plan`.

### Task 2: Worker `scheduler-cron-boundary`

- [x] Create an independent worker worktree/branch.
  - Branch: `codex/refactor-scheduler-cron-boundary-batch`.
- [x] Write RED boundary tests for scheduler/cron RPC/CLI ownership.
  - Evidence: added scheduler-domain request assembly boundary tests for cron add/update payload ownership.
- [x] Run the worker RED command and record the expected failure.
  - RED command: `uv run --extra dev pytest tests/test_scheduler tests/test_gateway/test_rpc_cron_current_session.py tests/test_gateway/test_cron_view_static.py -q`.
  - Expected failure: `2 failed, 31 passed`, proving scheduler-domain request assembly helpers did not exist and Gateway still owned that boundary.
- [x] Implement one behavior-compatible scheduler/cron boundary move.
  - Evidence: moved cron add/update request assembly into `src/opensquilla/scheduler/rpc_payload.py` while keeping public RPC method names and CLI/static files unchanged.
- [x] Run worker focused tests and touched-file ruff.
  - GREEN command: same focused pytest command -> `33 passed`.
  - Ruff command over touched scheduler/Gateway/test files -> `All checks passed!`.
  - `git diff --check` and post-commit `git diff --check HEAD^ HEAD` passed.
- [x] Commit with the required co-author trailer.
  - Commit: `cbe625b2715e845a5e9f989cd0a77f4e26b756c4 Refactor cron request assembly boundary`.

### Task 3: Worker `memory-source-flush-boundary`

- [x] Create an independent worker worktree/branch.
  - Branch: `codex/refactor-memory-source-flush-boundary-batch`.
- [x] Write RED boundary tests for memory source/flush/tool ownership.
  - Evidence: added memory tool source boundary tests requiring tool result shaping to live in `opensquilla.memory.tool_sources`.
- [x] Run the worker RED command and record the expected failure.
  - RED command: `uv run --extra dev pytest tests/test_memory_tool_sources.py -q`.
  - Expected failure: import failed because `memory_delete_tool_result` and `memory_get_tool_result` did not exist yet.
- [x] Implement one behavior-compatible memory boundary move.
  - Evidence: moved `memory_get` and `memory_delete` tool result shaping into `src/opensquilla/memory/tool_sources.py`; kept `memory_tools.py` as thin runtime/tool registration glue.
- [x] Run worker focused tests and touched-file ruff.
  - GREEN command: `uv run --extra dev pytest tests/test_memory_*.py tests/test_tools/test_memory_profile_guidance.py tests/test_session/test_session_lifecycle_memory.py tests/test_gateway/test_rpc_config_memory_embedding.py tests/test_gateway/test_config_memory_defaults.py -q` -> `107 passed`.
  - Ruff command over touched memory/tool files -> `All checks passed!`.
  - `git diff --check` passed.
- [x] Commit with the required co-author trailer.
  - Commit: `06e0401b17c235685b0b8837155746b3ad5d615f Refactor memory tool source boundary`.

### Task 4: Worker `skills-runtime-hub-boundary`

- [x] Create an independent worker worktree/branch.
  - Branch: `codex/refactor-skills-runtime-hub-boundary-batch`.
- [x] Write RED boundary tests for skills runtime/hub/RPC/CLI ownership.
  - Evidence: added hub search boundary test requiring `hub/search.py` to own top-level search request/outcome types.
- [x] Run the worker RED command and record the expected failure.
  - RED command: `uv run --extra dev pytest tests/test_skills_*.py tests/test_skill_*.py tests/test_gateway_static_skills_view.py -q`.
  - Expected failure: `test_hub_search_module_owns_search_request_and_runtime_boundary` failed because `hub/search.py` did not own top-level `SkillSearchRequest` or `SkillSearchOutcome`.
- [x] Implement one behavior-compatible skills boundary move.
  - Evidence: moved skills hub search request/outcome boundary out of `hub/operations.py` into `hub/search.py`.
- [x] Run worker focused tests and touched-file ruff.
  - GREEN command: same focused pytest command -> `105 passed, 1 skipped`.
  - Ruff command over touched skills hub files -> `All checks passed!`.
  - `git diff --check` and post-commit `git show --check HEAD` passed.
- [x] Commit with the required co-author trailer.
  - Commit: `7dbdbb1cea0b9b0a924e5842505b6396fb5c0a32 Refactor skills hub search boundary`.

### Task 5: Worker `search-runtime-cli-boundary`

- [x] Create an independent worker worktree/branch.
  - Evidence: verified assigned worker worktree `../opensquilla-refactor-agent-search-runtime-cli` and branch `codex/refactor-search-runtime-cli-boundary-batch`.
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
  - Commit: `262788c93cf41b8c2754a203612b90dd8f49a7cb Refactor search RPC payload boundary`.

### Task 6: Main Integration Review

- [x] Wait for all worker branches and read summaries.
- [x] Review each branch diff before merge.
- [x] Merge worker branches into child branch one by one with `git merge --no-ff`.
  - Memory merge: `84ffd3b Merge branch 'codex/refactor-memory-source-flush-boundary-batch' into codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
  - Skills merge: `12b8ce7 Merge branch 'codex/refactor-skills-runtime-hub-boundary-batch' into codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
  - Scheduler merge: `3dd9ebe Merge branch 'codex/refactor-scheduler-cron-boundary-batch' into codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
  - Search merge: `66f7432 Merge branch 'codex/refactor-search-runtime-cli-boundary-batch' into codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
- [x] Resolve conflicts without reverting another worker's ownership.
  - No merge conflicts observed.
- [x] Run the focused batch green command.
  - Baseline before worker merge: `264 passed, 1 skipped`.
  - After worker merges: `271 passed, 1 skipped`.
- [x] Run touched-file ruff, mypy, and `git diff --check`.
  - Targeted ruff over scheduler/memory/skills/search/Gateway/CLI/tests: `All checks passed!`.
  - Targeted mypy over scheduler/memory/skills/search: `Success: no issues found in 86 source files`.
  - `git diff --check`: no output.
- [x] Run full child `scripts/refactor_gate.sh`.
  - First run failed only in `tests/test_public_release_hygiene.py::test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths` because this stage record contained local home paths.
  - `superpowers:systematic-debugging` evidence: read the skill, identified the root cause as two absolute path strings in this stage file, replaced them with relative worktree references, and verified the failing hygiene test passed.
  - Final child gate result: ruff passed; mypy succeeded across 522 source files; whitespace check passed; pytest `2520 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop/status succeeded; `Refactor gate complete.`
- [ ] Commit stage-record update with the required co-author trailer.

### Task 7: Integration Branch Merge and Cleanup

- [x] Merge child into integration with `git merge --no-ff codex/refactor-knowledge-services-rpc-cli-boundary-batch`.
  - Integration merge commit: `453ec668a6f57d481bb704029d9252eafbc41932 Merge branch 'codex/refactor-knowledge-services-rpc-cli-boundary-batch' into codex/refactor-architecture`.
- [x] Run full integration `scripts/refactor_gate.sh`.
  - Result: ruff passed; mypy succeeded across 522 source files; whitespace check passed; pytest `2522 passed, 6 skipped, 2 warnings`; gateway smoke start/status/stop/status succeeded; `Refactor gate complete.`
- [x] Update this completion record with worker commits, child hash, integration hash, verification output, residual risk, and next recommended slice.
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
  - `scheduler-cron-boundary`: `cbe625b2715e845a5e9f989cd0a77f4e26b756c4 Refactor cron request assembly boundary`.
  - `memory-source-flush-boundary`: `06e0401b17c235685b0b8837155746b3ad5d615f Refactor memory tool source boundary`.
  - `skills-runtime-hub-boundary`: `7dbdbb1cea0b9b0a924e5842505b6396fb5c0a32 Refactor skills hub search boundary`.
  - `search-runtime-cli-boundary`: `262788c93cf41b8c2754a203612b90dd8f49a7cb Refactor search RPC payload boundary`.
- Child integration commits:
  - Base plan: `a33b2eb Record knowledge services boundary batch plan`.
  - Worker merges: `84ffd3b`, `12b8ce7`, `3dd9ebe`, `66f7432`.
  - Stage-record update: `4c35d4b Record knowledge services boundary gate`.
- Integration merge:
  - `453ec668a6f57d481bb704029d9252eafbc41932 Merge branch 'codex/refactor-knowledge-services-rpc-cli-boundary-batch' into codex/refactor-architecture`.
  - Final integration stage-record update: pending this commit.
- Verification evidence:
  - `scheduler-cron-boundary` RED: focused scheduler/Gateway cron suite -> `2 failed, 31 passed` before scheduler-domain request assembly helpers existed.
  - `scheduler-cron-boundary` GREEN: same focused suite -> `33 passed`; touched-file ruff and diff-check passed.
  - `memory-source-flush-boundary` RED: `tests/test_memory_tool_sources.py` failed before `memory_get_tool_result` and `memory_delete_tool_result` existed.
  - `memory-source-flush-boundary` GREEN: focused memory suite -> `107 passed`; touched-file ruff and diff-check passed.
  - `skills-runtime-hub-boundary` RED: focused skills suite failed because `hub/search.py` did not own `SkillSearchRequest` / `SkillSearchOutcome`.
  - `skills-runtime-hub-boundary` GREEN: focused skills suite -> `105 passed, 1 skipped`; touched-file ruff and diff-check passed.
  - `search-runtime-cli-boundary` RED: `uv run --extra dev pytest tests/test_search/test_search_runtime_boundary.py -q` failed as expected because the new `search.rpc_payload` boundary did not exist and `rpc_search.py` still imported from `search.execution`.
  - `search-runtime-cli-boundary` GREEN: `uv run --extra dev pytest tests/test_search tests/test_cli/test_search_cmd.py tests/test_onboarding/test_search_specs.py tests/test_skill_multi_search_engine.py -q` -> `30 passed in 0.69s`.
  - `search-runtime-cli-boundary` ruff: touched-file command above -> `All checks passed!`.
  - Combined focused suite after worker merges: `271 passed, 1 skipped`.
  - Targeted mypy after worker merges: `Success: no issues found in 86 source files`.
  - Child `scripts/refactor_gate.sh`: ruff passed; mypy succeeded across 522 source files; whitespace check passed; pytest `2520 passed, 8 skipped, 2 warnings`; gateway smoke start/status/stop/status succeeded; `Refactor gate complete.`
  - Integration `scripts/refactor_gate.sh`: ruff passed; mypy succeeded across 522 source files; whitespace check passed; pytest `2522 passed, 6 skipped, 2 warnings`; gateway smoke start/status/stop/status succeeded; `Refactor gate complete.`
- Residual risk:
  - Workers ran focused tests only; main thread child gate covered full-suite integration after merge.
  - Search keeps compatibility re-exports from `opensquilla.search.execution` to avoid breaking existing imports; a later cleanup can remove them only with a public import audit.
  - Scheduler request assembly moved substantially from Gateway to scheduler domain; full gate passed, but integration gate still must run after merging this child.
- Next recommended slice:
  - Continue with Web UI RPC/view-state or remaining CLI command-family boundaries, selected after integration gate and cleanup.
