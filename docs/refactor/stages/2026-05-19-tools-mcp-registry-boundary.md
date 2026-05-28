# Tools MCP Registry Boundary

> For agentic workers: REQUIRED SUB-SKILL: use
> `superpowers:writing-plans` before implementation. Use
> `superpowers:test-driven-development` for code or executable behavior and
> `superpowers:verification-before-completion` before claiming completion.

## Stage

- Name: tools-mcp-registry-boundary
- Date: 2026-05-19
- Integration branch: `codex/refactor-architecture`
- Child branch: `codex/refactor-tools-mcp-registry-boundary`
- Child worktree: `../opensquilla-refactor-agent-tools`
- Owner: Codex worker scoped to Tools MCP/tool registry lifecycle boundary.

## Goal

Create a behavior-compatible Tools-owned boundary for externally discovered
tool lifecycle ownership and dispatch-time visibility decisions, without
changing public tool names, schemas, policies, or failure envelopes.

## Current-state audit

- Current HEAD: `b7422a3`.
- Worktree status: clean before this stage record and RED tests.
- AGENTS.md files in scope:
  - `AGENTS.md`
  - `src/opensquilla/identity/templates/bootstrap/AGENTS.md` exists but is
    outside this stage's files.
- Files inspected:
  - `AGENTS.md`
  - `docs/refactor/stage-template.md`
  - `docs/refactor/stages/2026-05-18-tools-registry-visibility-boundary.md`
  - `docs/refactor/stages/2026-05-19-tools-gateway-runtime-surface-batch.md`
  - `src/opensquilla/tools/registry.py`
  - `src/opensquilla/tools/services.py`
  - `src/opensquilla/tools/dispatch.py`
  - `src/opensquilla/tools/visibility.py`
  - `src/opensquilla/tools/builtin/loader.py`
  - `src/opensquilla/tools/types.py`
  - `src/opensquilla/mcp/discovery.py`
  - `tests/test_tools/test_registry_visibility_boundary.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_mcp/test_discovery_lifecycle.py`
- Symbols or command surfaces inspected:
  - `ToolRegistry.register`
  - `ToolRegistry.unregister`
  - `ToolRegistry._iter_visible_tools`
  - `visible_registered_tools`
  - `build_tool_handler`
  - `discover_and_register`
  - `close_active_clients`
- Tests inspected:
  - Registry visibility/profile boundary tests.
  - Registry dispatch envelope tests.
  - MCP discovery lifecycle tests.
- Existing boundary pattern this stage follows:
  - `tools.visibility` owns context visibility policy while `ToolRegistry`
    keeps compatibility wrappers and core registration.
  - `tools.surface` owns row/context helpers while `ToolRegistry` remains the
    public registry facade.

## Superpowers evidence

- `superpowers:using-git-worktrees`:
  - Evidence: read the skill before work; this task arrived already pinned to
    sibling worktree `../opensquilla-refactor-agent-tools` on
    `codex/refactor-tools-mcp-registry-boundary`, and
    `scripts/refactor_preflight.sh --allow-dirty` confirmed that
    worktree/branch.
- `superpowers:writing-plans`:
  - Evidence: read the skill before implementation; this stage record captures
    the concrete file ownership, RED/GREEN commands, gate commands, and
    completion evidence.
- `superpowers:test-driven-development`:
  - Evidence: RED tests are written before production edits and run before
    implementation.
- `superpowers:verification-before-completion`:
  - Evidence: no completion claim until focused tests, touched-file checks,
    diff check, and the feasible refactor gate are freshly run and recorded.
- Parallelism decision:
  - `superpowers:dispatching-parallel-agents` or
    `superpowers:subagent-driven-development` used: no; user explicitly scoped
    this as a single worker in a fixed worktree/branch, and the touched module
    set is narrow.
  - `spawn_agent` probe: not run for this worker slice.
  - If same-thread agents were unavailable, external worker fallback: not used.
- Historical evidence note:
  - This record does not infer Superpowers usage for prior stages.

## Boundary decision

- Module batch:
  - Tool registry lifecycle ownership for externally registered tools.
  - Dispatch-time visibility/policy decision reuse through `tools.visibility`.
- Responsibilities moving out:
  - Duplicate dispatch checks for `owner_only`, `denied_tools`, and
    `allowed_tools` decision logic move into a Tools visibility helper.
