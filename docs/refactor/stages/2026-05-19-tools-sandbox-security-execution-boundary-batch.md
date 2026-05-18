# Tools Sandbox Security Execution Boundary Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for same-thread agent work or `superpowers:executing-plans` only if agent execution becomes unavailable. Steps use checkbox (`- [ ]`) syntax for tracking. This stage must record concrete Superpowers evidence, not only intent.

**Goal:** Refactor the Tools/Sandbox/Security execution surface into clearer behavior-compatible boundaries while preserving tool policy, approval, sandbox, filesystem, patch, code execution, network fetch, SSRF, and failure-envelope behavior.

**Architecture:** Keep existing public tool names, compatibility facades, error envelopes, and security decisions stable. Split the work across independent module families so same-thread workers can run in parallel with explicit ownership; the main thread owns stage planning, merge review, conflict resolution, full gates, and cleanup.

**Tech Stack:** Python 3.12, OpenSquilla tool registry/dispatch, sandbox backends, pytest AST/behavior guards, Ruff, mypy, full `scripts/refactor_gate.sh`.

---

## Stage

- Name: tools-sandbox-security-execution-boundary-batch
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-sandbox-security-execution-boundary-batch`
- Child worktree: `../opensquilla-refactor-active`
- Owner: Codex main thread for architecture, Superpowers evidence, worker dispatch, review, merge integration, full gates, stage record, and cleanup. Same-thread `spawn_agent` was rechecked and is available.

## Goal

Refactor the largest remaining tool and sandbox security surfaces as one cohesive batch:

- make tool runtime/dispatch/envelope responsibilities easier to audit;
- isolate sandbox runtime/governance/backend decisions from concrete tools;
- split local execution/filesystem/patch helper families out of large builtin modules where behavior-compatible;
- keep network/media fetch and SSRF protections explicit and tested;
- preserve all public and user-facing security behavior.

## Current-state audit

- Current HEAD: `7bd25f2`.
- Worktree status: clean before creating this stage plan.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is outside this stage's file scope.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/overall-plan.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-channel-runtime-dispatch-boundary-batch.md`
  - `scripts/refactor_preflight.sh`
  - `scripts/refactor_gate.sh`
  - `scripts/refactor_external_agent.sh`
  - `src/opensquilla/tools/dispatch.py`
  - `src/opensquilla/tools/policy_runtime.py`
  - `src/opensquilla/tools/execution_surface.py`
  - `src/opensquilla/tools/envelope.py`
  - `src/opensquilla/tools/services.py`
  - `src/opensquilla/tools/ssrf.py`
  - `src/opensquilla/tools/builtin/shell.py`
  - `src/opensquilla/tools/builtin/shell_policy.py`
  - `src/opensquilla/tools/builtin/code_exec.py`
  - `src/opensquilla/tools/builtin/filesystem.py`
  - `src/opensquilla/tools/builtin/patch.py`
  - `src/opensquilla/tools/builtin/web.py`
  - `src/opensquilla/tools/builtin/web_fetch.py`
  - `src/opensquilla/tools/builtin/media.py`
  - `src/opensquilla/sandbox/config.py`
  - `src/opensquilla/sandbox/policy.py`
  - `src/opensquilla/sandbox/integration.py`
  - `src/opensquilla/sandbox/governance.py`
  - `src/opensquilla/sandbox/backend/*.py`
- Symbols or command surfaces inspected:
  - `build_tool_handler`
  - `ToolSurfaceCapabilities`
  - `resolve_runtime_tool_surface`
  - `build_tool_execution_surface`
  - `build_policy`
  - shell approval, sandbox request, background process, sensitive path, and timeout helpers
  - filesystem workspace/memory source resolution and sensitive access helpers
  - patch parse/approval/gate/apply helpers
  - code execution destructive/sensitive/network helpers
  - web fetch SSRF, readability, max-chars, and wrapper helpers
- Tests inspected:
  - `tests/test_tools/test_execution_surface_boundary.py`
  - `tests/test_tools/test_policy_runtime_boundary.py`
  - `tests/test_tools/test_policy_config_boundary.py`
  - `tests/test_tools/test_tool_services_boundary.py`
  - `tests/test_tools/test_dispatch_envelope.py`
  - `tests/test_tools/test_shell_approval_policy.py`
  - `tests/test_sandbox/*`
  - `tests/test_security/*`
- Existing boundary pattern this stage follows:
  - `tools.policy` is a compatibility facade over `policy_config` and `policy_runtime`.
  - `tools.execution_surface` owns engine-facing tool execution assembly; engine code should not import dispatch/policy/registry internals directly.
  - Existing tests use AST boundary guards to prove ownership moves while preserving compatibility aliases.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill; verified no existing `../opensquilla-refactor-active`; created child worktree with `git worktree add ../opensquilla-refactor-active -b codex/refactor-tools-sandbox-security-execution-boundary-batch`; ran `scripts/refactor_preflight.sh --expect-branch codex/refactor-tools-sandbox-security-execution-boundary-batch`.
