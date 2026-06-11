# Windows Restricted-Token Backend Design

Date: 2026-06-11

## Goal

Replace the current Windows AppContainer sandbox path with a working Windows
restricted-token backend, while preserving the existing Linux, macOS, noop,
policy, and run-mode behavior as much as possible.

This is Phase 1 of a longer Codex-like Windows sandbox direction. Phase 1 must
remove AppContainer from the active implementation and make Windows shell
commands run through a restricted token instead of the current
AppContainer/Python-helper launch path.

## Confirmed Context

The current upstream `opensquilla/opensquilla.git` `dev` branch does not contain
a Windows restricted-token backend. Its sandbox backends are Linux bubblewrap,
macOS seatbelt, and noop. On upstream `dev`, Windows `backend=auto` disables the
sandbox runtime and resolves to noop.

The restricted-token path was introduced on the Windows sandbox branch in
commit `5f8ee54e` as a fail-closed skeleton. Later branch commits added the
AppContainer backend, AppContainer identity, AppContainer ACL grants, and
AppContainer-specific network boundary work.

The current branch still has a `windows_restricted_token` backend, but its
helper does not launch the requested payload. It validates input and exits with
`windows_restricted_token helper cannot enforce policy on this host`.

## Non-Goals

- Do not port the full Codex Windows setup/provisioning system in Phase 1.
- Do not implement persistent per-workspace capability SID setup in Phase 1.
- Do not change Linux bubblewrap, macOS seatbelt, noop, or shared sandbox policy
  semantics except where Windows-specific references must be removed.
- Do not claim Windows proxy allowlist networking is enforced until there is a
  real Windows network boundary proving it.

## Architecture

Windows will have one real backend:

```text
WindowsRestrictedTokenBackend
  -> windows_restricted_token_helper
  -> CreateRestrictedToken
  -> Job object with kill-on-close
  -> CreateProcessAsUserW or CreateProcessWithTokenW
  -> stdout/stderr/exit-code/timeout normalization
```

The backend remains a Python adapter that spawns a fresh helper interpreter.
The helper owns all Windows-only process-boundary work.

`backend=auto` selection becomes:

```text
Linux   -> bubblewrap when available
macOS   -> seatbelt when available
Windows -> windows_restricted_token when available
Other   -> existing unavailable/noop behavior
```

The explicit config backend literal `windows_appcontainer` is removed.
The explicit config backend literal `windows_restricted_token` remains.

## AppContainer Removal

Remove active AppContainer implementation and tests:

- `windows_appcontainer.py`
- `windows_appcontainer_helper.py`
- AppContainer profile creation, identity preparation, and launch primitives
- AppContainer SID-specific ACL grant helpers
- AppContainer-specific network boundary files and service request models
- AppContainer-specific WFP/package SID policy code
- tests whose purpose is AppContainer identity, launch, WFP package SID, or
  service broker/client behavior

After the removal, searching the active source and tests for `AppContainer`,
`appcontainer`, and `windows_appcontainer` should return no production path.
Historical docs or migration notes may mention the term only when explaining
the removal.

## Restricted Token Helper

The helper must become executable instead of a fail-closed skeleton.

Responsibilities:

- Parse and validate the JSON payload from `WindowsRestrictedTokenBackend`.
- Reject non-Windows hosts.
- Reject unsupported policy combinations before launch.
- Create a restricted primary token from the current process token.
- Put the child process in a job object configured to kill descendants when the
  helper exits.
- Launch the requested argv with the requested cwd and allowed environment.
- Capture stdout/stderr through pipes.
- Enforce wall timeout and return exit code `124` on timeout.

The first implementation can use a minimal Windows restricted-token model:

```text
CreateRestrictedToken(DISABLE_MAX_PRIVILEGE plus write restriction where usable)
Job object kill-on-close
CreateProcessAsUserW or CreateProcessWithTokenW
```

If `CreateProcessAsUserW` requires privileges unavailable in a normal user
process, the implementation should fall back to `CreateProcessWithTokenW` or a
documented supported API path rather than silently launching unsandboxed.

## Filesystem Policy

Restricted tokens alone are not a complete sandbox. Phase 1 must include a
filesystem enforcement story before marking the backend available.

Minimum acceptable Phase 1 behavior:

- Workspace rw mounts are accessible to the restricted child.
- Required read-only mounts are readable/executable where needed.
- The command cwd is accessible.
- The helper fails closed when a required mount cannot be granted or verified.
- Writes outside allowed rw roots are blocked by token/ACL behavior or by an
  explicit preflight rule that refuses unsupported policy shapes.

