# Windows Default Sandbox Design

Date: 2026-06-11

## Summary

OpenSquilla needs one clear Windows sandbox direction. The current
`windows_restricted_token` path was useful as a first exploration, but it is not
a successful product backend and keeping it as a separate concept would pollute
future development. This design replaces the old Windows backend semantics with
a single `windows_default` backend modeled after the Codex Windows sandbox
architecture.

The first implementation phase focuses on filesystem, execution, cache, and ACL
refresh behavior. It requires an administrator setup step, uses restricted and
capability tokens internally, grants runtime directories read/execute access,
refreshes writable roots before each command, and redirects language tool caches
to workspace-local cache directories by default.

Network enforcement is intentionally left for a later phase. The filesystem
design reserves setup, identity, and payload boundaries that can later host WFP
or another Windows network boundary without introducing a second Windows
sandbox backend.

## Decisions

- Windows has one sandbox backend concept: `windows_default`.
- The old `windows_restricted_token` backend is removed as an implementation
  and product concept.
- AppContainer remains deleted and must not return as a parallel backend.
- Full Host Access is the default host execution mode and does not enter the
  Windows sandbox.
- Standard-Sandbox and Trusted-Sandbox use `windows_default` on Windows.
- The first `windows_default` phase requires an administrator setup.
- Workspace-local caches are the default for language package managers and
  build tools.
- WFP and strong network isolation are not in the first phase.

## Goals

- Make Standard-Sandbox and Trusted-Sandbox usable for ordinary Windows
  development workflows.
- Ensure runtime binaries such as Python, PowerShell, Git, Node, compilers, and
  OpenSquilla helpers are executable inside the sandbox through explicit RX
  grants.
- Ensure workspace development directories can create and use virtual
  environments, package directories, build outputs, and caches.
- Support many language ecosystems through generic writable-root and cache-env
  handling instead of pip-only special cases.
- Refresh ACLs before every sandboxed command so current policy, mode, and
  cache roots are reflected in the process boundary.
- Keep Trusted-Sandbox easier to use than Standard-Sandbox without making it
  equivalent to Full Host Access.
- Fail closed for Standard-Sandbox and Trusted-Sandbox when the Windows backend
  cannot enforce required filesystem behavior.
- Preserve Linux, macOS, and Full Host Access behavior.

## Non-Goals

- Do not implement Windows WFP, brokered egress, or strong network isolation in
  this phase.
- Do not keep `windows_restricted_token` as a second implementation path.
- Do not use AppContainer.
- Do not make runtime directories writable by sandboxed commands.
- Do not persist broad global write access for package-manager caches by
  default.
- Do not silently fall back to host execution from Standard-Sandbox or
  Trusted-Sandbox.

## Product Modes

OpenSquilla has three product modes. The Windows backend must use these terms,
not Codex's `workspace-write` or `read-only` vocabulary.

```text
Full Host Access
  Default mode.
  Executes on the host as the real user.
  Does not use windows_default.
  Does not apply ACL refresh or restricted/capability tokens.

Standard-Sandbox
  Uses windows_default on Windows.
  Workspace roots are RWX.
  Runtime/read roots are RX.
  Required and policy grants are automatic.
  Workspace-external expansion grants require user approval.
  Sensitive paths are denied.

Trusted-Sandbox
  Uses windows_default on Windows.
  Workspace roots are RWX.
  Runtime/read roots are RX.
  Required and policy grants are automatic.
  Workspace-external non-sensitive expansion grants are automatic.
  Sensitive paths are denied.
```

Full Host Access is the only host execution path. Standard-Sandbox and
Trusted-Sandbox must not degrade to host execution without an explicit mode
change or approval path defined outside this design.

## Architecture

The implementation should create a new Windows backend family and remove the
old backend semantics.

```text
windows_default.py
  Backend adapter and request orchestration.

windows_default_setup.py or native setup helper
  Administrator setup.
  Creates sandbox users/group or equivalent identities.
  Writes setup marker and protected secrets.
  Initializes sandbox state directories and runtime/bin ACLs.

windows_default_runner.py or native runner helper
  Per-command ACL refresh.
  Restricted/capability token creation.
  Process launch, job lifetime, stdio capture, and timeout handling.

windows_acl.py
  ACL planning and application helpers.

windows_capability.py
  Capability SID persistence, per-root SID selection, and token inputs.

windows_roots.py
  Runtime roots, read roots, write roots, expansion roots, and sensitive-path
  classification.

windows_cache_env.py
  Workspace cache directory creation and language tool environment injection.
```

