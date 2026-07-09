# Remove Obsolete Approval Policy UI

## Context

The standalone `/approvals` destination was retired in PR #503. Pending
approvals now surface inside chat through `ApprovalCard`, with app-wide badges
and session routing for blocked work. The old page's three-state global mode
selector (`prompt`, `auto-approve`, `auto-deny`) was moved to Settings → Safety.

Current runtime behavior no longer matches that selector's presentation:

- Core sandbox approval paths enqueue requests directly and do not consult the
  global three-state mode.
- Execution posture is controlled by the `standard`, `trusted`, and `full` run
  modes.
- The global approval mode is process-local and returns to `prompt` when the
  gateway restarts.
- The settings request sends only `mode`, which also replaces externally
  configured allow/deny patterns with empty lists.

The UI copy therefore overstates the selector's authority by claiming that it
controls all tool executions across agents and channels.

## Decision

Remove the obsolete three-state selector from the Web UI while preserving all
active approval and sandbox contracts.

This is a frontend retirement, not a backend approval migration. The backend
REST/RPC mode contract remains available for external compatibility until a
separate deprecation decision is made.

## Alternatives Considered

### 1. Keep the selector unchanged

Rejected because it exposes a non-persistent compatibility state as though it
were the authoritative safety control.

### 2. Rewire every approval path to consume the selector

Rejected because it would reintroduce a second authorization model beside run
modes and would materially change sandbox behavior.

### 3. Remove only the frontend selector and retain backend compatibility

Selected because it removes misleading UI without weakening approval gates or
breaking external RPC consumers.

## Scope

### Remove

- The Settings → Safety rail entry and panel rendering branch.
- `SettingsSafetyPanel.vue`.
- The unreachable legacy `ApprovalsView.vue` source file.
- Locale strings, icons, comments, and tests that are used only by those
  retired surfaces.
- Generated Web UI assets made stale by the source deletion.

### Preserve

- `/approvals` redirect compatibility to `/sessions`.
- Chat `ApprovalCard` and interrupt resolution behavior.
- App-wide pending-approval badges, push subscriptions, and session routing.
- The approval queue, HTTP endpoints, RPC methods, scopes, and backend tests.
- `standard`, `trusted`, and `full` run-mode controls.
- Sandbox allow/deny decisions and approval gates.

## User Experience

The Settings rail no longer shows an otherwise empty Safety destination.
Users choose execution posture from the chat run-mode control and answer real
approval requests inline in the affected conversation. Existing `/approvals`
bookmarks continue to land on Sessions.

## Testing

- Add or update a focused settings-catalog test so the retired `safety` section
  fails before the source removal and passes afterward.
- Keep the route contract test proving `/approvals` is excluded from navigation
  and redirects to `/sessions`.
- Run affected Web UI unit tests and architecture/type checks.
- Run focused backend approval and sandbox tests to prove the preserved runtime
  contracts remain unchanged.
- Rebuild and verify the checked-in Web UI static distribution.

## Delivery

Ship the source cleanup, focused tests, regenerated static assets, and this
design/implementation documentation in one pull request. Do not remove or
deprecate backend approval APIs in this change.
