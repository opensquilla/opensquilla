# Windows Process Runtime Codex Legacy Parity Design

Date: 2026-06-12

## Goal

Make the Windows `windows_default` process backend behave like the mature
Codex legacy restricted-token execution path for foreground shell commands.

The immediate target is `exec_command` reliability and clear enforcement. A
Windows shell command should run inside the backend sandbox without the old
shell-layer path approval logic, without host fallback, and without needing a
Python wrapper as the default command host.

This is the next step after introducing the unified sandbox operation runtime.
It focuses on the third layer: native process execution under Windows.

## Confirmed Context

OpenSquilla now has a unified operation runtime for sandboxed tools, and
Windows filesystem operations can be routed through a dedicated worker. The
Windows `exec_command` path also no longer runs the old shell path envelope,
active tool mount merge, or trusted-path recovery before dispatching to the
backend.

The remaining failures are in the process backend itself. The current
`windows_default` backend:

- Builds a payload in `windows_default.py`.
- Launches `opensquilla.sandbox.backend.windows_default_runner`.
- Refreshes ACLs for planned roots.
- Creates a restricted token in Python via `ctypes`.
- Launches the child process with `CreateProcessAsUserW` or
  `CreateProcessWithTokenW`.

For Windows shell commands, the current command argv is still:

```text
python.exe -c <OpenSquilla shell host code> <powershell.exe> <command> <cwd> <tmp>
```

This means the sandbox must make all of these usable at once:

- OpenSquilla's Python executable.
- Python standard library and import roots.
- PowerShell.
- System32 utilities and Windows DLL dependencies.
- Workspace and sandbox temp write roots.

Codex's local Windows source contains a more complete legacy path under
`codex-rs/windows-sandbox-rs/src/unified_exec/backends/legacy.rs`. It resolves a
permission profile, prepares ACLs and capability SIDs, creates a restricted
token with the right token flags, spawns the process directly, and returns a
live process session abstraction.

## Non-Goals

- Do not implement Codex's elevated command-runner backend in this phase.
- Do not create sandbox users, DPAPI-protected sandbox credentials, or the full
  elevated setup executable.
- Do not implement WFP/firewall network enforcement in this phase.
- Do not implement ConPTY, resize, or full background process sessions in this
  phase.
- Do not reintroduce AppContainer or AppContainer-specific naming in new code.
- Do not loosen Full Host Access behavior. Host mode remains outside the
  sandbox runtime.

## Design Principle

The backend must own process enforcement.

The shell tool may classify commands, run sensitive-path hard blocks, apply
warnlist approval for risky shell commands, and build a `SandboxRequest`. Once
the request reaches the Windows sandbox backend, process launch, ACL refresh,
runtime roots, stdin/stdout/stderr wiring, timeout, and exit normalization are
backend responsibilities.

The shell layer must not parse command paths to decide Windows filesystem
mounts for sandboxed process execution.

## Architecture

The target Windows foreground process path is:

```text
exec_command
  -> SandboxOperation.process(SandboxRequest)
  -> SandboxOperationRuntime
  -> WindowsDefaultBackend.run(request)
  -> windows_default_runner
  -> WindowsProcessPrep
  -> CreateRestrictedToken
  -> CreateProcessAsUserW/CreateProcessWithTokenW
  -> Job object + pipes
  -> SandboxResult
```

`WindowsProcessPrep` is a logical component. It can start as functions inside
`windows_default_runner.py`, but it should have clear boundaries:

- Resolve runtime roots.
- Resolve writable roots.
- Resolve read-only platform roots.
- Build and apply ACL refresh.
- Build capability SID list.
- Create the restricted token.
- Prepare stdio handles and environment.

If the runner grows too large, these pieces should move into focused modules
under `opensquilla.sandbox.backend.windows_default_*`.

## Runtime Roots

The backend must make shell execution practical without granting broad write
access.

Required write roots:

- Workspace root.
- Workspace cache root.
- Windows sandbox temp root for the current workspace/session.
- Policy-provided read/write mounts.
- Trusted/standard non-sensitive expansion roots approved by policy.

Required read/execute roots:

- Runtime executable directory for the process being launched.
- OpenSquilla/Python runtime roots when the requested command is Python.
- PowerShell executable root when launching PowerShell.
- Windows platform default read roots:
  - `C:\Windows`
  - `C:\Program Files`
  - `C:\Program Files (x86)`
  - `C:\ProgramData`

The platform default roots are read/execute only. They must not become writable
because a command happens to run in Trusted-Sandbox.

Sensitive user paths remain denied unless a later explicit design changes that
policy. Examples include `.ssh`, `.aws`, `.azure`, `.kube`, `.docker`,
`.gnupg`, and `.config\gh`.

## Shell Launch Strategy

The default Windows shell launch should become direct PowerShell:

```text
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command <command>
```

The existing Python shell host should not be the default. It can temporarily
remain as an internal compatibility fallback while tests are migrated, but the
new backend contract should not depend on it.

This reduces the minimum runtime surface for ordinary shell commands. Python
only needs to be included when the requested command actually invokes Python or
when a filesystem worker uses Python intentionally.

## Token Creation

The Windows runner should move closer to Codex's legacy restricted-token model.

