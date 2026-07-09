# Workspace Session Grouping and Sandbox Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group sidebar sessions by explicit project workspace while preserving the current flat default workspace behavior, and make sandbox approval behavior match a Codex-style model where workspace writes and low-risk user-requested operations can proceed without UI friction.

**Architecture:** The gateway owns the workspace contract by deriving stable workspace fields from persisted sandbox run context or explicit agent workspace configuration. The web UI treats workspace groups as display rows inside the Chats section, leaving non-project sessions flat. Sandbox governance uses layered risk signals: protected paths and destructive system changes remain blocked, workspace paths are allowed, and low-risk explicit user operations outside the workspace can be auto-approved.

**Tech Stack:** Python 3.12, Pydantic, OpenSquilla gateway RPC handlers, Vue 3, TypeScript, Vitest, pytest, ruff, mypy.

## Global Constraints

- Do not change Windows or Linux sandbox behavior while touching macOS and shared sandbox paths.
- Do not reintroduce always-visible Approval Required UI for trusted sandbox auto-approval cases.
- Keep main branch web UI styling as the visual baseline.
- Keep sessions with the default OpenSquilla workspace flat in the sidebar.
- Treat explicit project workspaces from CLI cwd or app workspace selection as shared workspace groups.
- Workspace read and write operations must be allowed by default.
- Protected metadata, credential stores, system paths, and high-impact destructive actions must not be auto-approved.
- Low-risk outside-workspace operations can auto-approve only when the user request and operation signals both indicate low risk.

---

## File Structure

- `src/opensquilla/gateway/rpc_sessions.py`: Add workspace metadata to `sessions.list` rows and preserve sandbox run context when branching sessions.
- `src/opensquilla/gateway/session_view.py`: Include optional workspace fields in the stable session view shape.
- `tests/test_gateway/test_rpc_sessions_workspace.py`: Backend tests for workspace metadata, default workspace flattening, and fork inheritance.
- `opensquilla-webui/src/types/rpc.ts`: Add workspace fields to the raw session item type.
- `opensquilla-webui/src/composables/useSessions.ts`: Normalize workspace fields and build workspace group rows in the Chats section.
- `opensquilla-webui/src/components/SidebarConversations.vue`: Render workspace group rows without session actions.
- `opensquilla-webui/src/composables/useSessions.sections.test.ts`: Frontend grouping tests.
- `src/opensquilla/sandbox/governance.py`: Encode low-risk auto-approval decisions using existing governance data structures.
- `src/opensquilla/sandbox/path_validation.py`: Keep workspace access allowed and protected path rejection strict.
- `tests/test_sandbox/test_trusted_sandbox_risk_autoreview.py`: Sandbox risk tests for workspace writes, low-risk outside writes, and hard denials.

---

### Task 1: Backend Workspace Metadata Contract

**Files:**
- Modify: `src/opensquilla/gateway/rpc_sessions.py`
- Modify: `src/opensquilla/gateway/session_view.py`
- Create: `tests/test_gateway/test_rpc_sessions_workspace.py`

**Interfaces:**
- Produces `workspace: str | None`, `workspaceLabel: str | None`, and `workspaceDisplayPath: str | None` on session list items.
- Produces `_session_workspace_metadata(session: Session, config: GatewayConfig) -> dict[str, str]`.
- Consumes `RUN_CONTEXT_ORIGIN_KEY` and `resolve_agent_workspace_dir`.

- [ ] **Step 1: Write backend failing tests**

