# Gateway Startup Locking Spec

Date: 2026-06-27
Status: Draft

## Problem

Desktop first-run startup can leave the bundled gateway unable to boot when the
initial process is interrupted or a second gateway process is started while the
first process is still in schema migration.

The observed failure pattern is:

- A fresh desktop state starts successfully enough to seed the agent workspace.
- The first bundled gateway process does not reach `gateway.started`.
- Later gateway processes fail in `apply_pending()` with yoyo `LockTimeout`.
- The yoyo error reports the same earlier process id for every retry.

The direct failure is a stale or active row in the yoyo migration lock table for
the desktop `sessions.db`. Once this state exists, repeated desktop retries do
not recover by themselves.

## Goals

- Prevent the Electron shell from launching duplicate gateway processes for the
  same desktop profile.
- Keep the gateway pid lock alive for the full server lifetime and release it
  on graceful shutdown.
- Recover from a stale yoyo migration lock only when the recorded pid is proven
  dead.
- Preserve yoyo's safety guarantee when another process may still be migrating.
- Surface actionable startup errors instead of an opaque PyInstaller traceback.

## Non-Goals

- Do not disable yoyo migration locking.
- Do not blindly run `break-lock` on every migration lock timeout.
- Do not change the session database schema as part of this fix.
- Do not make the desktop gateway share a process with Electron.
- Do not broaden gateway binding or auth behavior.

## Existing Surfaces

- Electron launches the bundled gateway in `desktop/electron/src/main.ts` via
  `spawn(...)`.
- Electron waits up to 45 seconds for `/healthz` before reporting that the
  gateway did not become healthy.
- The gateway acquires `GatewayPidLock` before `build_services()` and before
  session database migration.
- `build_services()` runs `apply_pending(session_db_path, migrations_dir)` before
  opening `SessionStorage`.
- `apply_pending()` delegates locking to `with backend.lock():`.
- yoyo implements the migration lock as a row in `yoyo_lock`, keyed by pid, and
  removes it in a `finally` block. A hard process exit can leave the row behind.

## Design

Implement three defensive layers. Each layer addresses a different failure mode
and should be independently testable.

### Layer 1: Electron Single Instance Guard

Add `app.requestSingleInstanceLock()` near Electron app startup, before any
gateway startup work can run.

Expected behavior:

- If the lock cannot be acquired, the new Electron process exits immediately.
- On `second-instance`, the existing main window is restored and focused.
- `bootDesktopApp()` must not run in the second Electron process.
- The existing process remains the only owner allowed to spawn a gateway.

This reduces duplicate gateway starts caused by double-clicking the app,
reopening from Finder, or launching from a DMG while a first run is still in
progress.

### Layer 2: Gateway PID Lock Lifetime

Store the acquired `GatewayPidLock` on the returned `GatewayServer` object and
release it in `GatewayServer.close()`.

Expected behavior:

- `start_gateway_server()` acquires the lock before database migration, as it
  does today.
- The lock object remains strongly referenced for the whole server lifetime.
- `GatewayServer.close()` calls `release()` exactly once, after shutdown work is
  complete enough that a new gateway may safely start.
- `release()` remains idempotent.
- Existing `atexit` and signal cleanup remain as best-effort fallback paths.

This makes normal gateway shutdown explicit instead of relying only on process
exit behavior.

### Layer 3: Conservative Yoyo Stale Lock Recovery

Wrap yoyo `LockTimeout` handling inside `apply_pending()`.

When yoyo reports a lock timeout:

1. Inspect the lock table for recorded pids.
2. If any recorded pid is alive, fail without clearing the lock.
3. If every recorded pid is dead or invalid, delete the yoyo lock rows.
4. Retry migration once.
5. If the retry fails, surface the second failure without another recovery loop.

The liveness check should use platform-appropriate process probing:

- POSIX: `os.kill(pid, 0)`.
- Windows: `OpenProcess` or equivalent existing helper behavior.