- Responsibilities staying in place:
  - `ToolRegistry` remains the registration, lookup, unregister, schema export,
    and compatibility facade.
  - `dispatch.py` keeps injection guard, skill-name mismatch behavior, channel
    permission matrix checks, approval-surface handling, result wrapping, and
    stable failure-envelope construction.
  - MCP client process lifecycle remains in `opensquilla.mcp.discovery`; the
    Tools-owned registry boundary only tracks and unregisters tools by lifecycle
    owner.
- New module/file responsibility:
  - `src/opensquilla/tools/visibility.py` owns dispatch visibility block
    decisions shared by schema visibility and dispatch defense-in-depth.
  - `ToolRegistry` owns lifecycle-owner metadata and unregister-by-owner
    operations for tools such as MCP-discovered registrations.
- Public behavior that must not change:
  - Registered tool names, including `mcp_` prefix behavior.
  - Existing `ToolRegistry.register(spec, handler)` call sites.
  - Owner-only and policy-denied dispatch error classes and user messages.
  - Tool-not-found and skill-name mismatch failure envelopes.
  - Visibility filtering, row shapes, sorting, and public compatibility imports.
- Files explicitly out of scope:
  - Provider, session, channels, gateway WebSocket, web UI.
  - MCP transport client implementations.
  - Shell/filesystem/web/patch builtin tool behavior.

## TDD red/green

- Failing test command:
  - `uv run --extra dev pytest tests/test_tools/test_registry_lifecycle_boundary.py tests/test_mcp/test_discovery_lifecycle.py::test_tool_registry_lifecycle_owner_can_remove_mcp_registered_surface -q`
- Expected red failure:
  - `TypeError: ToolRegistry.register() got an unexpected keyword argument 'owner'`
  - `AttributeError` for lifecycle owner helpers before implementation.
- Behavior compatibility coverage:
  - Registry lifecycle ownership can remove MCP-owned tools without touching
    builtin tools.
  - Dispatch owner-only, denied, and allowed-tool failures keep the same error
    classes and user messages while decision logic comes from
    `tools.visibility`.
- Module-batch implementation:
  - Add lifecycle owner metadata to `ToolRegistry`.
  - Add unregister-by-owner and owner lookup helpers.
  - Add a `tools.visibility` dispatch block helper and call it from
    `dispatch.py`.
- Focused green command:
  - `uv run --extra dev pytest tests/test_tools/test_registry_lifecycle_boundary.py tests/test_mcp/test_discovery_lifecycle.py tests/test_tools/test_registry_visibility.py tests/test_tools/test_dispatch_envelope.py -q`
- Additional touched-file checks:
  - `uv run --extra dev ruff check src/opensquilla/tools/registry.py src/opensquilla/tools/dispatch.py src/opensquilla/tools/visibility.py tests/test_tools/test_registry_lifecycle_boundary.py tests/test_mcp/test_discovery_lifecycle.py`
  - `uv run --extra dev mypy src/opensquilla/tools/registry.py src/opensquilla/tools/dispatch.py src/opensquilla/tools/visibility.py --show-error-codes`
  - `git diff --check`

## Files

- Create:
  - `tests/test_tools/test_registry_lifecycle_boundary.py`
- Modify:
  - `src/opensquilla/tools/registry.py`
  - `src/opensquilla/tools/dispatch.py`
  - `src/opensquilla/tools/visibility.py`
- Test:
  - `tests/test_tools/test_registry_lifecycle_boundary.py`
  - `tests/test_mcp/test_discovery_lifecycle.py`
  - `tests/test_tools/test_registry_visibility.py`
  - `tests/test_tools/test_dispatch_envelope.py`
- Documentation:
  - `docs/refactor/stages/2026-05-19-tools-mcp-registry-boundary.md`

## Steps

- [x] Run `scripts/refactor_preflight.sh --allow-dirty`.
- [x] Write the failing test or executable contract.
- [x] Run the focused test and confirm the expected failure.
- [x] Implement the cohesive behavior-compatible module batch without dropping
      existing feature coverage.
- [x] Run the focused test and touched-file checks.
- [x] Run `scripts/refactor_gate.sh`.
- [x] Commit with:

```text
Co-authored-by: Codex <noreply@openai.com>
```

- [x] Merge child into integration with `git merge --no-ff`.
      Merge: `1b5e36c` (`Merge tools MCP registry boundary`).
- [x] Run `scripts/refactor_gate.sh` in integration.
      Result: ruff all checks passed; mypy success for 574 source files;
      pytest `2813 passed, 6 skipped, 2 warnings`; gateway smoke passed on
      port `61461`.