```python
from pathlib import Path

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc_sessions import _handle_sessions_list
from opensquilla.gateway.session_store import Session
from opensquilla.sandbox.run_context import RUN_CONTEXT_ORIGIN_KEY


def test_sessions_list_groups_explicit_workspace(tmp_path):
    workspace = tmp_path / "project-alpha"
    workspace.mkdir()
    cfg = GatewayConfig(workspace_dir=str(tmp_path / "default-workspace"))
    session = Session(
        session_key="s1",
        title="Build",
        messages=[],
        origin={RUN_CONTEXT_ORIGIN_KEY: {"workspace": str(workspace), "run_mode": "trusted"}},
    )

    response = _handle_sessions_list(_ctx_with_sessions(cfg, [session]), {})

    row = response["sessions"][0]
    assert row["workspace"] == str(workspace)
    assert row["workspaceLabel"] == "project-alpha"
    assert row["workspaceDisplayPath"] == str(workspace)


def test_sessions_list_keeps_default_workspace_flat(tmp_path):
    default_workspace = tmp_path / ".opensquilla" / "workspace"
    default_workspace.mkdir(parents=True)
    cfg = GatewayConfig(workspace_dir=str(default_workspace))
    session = Session(
        session_key="s1",
        title="Default",
        messages=[],
        origin={RUN_CONTEXT_ORIGIN_KEY: {"workspace": str(default_workspace), "run_mode": "trusted"}},
    )

    response = _handle_sessions_list(_ctx_with_sessions(cfg, [session]), {})

    row = response["sessions"][0]
    assert "workspace" not in row
    assert "workspaceLabel" not in row
    assert "workspaceDisplayPath" not in row


def test_session_branch_preserves_workspace_run_context(tmp_path):
    workspace = tmp_path / "project-beta"
    workspace.mkdir()
    manager = _session_manager(tmp_path)
    parent = manager.create_session(
        title="Parent",
        origin={RUN_CONTEXT_ORIGIN_KEY: {"workspace": str(workspace), "run_mode": "trusted"}},
    )

    child = manager.branch(parent.session_key, title="Child")

    assert child.origin[RUN_CONTEXT_ORIGIN_KEY]["workspace"] == str(workspace)
    assert child.origin[RUN_CONTEXT_ORIGIN_KEY]["run_mode"] == "trusted"
```

- [ ] **Step 2: Run backend tests to verify RED**

Run: `uv run pytest tests/test_gateway/test_rpc_sessions_workspace.py -q`

Expected: FAIL because the new test module references workspace fields and helpers that are not implemented.

- [ ] **Step 3: Implement backend workspace metadata**

Add a helper in `src/opensquilla/gateway/rpc_sessions.py`:

```python
def _session_workspace_metadata(session: Session, config: GatewayConfig) -> dict[str, str]:
    origin = session.origin if isinstance(session.origin, dict) else {}
    sandbox_context = origin.get(RUN_CONTEXT_ORIGIN_KEY)
    workspace_value = sandbox_context.get("workspace") if isinstance(sandbox_context, dict) else None
    if not workspace_value:
        agent_id = _effective_agent_id_for_session(session, session.session_key)
        workspace_value = str(resolve_agent_workspace_dir(agent_id, config))
    workspace_path = _normalize_workspace_path(workspace_value)
    if workspace_path is None or _is_default_opensquilla_workspace(workspace_path, config):
        return {}
    path = Path(workspace_path)
    return {
        "workspace": workspace_path,
        "workspaceLabel": path.name or workspace_path,
        "workspaceDisplayPath": workspace_path,
    }
```

Merge that dictionary into every `sessions.list` row after `build_session_view_item(...)`. Add the same optional fields to `build_session_view_item(...)` output in `src/opensquilla/gateway/session_view.py`.

Update `SessionManager.branch(...)` so the child origin copies only the parent sandbox run context:

```python
origin = None
if isinstance(parent.origin, dict):
    sandbox_context = parent.origin.get(RUN_CONTEXT_ORIGIN_KEY)
    if isinstance(sandbox_context, dict):
        origin = {RUN_CONTEXT_ORIGIN_KEY: dict(sandbox_context)}
```

- [ ] **Step 4: Run backend tests to verify GREEN**

Run: `uv run pytest tests/test_gateway/test_rpc_sessions_workspace.py -q`

Expected: PASS.

- [ ] **Step 5: Run adjacent gateway regression tests**

Run: `uv run pytest tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_sandbox/test_rpc_sandbox_access.py -q`

Expected: PASS or a pre-existing unrelated failure must be recorded with the exact failing test name.

- [ ] **Step 6: Commit backend task**

```bash
git add src/opensquilla/gateway/rpc_sessions.py src/opensquilla/gateway/session_view.py tests/test_gateway/test_rpc_sessions_workspace.py
git commit -m "feat: expose workspace metadata for sessions"
```

---

### Task 2: Frontend Workspace Group Rows

**Files:**
- Modify: `opensquilla-webui/src/types/rpc.ts`
- Modify: `opensquilla-webui/src/composables/useSessions.ts`
- Modify: `opensquilla-webui/src/components/SidebarConversations.vue`
- Modify: `opensquilla-webui/src/composables/useSessions.sections.test.ts`