The lock recovery path must log structured events:

- `migrator.lock_timeout`
- `migrator.lock_held_by_live_process`
- `migrator.stale_lock_cleared`
- `migrator.stale_lock_retry_failed`

The operator-facing error should explain whether the gateway is still starting,
another gateway is running, or a stale migration lock could not be recovered.

## Safety Rules

- Never clear a yoyo lock held by a live pid.
- Never clear the lock if the database cannot be inspected safely.
- Never retry migration more than once after clearing a stale lock.
- Keep migration failure loud if schema state is uncertain.
- Prefer false negatives over false positives: failing startup is safer than
  corrupting a migration.

## Implementation Notes

Electron:

- Add single-instance handling in `desktop/electron/src/main.ts`.
- Keep the current `startupInProgress` guard for the existing process.
- On a second instance, restore and focus `mainWindow` if it exists.

Gateway:

- Extend `GatewayServer` with an optional pid lock field.
- Assign the acquired lock after `GatewayPidLock.acquire()` succeeds.
- Release the lock in `GatewayServer.close()` in a `finally`-safe path.

Migrator:

- Import yoyo `LockTimeout` explicitly.
- Add a small helper to query `yoyo_lock` rows through the yoyo backend or a
  separate SQLite connection to the same local database.
- Add a small helper to clear the yoyo lock table.
- Keep `:memory:` behavior unchanged.
- Keep normal no-pending migration behavior unchanged.

## Test Plan

### Unit Tests

- `GatewayPidLock` rejects a second lock acquisition for the same state dir while
  the first lock is held.
- `GatewayServer.close()` releases the stored gateway pid lock.
- `apply_pending()` does not clear a yoyo lock for a live pid.
- `apply_pending()` clears a yoyo lock for a dead pid and retries once.
- `apply_pending()` does not enter an unbounded retry loop after stale-lock
  recovery fails.
- `apply_pending()` preserves normal migration success and no-op behavior.

### Electron Tests

- A second Electron instance does not call `bootDesktopApp()`.
- A second Electron instance focuses the existing window.
- Desktop retry does not spawn a new gateway while startup is already in
  progress.

### Integration Tests

- Create a temporary desktop state with `sessions.db` containing a stale
  `yoyo_lock` row. Gateway startup clears it and completes migration.
- Create a temporary desktop state with a live helper process recorded in
  `yoyo_lock`. Gateway startup fails with a clear, non-destructive error.
- Start two gateway processes against the same state dir. The second process
  fails before database migration.

### Manual DMG Smoke

- Install the DMG into `/Applications`.
- Start from a clean desktop user data directory.
- Double-click the app repeatedly during first-run startup.
- Confirm only one gateway process is launched.
- Confirm the app becomes ready or surfaces a clear single startup error.
- Force quit during first-run migration, relaunch, and confirm stale-lock
  recovery works when the recorded pid is no longer alive.

## Acceptance Criteria

- Fresh DMG first run cannot spawn two owned gateway processes from two Electron
  instances.
- A stale yoyo migration lock whose pid is dead is cleared automatically and the
  gateway starts.
- A yoyo migration lock whose pid is alive is never cleared automatically.
- A second gateway using the same desktop state fails before migration work.
- Graceful gateway shutdown removes `gateway.pid` and releases
  `gateway.pid.lock`.
- Failure messages distinguish active startup, already-running gateway, and
  unrecoverable migration lock states.
- CI covers stale-lock recovery and live-lock non-recovery.

## Rollout

- Ship behind normal startup behavior, with no user-facing setting.
- Keep structured logs in the desktop gateway log for post-incident diagnosis.
- Add a short troubleshooting entry once the behavior is implemented.

## Open Questions

- Whether yoyo lock inspection should use yoyo backend APIs only or direct
  SQLite for local file databases.
- Whether desktop startup should extend the first-run health timeout after it
  detects schema migration is active.
- Whether the boot splash should show a distinct "Preparing database" phase.