- `superpowers:writing-plans`:
  - Evidence: read the skill; created this stage plan before worker implementation; plan includes exact files, ownership, TDD commands, gates, and completion record fields.
- `superpowers:test-driven-development`:
  - Evidence: read the skill; workers must add RED boundary tests first and record the expected failure before production edits.
- `superpowers:verification-before-completion`:
  - Evidence: read the skill; this stage will not claim completion until focused tests, touched-file checks, child `scripts/refactor_gate.sh`, integration merge, integration `scripts/refactor_gate.sh`, and stage close evidence are recorded.
- `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development`:
  - Evidence: read both skills; same-thread `spawn_agent` probe succeeded with agent `019e3bf2-2247-7b80-8e44-4e75af7c2084`; parallel explorer agents reviewed Tools/Sandbox, Web UI, and Knowledge Services candidates.
- Parallelism decision:
  - Use same-thread worker agents because the batch has disjoint ownership slices and `spawn_agent` is available.
  - If worker spawning fails later, switch to `scripts/refactor_external_agent.sh` fixed worker slots before sequential fallback.
- Historical evidence note:
  - A quick stage-record audit found many previous files contain required Superpowers headers and TDD sections, but not all contain strong evidence of actual use. `2026-05-19-session-lifecycle-flush-boundary.md` has no Superpowers keyword. Going forward, every major stage must fill this evidence section.

## Boundary decision

- Module batch:
  - `tools-sandbox-security-execution-boundary-batch`
- Responsibilities moving out or clarifying:
  - Tool runtime capability, execution surface, dispatch envelope, and service wiring ownership.
  - Sandbox runtime configuration, governance, policy selection, backend selection, and stale output/intent cache boundaries.
  - Local execution adapters for shell/code/filesystem/patch/git helper families.
  - Network/media fetch security, SSRF, HTTP request, and fetch wrapping boundaries.
- Responsibilities staying in place:
  - Public builtin tool names and handler signatures.
  - `tools.policy` compatibility facade.
  - Approval queue and intent cache public runtime behavior.
  - Gateway and engine call sites unless a worker proves a narrow import boundary move is safe.
- New module/file responsibility:
  - Workers may create focused helper modules under `src/opensquilla/tools/builtin/` or `src/opensquilla/tools/` only when the new module owns a coherent security boundary and preserves compatibility imports.
  - Workers may create focused sandbox helper modules only when they reduce coupling without changing backend selection or policy semantics.
- Public behavior that must not change:
  - Canonical five-field tool failure envelopes.
  - Approval statuses and unattended approval behavior.
  - Sensitive path hard blocks except explicit `elevated="full"` behavior.
  - Sandbox network hints and backend selection behavior.
  - Filesystem workspace/memory/bootstrap write notifications.
  - Patch approval payload, fingerprint, and operation validation.
  - SSRF fake-IP trust limited to RFC2544 ranges, never private/loopback ranges.
  - Web fetch max-char handling, wrapping, retry, and external-content safety behavior.
- Files explicitly out of scope:
  - Channel runtime dispatch modules.
  - Provider/model routing.
  - Web UI view-state refactors.
  - Skills/memory/search/scheduler refactors.

## Parallel Worker Ownership

- Worker `tool-surface-dispatch` owns:
  - `src/opensquilla/tools/policy_runtime.py`
  - `src/opensquilla/tools/execution_surface.py`
  - `src/opensquilla/tools/dispatch.py`
  - `src/opensquilla/tools/envelope.py`
  - `src/opensquilla/tools/services.py`
  - Tests:
    - `tests/test_tools/test_policy_runtime_boundary.py`
    - `tests/test_tools/test_execution_surface_boundary.py`
    - `tests/test_tools/test_dispatch_envelope.py`
    - `tests/test_tools/test_dispatch_logs.py`
    - `tests/test_tools/test_tool_failure_envelope.py`
    - `tests/test_tools/test_tool_services_boundary.py`
    - `tests/test_tools/test_registry_visibility_boundary.py`
    - `tests/test_tools/test_registry_visibility.py`