**Interfaces:**
- Consumes backend fields `workspace`, `workspaceLabel`, and `workspaceDisplayPath`.
- Produces `SidebarSectionRow.rowKind: "session" | "workspace"`.
- Produces workspace headers only inside the Chats section.

- [ ] **Step 1: Write frontend failing tests**

Append tests in `opensquilla-webui/src/composables/useSessions.sections.test.ts`:

```typescript
it('groups chat sessions by explicit workspace and keeps default sessions flat', () => {
  const sections = arrangeSidebarSections([
    makeSession({ key: 's1', title: 'Session 1', workspace: '/repo/project1', workspaceLabel: 'project1', updatedAt: '2026-07-09T10:00:00Z' }),
    makeSession({ key: 's2', title: 'Session 2', workspace: '/repo/project1', workspaceLabel: 'project1', updatedAt: '2026-07-09T09:00:00Z' }),
    makeSession({ key: 's3', title: 'Session 3', workspace: '/repo/project2', workspaceLabel: 'project2', updatedAt: '2026-07-09T08:00:00Z' }),
    makeSession({ key: 's4', title: 'Session 4', updatedAt: '2026-07-09T07:00:00Z' }),
  ])

  expect(sections[0].rows.map((row) => [row.rowKind, row.key, row.depth])).toEqual([
    ['workspace', 'workspace:/repo/project1', 0],
    ['session', 's1', 1],
    ['session', 's2', 1],
    ['workspace', 'workspace:/repo/project2', 0],
    ['session', 's3', 1],
    ['session', 's4', 0],
  ])
})

it('nests subagent rows one level deeper inside their workspace group', () => {
  const sections = arrangeSidebarSections([
    makeSession({ key: 'parent', title: 'Parent', workspace: '/repo/project', workspaceLabel: 'project', updatedAt: '2026-07-09T10:00:00Z' }),
    makeSession({ key: 'child', title: 'Child', workspace: '/repo/project', workspaceLabel: 'project', parentSessionKey: 'parent', updatedAt: '2026-07-09T10:01:00Z' }),
  ])

  expect(sections[0].rows.map((row) => [row.rowKind, row.key, row.depth])).toEqual([
    ['workspace', 'workspace:/repo/project', 0],
    ['session', 'parent', 1],
    ['session', 'child', 2],
  ])
})
```

- [ ] **Step 2: Run frontend tests to verify RED**

Run: `cd opensquilla-webui && npm test -- useSessions.sections.test.ts --runInBand`

Expected: FAIL because rows do not have `rowKind` and workspace grouping is not implemented.

- [ ] **Step 3: Implement workspace normalization and grouping**

Add workspace fields to `RawSessionItem`, `SessionItem`, and `SidebarSectionRow`. In `normalizeSessionItem`, copy only non-empty string fields:

```typescript
const workspace = typeof raw.workspace === 'string' && raw.workspace.length > 0 ? raw.workspace : undefined
const workspaceLabel = typeof raw.workspaceLabel === 'string' && raw.workspaceLabel.length > 0 ? raw.workspaceLabel : undefined
const workspaceDisplayPath = typeof raw.workspaceDisplayPath === 'string' && raw.workspaceDisplayPath.length > 0 ? raw.workspaceDisplayPath : undefined
```

In `arrangeSidebarSections`, pass Chats rows through `arrangeWorkspaceRows(...)` after `arrangeSessionLedger(...)`:

```typescript
function arrangeWorkspaceRows(entries: LedgerEntry[]): SidebarSectionRow[] {
  const buckets = new Map<string, { title: string; displayPath?: string; rows: SidebarSectionRow[]; updatedAt: string }>()
  const topLevel: Array<{ kind: 'workspace'; key: string; updatedAt: string } | { kind: 'row'; row: SidebarSectionRow; updatedAt: string }> = []
  for (const entry of entries) {
    const row = toSidebarSectionRow(entry.item, entry.depth)
    row.rowKind = 'session'
    if (!entry.item.workspace) {
      topLevel.push({ kind: 'row', row, updatedAt: row.updatedAt || '' })
      continue
    }
    const bucketKey = entry.item.workspace
    const bucket = buckets.get(bucketKey) ?? { title: entry.item.workspaceLabel || bucketKey, displayPath: entry.item.workspaceDisplayPath, rows: [], updatedAt: '' }
    bucket.rows.push({ ...row, depth: row.depth + 1 })
    bucket.updatedAt = maxTimestamp(bucket.updatedAt, row.updatedAt || '')
    if (!buckets.has(bucketKey)) topLevel.push({ kind: 'workspace', key: bucketKey, updatedAt: bucket.updatedAt })
    buckets.set(bucketKey, bucket)
  }
  return materializeWorkspaceRows(topLevel, buckets)
}
```