- [x] Record child hash, integration hash, verification, and next slice.
- [x] Remove worker worktree, run `git worktree prune`, and verify cleanup.
      Removed `../opensquilla-refactor-agent-tools`; deleted
      `codex/refactor-tools-mcp-registry-boundary`; `git worktree list`
      verified no tools worker worktree remains.

## Child gate

- `uv run --extra dev ruff check src tests`
- `uv run --extra dev mypy src/opensquilla --show-error-codes`
- `git diff --check`
- `uv run --extra dev pytest`
- gateway smoke through `scripts/refactor_gate.sh`

## Integration gate

- Integration merge: `1b5e36c` (`Merge tools MCP registry boundary`).
- Full integration gate: `scripts/refactor_gate.sh` passed after replacing
  local absolute paths in the dispatch record; ruff passed; mypy passed with no
  issues in 574 source files; whitespace passed; pytest `2813 passed, 6
  skipped, 2 warnings`; gateway smoke start/status/stop passed on port `61461`.
- Cleanup evidence: removed `../opensquilla-refactor-agent-tools`, deleted
  `codex/refactor-tools-mcp-registry-boundary`, ran `git worktree prune`, and
  verified `git worktree list` contained no Tools worker worktree.

## Rollback

- Revert the child commit if registry lifecycle ownership or dispatch failure
  envelopes regress.
- Keep the child branch for integration diagnosis.
- Do not rewrite `main` or unrelated worktrees.

## Completion record

- Child commit:
  - `585489c` (`Refactor tools MCP registry lifecycle boundary`).
- Integration merge:
  - `1b5e36c` (`Merge tools MCP registry boundary`).
- Verification evidence:
  - Red: `uv run --extra dev pytest tests/test_tools/test_registry_lifecycle_boundary.py tests/test_mcp/test_discovery_lifecycle.py::test_tool_registry_lifecycle_owner_can_remove_mcp_registered_surface -q`
    failed as expected with `TypeError: ToolRegistry.register() got an
    unexpected keyword argument 'owner'` and missing dispatch
    visibility-boundary ownership.
  - First green: same command passed with `7 passed in 0.33s`.
  - Focused green:
    `uv run --extra dev pytest tests/test_tools/test_registry_lifecycle_boundary.py tests/test_mcp/test_discovery_lifecycle.py tests/test_tools/test_registry_visibility.py tests/test_tools/test_dispatch_envelope.py -q`
    passed with `30 passed in 1.25s`.
  - Touched ruff:
    `uv run --extra dev ruff check src/opensquilla/tools/registry.py src/opensquilla/tools/dispatch.py src/opensquilla/tools/visibility.py tests/test_tools/test_registry_lifecycle_boundary.py tests/test_mcp/test_discovery_lifecycle.py`
    passed with `All checks passed!`.
  - Touched mypy:
    `uv run --extra dev mypy src/opensquilla/tools/registry.py src/opensquilla/tools/dispatch.py src/opensquilla/tools/visibility.py --show-error-codes`
    passed with `Success: no issues found in 3 source files`.
  - Whitespace: `git diff --check` passed.
  - Child gate: `scripts/refactor_gate.sh` passed; ruff passed; mypy passed
    with no issues in 574 source files; whitespace passed; pytest passed with
    `2811 passed, 8 skipped, 2 warnings in 64.80s`; gateway smoke
    start/status/stop passed on port `60730`.
  - Integration gate: `scripts/refactor_gate.sh` passed after replacing local
    absolute paths in the dispatch record; ruff passed; mypy passed with no
    issues in 574 source files; whitespace passed; pytest passed with
    `2813 passed, 6 skipped, 2 warnings`; gateway smoke start/status/stop
    passed on port `61461`.
- Cleanup evidence:
  - Removed `../opensquilla-refactor-agent-tools`.
  - Deleted `codex/refactor-tools-mcp-registry-boundary`.
  - Ran `git worktree prune`.
  - Verified `git worktree list` contains no Tools worker worktree.
- Residual risk:
  - Low. MCP client lifecycle remains in `opensquilla.mcp.discovery`; this
    slice gives Tools first-class registry ownership/unregister semantics for
    lifecycle cleanup without moving MCP transport code.
- Next recommended slice:
  - Wire MCP discovery/close orchestration to the new registry owner boundary if
    integration wants closed MCP servers to automatically remove their
    registered tool surface.