The Python adapter may call a native helper for Windows token, ACL, user, and
process APIs. The final implementation can choose Python `ctypes`, Rust, or a
small helper executable, but the public backend concept remains
`windows_default`.

`backend=auto` should resolve as:

```text
Linux Standard/Trusted   -> bubblewrap when available
macOS Standard/Trusted   -> seatbelt when available
Windows Standard/Trusted -> windows_default when setup/support is available
Full Host Access         -> host/noop path
```

An explicit `backend="windows_restricted_token"` should not select an old
execution path. The preferred behavior is a configuration error that tells the
operator to use `windows_default` or `auto`.

## Directory Model

OpenSquilla-owned state:

```text
%USERPROFILE%\.opensquilla\
  sandbox\
    setup_marker.json
    cap_sids.json
    logs\
  sandbox-secrets\
    users.json or protected secrets
  sandbox-bin\
    setup helper
    runner helper
    command helper
```

The `sandbox` and `sandbox-bin` directories are controlled by OpenSquilla.
Sandboxed commands must not receive ordinary workspace write capability for
secrets, setup markers, user credentials, or protected state. `sandbox-bin`
receives RX for sandbox execution and RW for the real user or setup helper.

Runtime and read roots:

```text
current Python executable directory
current Python Scripts directory when present
OpenSquilla package/runtime directories
OpenSquilla sandbox-bin
C:\Windows
C:\Program Files
C:\Program Files (x86)
C:\ProgramData
explicit read roots
```

These roots receive RX for the sandbox identity or read capability. They do not
receive RWX.

Workspace write roots:

```text
workspace root
explicit writable roots
workspace\.opensquilla-cache
approved or trusted expansion roots
```

Workspace and approved writable roots receive RWX with inheritance for the
current command's capability SID. This makes ordinary subdirectories such as
`.venv`, `node_modules`, `target`, `build`, `dist`, and language package
directories work through inherited access rather than through per-tool grants.

Workspace-local cache layout:

```text
<workspace>\.opensquilla-cache\
  temp\
  pip\
  uv\
  npm\
  pnpm\
  yarn\
  cargo\
  rustup\
  go\
  maven\
  gradle\
  nuget\
  dotnet\
  composer\
  ruby\
```

## Permission Model

`windows_default` uses restricted and capability tokens internally.

- Runtime/read roots receive RX.
- Workspace write roots receive RWX with inheritance.
- Per-root capability SIDs should be used for writable roots so stale ACLs from
  one run do not expand another run's token.
- The command token contains only the capability SIDs required for the current
  command.
- Sensitive OpenSquilla state, credentials, runtime bins, system paths, and
  protected user credential directories never receive automatic write grants.

Suggested sensitive path families:

```text
%USERPROFILE%\.ssh
%USERPROFILE%\.aws
%USERPROFILE%\.azure
%USERPROFILE%\.kube
%USERPROFILE%\.docker
%USERPROFILE%\.gnupg
%USERPROFILE%\.config\gh
%USERPROFILE%\.opensquilla\sandbox
%USERPROFILE%\.opensquilla\sandbox-secrets
C:\Windows
C:\Program Files
C:\Program Files (x86)
```

This list can grow, but it should be centralized in `windows_roots.py` or an
equivalent module so Standard-Sandbox, Trusted-Sandbox, approvals, tests, and
diagnostics agree.

## ACL Refresh Decisions

ACL refresh is a policy-driven operation. The helper must not freely grant
permissions without the main runtime classifying the change.

```text
Required grants
  Runtime RX, helper RX, workspace RWX, workspace cache RWX, TEMP/TMP RWX.

Policy grants
  Paths already allowed by current user/config policy.

Expansion grants
  New write needs discovered from command profiling, cache redirection, or
  retry/diagnostic flow that are not already in required or policy grants.
```

Decision matrix:

```text
Full Host Access
  No ACL refresh.
  Host execution.

Standard-Sandbox
  Required grants: auto
  Policy grants: auto
  Expansion grants: ask
  Sensitive paths: deny

Trusted-Sandbox
  Required grants: auto
  Policy grants: auto
  Non-sensitive expansion grants: auto
  Sensitive paths: deny
```