Render `row.rowKind === "workspace"` as a non-clickable workspace label in `SidebarConversations.vue`, and keep session rows unchanged.

- [ ] **Step 4: Run frontend tests to verify GREEN**

Run: `cd opensquilla-webui && npm test -- useSessions.sections.test.ts --runInBand`

Expected: PASS.

- [ ] **Step 5: Run adjacent frontend regression tests**

Run: `cd opensquilla-webui && npm test -- ChatComposerSettings.test.ts useSessions.sections.test.ts --runInBand`

Expected: PASS.

- [ ] **Step 6: Commit frontend task**

```bash
git add opensquilla-webui/src/types/rpc.ts opensquilla-webui/src/composables/useSessions.ts opensquilla-webui/src/components/SidebarConversations.vue opensquilla-webui/src/composables/useSessions.sections.test.ts
git commit -m "feat: group sessions by workspace"
```

---

### Task 3: Sandbox Workspace and Low-Risk Auto-Approval

**Files:**
- Modify: `src/opensquilla/sandbox/governance.py`
- Modify: `src/opensquilla/sandbox/path_validation.py`
- Create: `tests/test_sandbox/test_trusted_sandbox_risk_autoreview.py`

**Interfaces:**
- Consumes existing sandbox decision objects and path classification helpers.
- Produces deterministic outcomes for workspace writes, low-risk user-requested outside writes, and hard-denied protected paths.

- [ ] **Step 1: Write sandbox failing tests**

```python
from opensquilla.sandbox.governance import evaluate_sandbox_action


def test_trusted_workspace_write_is_allowed_without_approval(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    target = workspace / "note.txt"

    decision = evaluate_sandbox_action(
        run_mode="trusted",
        tool_name="write_file",
        target_path=str(target),
        workspace=str(workspace),
        user_requested=True,
        destructive=False,
    )

    assert decision.status == "allow"
    assert decision.requires_approval is False


def test_low_risk_user_requested_outside_workspace_write_auto_approves(tmp_path):
    workspace = tmp_path / "project"
    downloads = tmp_path / "Downloads"
    workspace.mkdir()
    downloads.mkdir()
    target = downloads / "mac-sandbox.png"

    decision = evaluate_sandbox_action(
        run_mode="trusted",
        tool_name="delete_file",
        target_path=str(target),
        workspace=str(workspace),
        user_requested=True,
        destructive=False,
    )

    assert decision.status == "allow"
    assert decision.requires_approval is False
    assert decision.auto_approved is True


def test_system_or_metadata_path_is_not_auto_approved_even_when_user_requested(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()

    decision = evaluate_sandbox_action(
        run_mode="trusted",
        tool_name="write_file",
        target_path="/etc/sudoers",
        workspace=str(workspace),
        user_requested=True,
        destructive=False,
    )

    assert decision.status in {"deny", "approval_required"}
    assert decision.auto_approved is False
```

- [ ] **Step 2: Run sandbox tests to verify RED**

Run: `uv run pytest tests/test_sandbox/test_trusted_sandbox_risk_autoreview.py -q`

Expected: FAIL because `evaluate_sandbox_action(...)` does not expose the requested Codex-style risk contract yet.

- [ ] **Step 3: Implement layered risk evaluation**

Add or adapt a focused helper in `src/opensquilla/sandbox/governance.py`:

```python
def evaluate_sandbox_action(
    *,
    run_mode: str,
    tool_name: str,
    target_path: str,
    workspace: str | None,
    user_requested: bool,
    destructive: bool,
) -> SandboxActionDecision:
    classification = classify_path_for_sandbox(target_path, workspace=workspace)
    if classification.protected:
        return SandboxActionDecision.deny(reason=classification.reason)
    if classification.within_workspace:
        return SandboxActionDecision.allow(auto_approved=False)
    if run_mode == "trusted" and user_requested and not destructive and classification.low_risk_user_area:
        return SandboxActionDecision.allow(auto_approved=True)
    return SandboxActionDecision.require_approval(reason="outside_workspace")
```