Phase 1 may use a single session-level restricting SID instead of the full
Codex persistent per-workspace SID model. Persistent per-workspace and
per-write-root SIDs are deferred to Phase 2.

The implementation must avoid per-command recursive grants over large runtime
directories when possible. Runtime/tool directories should be read-only and
either preflighted cheaply or granted in a cached/idempotent way.

## Network Policy

Phase 1 must not pretend to enforce Windows proxy allowlist networking.

Behavior:

- `network=none` is supported only when the helper can prevent or confidently
  reject network access for the child. If this cannot be guaranteed in Phase 1,
  the backend must explicitly document and fail closed for network-sensitive
  policies.
- `network=host` is allowed only if policy generation explicitly requests host
  networking for an approved/full-access action.
- `network=proxy_allowlist` fails closed unless a Windows network boundary is
  implemented and smoke-tested.

Existing managed proxy setup can remain for non-Windows platforms and for
future Windows work, but AppContainer package-SID WFP logic is removed in this
phase.

## Shell Compatibility

The Windows shell compatibility layer in `exec_command` may continue to wrap
PowerShell through the existing Python shell host during Phase 1 if that is the
smallest safe change. However, the process boundary below it must be
restricted-token, not AppContainer.

The runtime Python directory timeout must be addressed by removing AppContainer
per-command ACL grants. If the Python shell host remains, its runtime directory
must be handled as a read-only dependency of the restricted-token launch path
without recursive AppContainer ACL churn.

Direct PowerShell launch is a possible follow-up optimization after Phase 1.

## Support Probe

`probe_windows_sandbox_support()` should be simplified around restricted-token
readiness:

- `is_windows`
- `ctypes_available`
- `restricted_token_enforced`
- optional future network readiness fields

Remove `appcontainer_enforced` and `appcontainer_available` from active
selection logic. Tests may retain compatibility shims only if needed during the
transition, but the public backend selection should not prefer or expose
AppContainer.

`WindowsRestrictedTokenBackend.available()` should require only the process and
filesystem boundaries needed for the policies it claims to run. It should not
require AppContainer WFP or broker readiness.

## Tests

Update or add focused tests:

- Windows auto selects `windows_restricted_token` when available.
- Explicit `windows_appcontainer` config is rejected by validation.
- Explicit `windows_restricted_token` still fails closed when unavailable.
- Restricted-token backend serializes only allowed environment variables.
- Helper rejects malformed payloads and non-Windows hosts.
- Helper does not fall back to unsandboxed `subprocess.run`.
- Helper timeout kills the child/job and returns `124`.
- Native smoke test, Windows-only and opt-in, proves:
  - a simple command runs;
  - workspace write succeeds;
  - write outside allowed roots is denied or policy is refused before launch.
- Linux and macOS backend selection tests continue to pass unchanged in
  behavior.

Remove or rewrite tests that assert AppContainer is selected first, AppContainer
SIDs are required, AppContainer loopback exemptions exist, or WFP rules are
bound to package SIDs.

## Migration Risk

The highest-risk area is filesystem enforcement. A restricted token without
correct restricting SIDs and ACLs is not enough. The implementation must prefer
fail-closed behavior over launching a child process with unclear write access.

The second risk is network enforcement. Since the current WFP path is
AppContainer package-SID based, removing AppContainer means Windows
`proxy_allowlist` cannot be considered enforced until a replacement exists.

The third risk is compatibility with shell tooling that expects Python, py, tmp
mapping, or nested PowerShell behavior. Phase 1 should preserve the existing
shell compatibility layer unless replacing it is necessary for correctness.

## Acceptance Criteria

- No active backend selection path references `windows_appcontainer`.
- Windows `backend=auto` resolves to `windows_restricted_token` when the
  restricted-token backend is available.
- AppContainer-specific production modules are removed or reduced to migration
  notes only.
- The restricted-token backend can launch a simple command on native Windows.
- The backend does not launch commands unsandboxed when policy enforcement is
  unavailable.
- Existing Linux/macOS/noop sandbox tests keep their behavior.
- Windows native smoke tests document any Phase 1 policy limits clearly.

## Follow-Up Phases

Phase 2 should add a Codex-like persistent setup model:

- persisted sandbox SIDs;
- per-workspace and per-write-root SIDs;
- idempotent ACL refresh;
- diagnostics for missing ACEs;
- cached/pre-authorized runtime read-only roots.

Phase 3 should add a replacement Windows network boundary:

- no-network enforcement;
- proxy allowlist enforcement;
- elevated setup if needed;
- cleanup and smoke tests for network rules.