Use `CreateRestrictedToken` with:

```text
DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED
```

After token creation, the runner should:

- Set a permissive token default DACL for the logon SID, Everyone, and active
  capability SIDs so child processes can create required pipes and IPC objects.
- Re-enable `SeChangeNotifyPrivilege`, because directory traversal is required
  for ordinary Windows process startup.
- Keep capability SIDs scoped to the resolved allow roots.
- Avoid using the original user SID as a blanket bypass for writes.

The implementation should return structured backend errors when token creation
or process creation fails, including the failing Win32 API and error code.

## Stdio And Exit Semantics

`SandboxRequest.stdin` must be consumed by the Windows runner.

Foreground execution must support:

- Optional stdin bytes.
- Separate stdout and stderr capture.
- Output byte caps.
- Wall timeout.
- Job-object kill-on-close.
- Exit code normalization.

Timeout should return exit code `124`, `timed_out=True`, and a clear stderr
message.

The backend must never fall back to host execution on process creation failure.

## Background Process Scope

`background_process` is out of scope for this phase.

The Windows backend may continue to report that background shell is unsupported.
A later design should add a Codex-like process session abstraction with stdin,
stdout/stderr streaming, terminate, and optional ConPTY support.

## Network Scope

Network enforcement is out of scope for this phase.

If the policy requests `proxy_allowlist`, the Windows process backend should
continue to fail closed or return a clear unsupported-network error. It should
not silently run with host networking while claiming proxy enforcement.

## Data Flow

1. The shell tool receives `command`, `workdir`, optional `stdin`, and timeout.
2. The shell tool performs non-backend checks:
   - safe-bin hard blocks
   - sensitive-path hard blocks
   - warnlist approval for risky commands
3. The shell tool builds `SandboxRequest`.
4. The operation runtime dispatches the process request to
   `WindowsDefaultBackend.run`.
5. The backend builds a Windows payload with argv, cwd, env, run mode, timeout,
   and ACL plan.
6. The helper validates payload shape and unsupported policies.
7. The helper applies ACL refresh.
8. The helper creates the restricted token.
9. The helper launches the requested process with pipes and a job object.
10. The backend returns `SandboxResult`.

## Error Handling

Backend failures should be explicit and actionable:

- Invalid payload: return a validation error.
- Unsupported network policy: return unsupported-network error.
- ACL grant denied for sensitive path: return denied-sensitive-path error.
- ACL grant failed because a target does not exist: include the target path.
- `CreateRestrictedToken` failure: include Win32 code and API name.
- `CreateProcessAsUserW` and `CreateProcessWithTokenW` failure: include both
  attempted APIs and the final Win32 code.
- Timeout: return code `124` and mark the result timed out.

The frontend/user-facing tool envelope can still simplify these messages, but
logs and tests need enough detail to identify the third-layer failure.

## Testing Strategy

Add unit tests before implementation for each backend contract.

Token and payload tests:

- Payload includes `runMode` and rejects values other than `standard` or
  `trusted`.
- Windows runner uses `LUA_TOKEN` and `WRITE_RESTRICTED` flags.
- Windows runner sets token default DACL.
- Windows runner attempts to re-enable `SeChangeNotifyPrivilege`.

Root planning tests:

- Workspace roots are RWX.
- Workspace cache/temp roots are RWX.
- Platform default roots are RX only.
- Runtime Python roots are RX only.
- Sensitive user roots are denied.
- Trusted-Sandbox does not turn RX runtime roots into RWX roots.

Foreground process tests:

- `Write-Output ok` succeeds.
- `cmd /c echo ok` succeeds.
- `where powershell` succeeds or returns a normal command-not-found style exit,
  not `Access is denied`.
- `dir`/`Get-ChildItem` can read workspace.
- Writing under workspace succeeds.
- Writing under runtime bin fails.
- Writing under `C:\ProgramData` fails unless explicitly policy-approved.
- `stdin` reaches the child process.
- Timeout returns `124`.

Regression tests:

- Windows process sandbox does not call legacy shell path access envelopes.
- Windows process sandbox does not merge active tool mounts from the old shell
  approval path.
- Windows process sandbox does not use host fallback.
- Non-Windows backends keep their existing behavior.

## Acceptance Criteria

The phase is complete when:

- `exec_command` in Standard-Sandbox and Trusted-Sandbox runs through
  `windows_default` without old path approval prompts.
- Common shell commands run reliably:
  - PowerShell builtins
  - `cmd /c`
  - `where`
  - Python command invocation when Python is explicitly requested
- Workspace writes succeed.
- Runtime roots remain read/execute only.
- Sensitive user paths do not auto-expand.
- Host fallback is impossible while sandbox mode is active.
- Unsupported Windows network enforcement fails closed.
- The targeted Windows process runtime test suite passes.

## Later Phases

After this phase, the next Codex-like milestones are:

1. Elevated command-runner backend.
2. Sandbox users and setup executable.
3. IPC framed protocol for live process sessions.
4. Background process support with stdin/stdout/stderr streaming.
5. Optional ConPTY support.
6. WFP/proxy network enforcement.
7. Persistent deny-read ACL state and workspace privacy hardening.

Those phases should not be folded into the legacy parity implementation.