Keep existing approval records and denial payload fields intact so current UI and CLI clients continue to understand decisions.

- [ ] **Step 4: Run sandbox tests to verify GREEN**

Run: `uv run pytest tests/test_sandbox/test_trusted_sandbox_risk_autoreview.py -q`

Expected: PASS.

- [ ] **Step 5: Run existing sandbox regression tests**

Run: `uv run pytest tests/test_sandbox/test_trusted_sandbox_execution.py tests/test_sandbox/test_path_access.py tests/test_sandbox/test_rpc_sandbox_access.py -q`

Expected: PASS.

- [ ] **Step 6: Commit sandbox task**

```bash
git add src/opensquilla/sandbox/governance.py src/opensquilla/sandbox/path_validation.py tests/test_sandbox/test_trusted_sandbox_risk_autoreview.py
git commit -m "feat: auto-approve low-risk trusted sandbox actions"
```

---

### Task 4: End-to-End Verification, Rebase, Push, and PR

**Files:**
- Modify only files changed by Tasks 1-3.

**Interfaces:**
- Consumes all behavior from Tasks 1-3.
- Produces a pushed branch and PR against `upstream/main`.

- [ ] **Step 1: Run focused verification**

Run:

```bash
uv run pytest tests/test_gateway/test_rpc_sessions_workspace.py tests/test_sandbox/test_trusted_sandbox_risk_autoreview.py -q
cd opensquilla-webui && npm test -- useSessions.sections.test.ts ChatComposerSettings.test.ts --runInBand
```

Expected: PASS.

- [ ] **Step 2: Run repository checks**

Run:

```bash
uv run ruff check src tests
uv run mypy src/opensquilla --show-error-codes
uv run pytest tests/test_gateway tests/test_sandbox -q
cd opensquilla-webui && npm test -- --runInBand
```

Expected: PASS. If a check fails, record the exact test or diagnostic and fix it before continuing.

- [ ] **Step 3: Fetch and update local main from upstream**

```bash
git fetch upstream main
git switch main
git reset --hard upstream/main
git push origin main
```

Expected: local `main` equals `upstream/main`, and `origin/main` receives the same commit.

- [ ] **Step 4: Rebase feature branch onto upstream main**

```bash
git switch fix/trusted-sandbox-delete-soft-landing
git rebase main
```

Expected: branch replays without conflict. If a conflict appears, resolve by keeping the sandbox behavior from this branch and the visual styling baseline from main.

- [ ] **Step 5: Re-run verification after rebase**

Run:

```bash
uv run ruff check src tests
uv run mypy src/opensquilla --show-error-codes
uv run pytest tests/test_gateway tests/test_sandbox -q
cd opensquilla-webui && npm test -- --runInBand
```

Expected: PASS.

- [ ] **Step 6: Push branch and open or update PR**

```bash
git push --force-with-lease origin fix/trusted-sandbox-delete-soft-landing
gh pr view --head Liu-RK:fix/trusted-sandbox-delete-soft-landing --repo opensquilla/opensquilla --json number,url,state
gh pr create --repo opensquilla/opensquilla --base main --head Liu-RK:fix/trusted-sandbox-delete-soft-landing --title "Add trusted sandbox workspace grouping and risk handling" --body-file /tmp/opensquilla-pr-body.md
```

Expected: if the PR already exists, use the existing PR URL; if it does not exist, create it.

---

## Self-Review

Spec coverage:
- Backend session workspace metadata is covered by Task 1.
- Default OpenSquilla workspace remaining flat is covered by Task 1 and Task 2.
- Shared workspace grouping in the left sidebar is covered by Task 2.
- Workspace read and write allowance is covered by Task 3.
- Low-risk outside-workspace auto-approval is covered by Task 3.
- Protected path and high-impact denial behavior is covered by Task 3.
- Rebase, push, and PR creation are covered by Task 4.

Placeholder scan:
- The plan contains no placeholder terms requiring later invention.

Type consistency:
- Backend fields use `workspace`, `workspaceLabel`, and `workspaceDisplayPath` in all tasks.
- Frontend rows use `rowKind: "session" | "workspace"` in all tasks.
- Sandbox decision fields use `status`, `requires_approval`, and `auto_approved` in all tests and implementation notes.