- Worker `sandbox-runtime` owns:
  - `src/opensquilla/sandbox/config.py`
  - `src/opensquilla/sandbox/policy.py`
  - `src/opensquilla/sandbox/integration.py`
  - `src/opensquilla/sandbox/governance.py`
  - `src/opensquilla/sandbox/types.py`
  - `src/opensquilla/sandbox/stale_output_cache.py`
  - `src/opensquilla/sandbox/intent_cache.py`
  - `src/opensquilla/sandbox/backend/*.py`
  - Tests:
    - `tests/test_sandbox/test_policy_network.py`
    - `tests/test_sandbox/test_sandbox_runtime_lifecycle.py`
    - `tests/test_sandbox/test_windows_auto_backend.py`
    - `tests/test_sandbox/test_sensitive_paths.py`
- Worker `local-execution-filesystem` owns:
  - `src/opensquilla/tools/builtin/shell.py`
  - `src/opensquilla/tools/builtin/shell_policy.py`
  - `src/opensquilla/tools/builtin/code_exec.py`
  - `src/opensquilla/tools/builtin/filesystem.py`
  - `src/opensquilla/tools/builtin/patch.py`
  - `src/opensquilla/tools/builtin/git.py`
  - Tests:
    - `tests/test_tools/test_shell_approval_policy.py`
    - `tests/test_tools/test_shell_sensitive.py`
    - `tests/test_tools/test_shell_policy_windows.py`
    - `tests/test_tools/test_shell_process_isolation.py`
    - `tests/test_tools/test_code_exec_python_resolution.py`
    - `tests/test_tools/test_filesystem_read_workspace.py`
    - `tests/test_tools/test_apply_patch_gates.py`
    - `tests/test_tools/test_bootstrap_write_notifications.py`
    - `tests/test_tools/test_sandbox_network_hint.py`
- Worker `network-media-security` owns:
  - `src/opensquilla/tools/ssrf.py`
  - `src/opensquilla/tools/builtin/web.py`
  - `src/opensquilla/tools/builtin/web_fetch.py`
  - `src/opensquilla/tools/builtin/media.py`
  - Tests:
    - `tests/test_security/test_ssrf_fake_ip.py`
    - `tests/test_security/test_sensitive_payloads.py`
    - `tests/test_tools/test_web_http_request.py`
    - `tests/test_tools/test_media_gateway_boundary.py`

Workers are not alone in the codebase. Each worker must preserve other workers' edits, avoid shared-file changes outside its ownership, and not revert unrelated changes.

## TDD Red/Green

- Failing test commands:
  - Worker `tool-surface-dispatch`: `uv run --extra dev pytest tests/test_tools/test_policy_runtime_boundary.py tests/test_tools/test_execution_surface_boundary.py tests/test_tools/test_dispatch_envelope.py -q`
  - Worker `sandbox-runtime`: `uv run --extra dev pytest tests/test_sandbox -q`
  - Worker `local-execution-filesystem`: `uv run --extra dev pytest tests/test_tools/test_shell_approval_policy.py tests/test_tools/test_filesystem_read_workspace.py tests/test_tools/test_apply_patch_gates.py -q`
  - Worker `network-media-security`: `uv run --extra dev pytest tests/test_security/test_ssrf_fake_ip.py tests/test_tools/test_web_http_request.py tests/test_tools/test_media_gateway_boundary.py -q`
- Expected red failures:
  - New boundary tests fail because ownership still lives in larger modules or target helper modules do not exist yet.
  - If a worker only moves helper families with existing coverage, it must first add an AST/import boundary assertion that fails on the current code.
- Behavior compatibility coverage:
  - Tool surface and dispatch tests listed above.
  - Full `tests/test_sandbox`.
  - Local execution/filesystem/patch/code execution tests listed above.
  - Security/network/media tests listed above.
- Module-batch implementation:
  - Move coherent helper families into focused modules without changing public tool behavior.
  - Preserve compatibility imports from existing modules when downstream code or tests currently rely on private names.
  - Add AST/import boundary tests proving new ownership.
  - Keep behavior tests green after each worker slice.
- Focused green command:
  - `uv run --extra dev pytest tests/test_tools/test_policy_runtime_boundary.py tests/test_tools/test_execution_surface_boundary.py tests/test_tools/test_dispatch_envelope.py tests/test_tools/test_dispatch_logs.py tests/test_tools/test_tool_failure_envelope.py tests/test_tools/test_tool_services_boundary.py tests/test_tools/test_registry_visibility_boundary.py tests/test_tools/test_registry_visibility.py tests/test_sandbox tests/test_tools/test_shell_approval_policy.py tests/test_tools/test_shell_sensitive.py tests/test_tools/test_shell_policy_windows.py tests/test_tools/test_shell_process_isolation.py tests/test_tools/test_code_exec_python_resolution.py tests/test_tools/test_filesystem_read_workspace.py tests/test_tools/test_apply_patch_gates.py tests/test_tools/test_bootstrap_write_notifications.py tests/test_tools/test_sandbox_network_hint.py tests/test_security/test_ssrf_fake_ip.py tests/test_security/test_sensitive_payloads.py tests/test_tools/test_web_http_request.py tests/test_tools/test_media_gateway_boundary.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/tools src/opensquilla/sandbox tests/test_tools tests/test_sandbox tests/test_security`
  - `uv run --extra dev mypy src/opensquilla/tools src/opensquilla/sandbox --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - Worker-specific boundary modules and boundary tests as justified by RED tests.
- Modify:
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-19-tools-sandbox-security-execution-boundary-batch.md`
  - Worker-owned files listed in Parallel Worker Ownership.