Typical Trusted-Sandbox non-sensitive expansion roots include package and build
caches such as:

```text
%USERPROFILE%\.cache\pip
%APPDATA%\npm-cache
%USERPROFILE%\.cargo
%USERPROFILE%\.gradle
%USERPROFILE%\.m2
%LOCALAPPDATA%\NuGet
```

The first implementation should still prefer workspace-local cache redirection.
Workspace-external expansion grants are a compatibility path for tools that
ignore or override cache environment variables.

## Command Flow

Every Windows Standard-Sandbox or Trusted-Sandbox command follows one path:

```text
1. Resolve request
   argv, cwd, env, run mode, policy, workspace roots.

2. Build cache environment
   Create workspace .opensquilla-cache when workspace is writable.
   Inject generic package-manager and build-cache environment variables.

3. Compute roots
   read_roots, write_roots, deny_write paths, sensitive classifications.

4. Build ACL refresh plan
   Classify required, policy, and expansion grants.
   Apply Standard/Trusted decisions.
   Request approval only when the mode requires it.

5. Ensure setup
   If setup is missing or stale, run administrator setup.
   If setup is cancelled or fails, fail closed.

6. Refresh ACLs
   Apply RX and RWX grants and deny-write entries.
   Validate failures as structured backend errors.

7. Create token
   Include only current command capability SIDs.

8. Spawn command
   Use CreateProcessAsUserW or equivalent.
   Attach job object and stdio capture.
   Enforce timeout cleanup.

9. Return result
   stdout, stderr, exit code, backend name, policy summary, diagnostics.
```

First phase does not implement runtime dynamic ACL interception. If a tool
fails with `ACCESS_DENIED`, the runtime may classify the failure and suggest or
request a retry, but the sandbox boundary remains fail-closed.

## Cache Environment

Cache redirection is generic. It is not the security boundary, but it reduces
unnecessary workspace-external writes and makes installs predictable.

When workspace cache is available:

```text
TEMP=<workspace>\.opensquilla-cache\temp
TMP=<workspace>\.opensquilla-cache\temp

PIP_CACHE_DIR=<workspace>\.opensquilla-cache\pip
UV_CACHE_DIR=<workspace>\.opensquilla-cache\uv

npm_config_cache=<workspace>\.opensquilla-cache\npm
PNPM_HOME=<workspace>\.opensquilla-cache\pnpm\home
PNPM_STORE_DIR=<workspace>\.opensquilla-cache\pnpm\store
YARN_CACHE_FOLDER=<workspace>\.opensquilla-cache\yarn

CARGO_HOME=<workspace>\.opensquilla-cache\cargo
RUSTUP_HOME=<workspace>\.opensquilla-cache\rustup

GOMODCACHE=<workspace>\.opensquilla-cache\go\pkg\mod
GOCACHE=<workspace>\.opensquilla-cache\go\build

MAVEN_USER_HOME=<workspace>\.opensquilla-cache\maven
GRADLE_USER_HOME=<workspace>\.opensquilla-cache\gradle

NUGET_PACKAGES=<workspace>\.opensquilla-cache\nuget
DOTNET_CLI_HOME=<workspace>\.opensquilla-cache\dotnet

COMPOSER_CACHE_DIR=<workspace>\.opensquilla-cache\composer
GEM_HOME=<workspace>\.opensquilla-cache\ruby\gems
GEM_SPEC_CACHE=<workspace>\.opensquilla-cache\ruby\specs
```

Rules:

- Do not make runtime directories writable.
- Do not special-case package install permissions by language.
- If the user explicitly sets a cache environment variable to a
  workspace-external path, Standard-Sandbox asks and Trusted-Sandbox auto grants
  only when the path is non-sensitive.
- If workspace is not writable, do not create workspace cache. Standard-Sandbox
  and Trusted-Sandbox should fail closed or require an approved writable root
  rather than silently using host caches.

## Error Handling

Errors should be structured and specific:

- Setup missing or stale: request administrator setup.
- Setup cancelled: fail closed and show how to retry setup.
- Runtime RX grant failed: fail closed with path and access type.
- Workspace RWX grant failed: fail closed with path and access type.
- Sensitive expansion: fail closed with path classification.
- Standard expansion rejected: fail closed with approval denial.
- Capability SID or token creation failed: fail closed.
- Spawn failed: include Windows error code, command, cwd, and backend name.
- Network enforcement requested in phase 1: fail closed with a clear
  `network boundary pending` diagnostic unless the caller selected Full Host
  Access.

Standard-Sandbox and Trusted-Sandbox must not quietly retry on the host after a
backend failure.

## Audit Events

The implementation should emit structured audit events for setup, refresh,
approval, and spawn decisions.

```text
windows_sandbox.setup_required
windows_sandbox.setup_completed
windows_sandbox.acl_refresh_plan
windows_sandbox.acl_auto_grant
windows_sandbox.acl_approval_required
windows_sandbox.acl_denied_sensitive
windows_sandbox.runtime_rx_failed
windows_sandbox.write_root_failed
windows_sandbox.spawn_failed
```

Common fields:

```text
mode=standard|trusted|full
backend=windows_default|host
path=<absolute path>
access=RX|RWX|DENY_WRITE
reason=runtime|workspace|cache|expansion|sensitive|setup
decision=auto|ask|deny|host
```

## Migration

Remove active legacy Windows backend files and tests tied to old concepts:

- AppContainer files and tests remain removed.
- `windows_restricted_token.py` and `windows_restricted_token_helper.py` are
  replaced by `windows_default` modules or helpers.
- Tests named around `windows_restricted_token` should be renamed or removed.
- Documentation should describe `windows_default`, Standard-Sandbox,
  Trusted-Sandbox, and Full Host Access.
- `backend="windows_restricted_token"` should produce a migration error instead
  of selecting an old path.

The new code may reuse low-level logic from the old helper, such as
`CreateRestrictedToken`, `CreateProcessAsUserW`, job object cleanup, and pipe
capture, but the product and backend boundary should be new.

## Testing Strategy

Unit tests:

- Product mode to backend selection.
- Root computation for runtime, workspace, cache, explicit roots, and
  sensitive paths.
- ACL refresh decision matrix for Full, Standard, and Trusted.
- Cache environment injection for Python, Node, Rust, Go, Java, .NET, PHP, and
  Ruby ecosystems.
- Setup payload serialization.
- Configuration error for `windows_restricted_token`.
- Fail-closed behavior when network enforcement is requested in phase 1.

Mocked Windows API tests:

- RX grant plans for runtime roots.
- RWX grant plans for workspace and cache roots.
- Per-root capability SID selection.
- Token input contains only current command capabilities.
- Sensitive paths are rejected before helper execution.
- Standard expansion asks for approval.
- Trusted non-sensitive expansion auto grants.
- Spawn uses the restricted/capability token.

Native Windows smoke tests:

- Gated behind `OPENSQUILLA_RUN_WINDOWS_NATIVE_SMOKE=1`.
- Separate administrator setup smoke from ordinary command smoke.
- Verify runtime Python can execute with RX only.
- Verify PowerShell can execute when runtime/read roots are prepared.
- Verify workspace file creation succeeds in Standard and Trusted.
- Verify workspace `.venv` creation succeeds.
- Verify `pip install` writes to workspace cache or workspace venv paths.
- Verify npm cache env points to workspace cache.
- Verify Standard asks for workspace-external expansion.
- Verify Trusted auto grants non-sensitive expansion.
- Verify sensitive paths are denied.
- Verify backend failures do not fall back to host execution.

## Acceptance Criteria

- Full Host Access remains host execution and is unaffected by
  `windows_default`.
- Windows Standard-Sandbox and Trusted-Sandbox select `windows_default`.
- There is no active `windows_restricted_token` backend execution path.
- Runtime Python and PowerShell can start in the Windows sandbox through RX
  grants.
- Workspace roots are RWX in Standard-Sandbox and Trusted-Sandbox.
- Workspace-local `.opensquilla-cache` is created and writable when workspace
  is writable.
- Common language cache environment variables point at workspace cache.
- Virtual environment creation and package installation work when their writes
  stay under workspace or approved non-sensitive roots.
- Sensitive paths are never automatically granted.
- Network enforcement is clearly reported as pending in phase 1.
- Standard-Sandbox and Trusted-Sandbox fail closed instead of silently using
  host execution.