- Test:
  - Worker tests listed in Parallel Worker Ownership.
- Documentation:
  - This stage file and the stage template Superpowers evidence section.

## Detailed Superpowers Implementation Plan

### Task 1: Baseline, Evidence, and Stage Plan

- [x] Run `scripts/refactor_preflight.sh --expect-branch codex/refactor-architecture` from integration.
- [x] Confirm `spawn_agent` status.
  - Observed: same-thread spawn succeeded.
- [x] Read required Superpowers skills:
  - `superpowers:using-superpowers`
  - `superpowers:using-git-worktrees`
  - `superpowers:writing-plans`
  - `superpowers:dispatching-parallel-agents`
  - `superpowers:subagent-driven-development`
  - `superpowers:test-driven-development`
  - `superpowers:verification-before-completion`
- [x] Use Serena project activation and initial instructions.
- [x] Create fixed active worktree on `codex/refactor-tools-sandbox-security-execution-boundary-batch`.
- [x] Add Superpowers evidence fields to the stage template.
- [x] Write this stage plan before implementation.
- [ ] Commit this stage plan and template evidence update as the worker base.

### Task 2: Worker `tool-surface-dispatch`

- [ ] Write RED boundary tests for any ownership move in tool surface, dispatch, envelope, or services.
- [ ] Run the worker RED command and record the expected failure.
- [ ] Implement the smallest coherent behavior-compatible boundary move.
- [ ] Run worker focused tests and touched-file ruff.
- [ ] Commit with the required co-author trailer.

### Task 3: Worker `sandbox-runtime`

- [ ] Write RED boundary tests for sandbox runtime/governance/backend ownership.
- [ ] Run the worker RED command and record the expected failure.
- [ ] Implement the smallest coherent behavior-compatible sandbox boundary move.
- [ ] Run `uv run --extra dev pytest tests/test_sandbox -q` and touched-file ruff.
- [ ] Commit with the required co-author trailer.

### Task 4: Worker `local-execution-filesystem`

- [ ] Write RED boundary tests for shell/code/filesystem/patch helper ownership.
- [ ] Run the worker RED command and record the expected failure.
- [ ] Implement behavior-compatible helper extraction or boundary clarification.
- [ ] Run worker focused tests and touched-file ruff.
- [ ] Commit with the required co-author trailer.

### Task 5: Worker `network-media-security`

- [ ] Write RED boundary tests for SSRF/network/media fetch ownership.
- [ ] Run the worker RED command and record the expected failure.
- [ ] Implement behavior-compatible helper extraction or boundary clarification.
- [ ] Run worker focused tests and touched-file ruff.
- [ ] Commit with the required co-author trailer.

### Task 6: Main Integration Review

- [ ] Wait for all worker branches and read summaries.
- [ ] Review each branch diff before merge.
- [ ] Merge worker branches into child branch one by one with `git merge --no-ff`.
- [ ] Resolve conflicts without reverting another worker's ownership.
- [ ] Run the focused batch green command.
- [ ] Run touched-file ruff, mypy, and `git diff --check`.
- [ ] Run full child `scripts/refactor_gate.sh`.
- [ ] Commit any integration fix or stage-record update with the required co-author trailer.

### Task 7: Integration Branch Merge and Cleanup

- [ ] Merge child into integration with `git merge --no-ff codex/refactor-tools-sandbox-security-execution-boundary-batch`.
- [ ] Run full integration `scripts/refactor_gate.sh`.
- [ ] Update this completion record with worker commits, child hash, integration hash, verification output, residual risk, and next recommended slice.
- [ ] Commit the stage record update on integration with the required co-author trailer.
- [ ] Remove `../opensquilla-refactor-active`.
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

- Revert the integration merge commit if tool policy, approval, filesystem, patch, sandbox, SSRF, or network/media fetch behavior regresses.
- Keep worker branches until a replacement slice is ready.
- Do not rewrite `main` or unrelated worktrees.

## Completion Record

- Worker commits:
- Child integration commits:
- Integration merge:
- Verification evidence:
- Residual risk:
- Next recommended slice:
