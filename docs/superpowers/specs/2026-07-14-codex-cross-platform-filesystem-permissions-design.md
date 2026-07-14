# Codex-Exact Cross-Platform Filesystem Permissions Design

Date: 2026-07-14

Status: Conversational design approved; pending written-spec review

Reference implementation: OpenAI Codex `b24aa20107`

Scope: Phase 1 filesystem behavior while the sandbox is enabled on Linux,
macOS, and Windows

## Summary

OpenSquilla will use one resolved filesystem permission profile for every local
filesystem tool and for shell execution. Each operating-system backend will
compile that shared profile into the native mechanism used by Codex on the same
platform. Tools must no longer create narrower, tool-specific backend policies
that disagree with the shell.

Phase 1 provides the Codex interaction model requested here:

- broad host reads, subject to explicit unreadable paths and the user's OS
  permissions;
- writes only inside declared writable roots;
- an exact, one-shot elevation request for writes outside those roots;
- automatic Guardian review when configured, with the same audit trail and
  fail-closed behavior for all tools;
- equivalent policy decisions for direct filesystem tools and shell commands.

“Codex-exact” means matching Codex's current platform implementation, not
forcing a POSIX `/` model onto every operating system. Linux and macOS can
express a full-filesystem read baseline directly. Windows uses Codex's current
projection of system roots, non-sensitive profile children, the command working
directory, and writable roots into the sandbox account.

## Why This Change Is Needed

OpenSquilla already has most of the required policy vocabulary in
`FileSystemPermissionProfile`, but the effective policy is not consistently
delivered to every backend operation.

Shell execution consumes the policy built for the active session. Direct
filesystem operations instead call backend-local
`_filesystem_operation_policy` functions in `bubblewrap.py`, `seatbelt.py`, and
`windows_default.py`. Those functions derive a narrow policy from the target
path and the temporary worker payload. That creates a second source of truth.

The mismatch produced observed failures such as:

- `exec_command` could read host paths that `list_dir` could not read;
- Linux `list_dir` failed for `/home` because a narrow bind plan collided with
  a versioned `uv` Python symlink;
- listing `/etc` failed when `entry.stat()` encountered the environment's
  unresolved `/etc/resolv.conf`;
- listing `/var` failed when one entry such as `/var/lock` could not be
  inspected;
- backend setup failures appeared as generic `SandboxBackendError` even when
  the requested read was allowed by the session profile.

The observed out-of-workspace create and delete operations did not bypass
approval. Each produced `approval_pending`, received a separate low-risk
Guardian `allow`, and then executed once on the host with an elevation grant.
The desired behavior is therefore to preserve that flow and make every writing
tool enter it consistently.

## Design Principles

### One permission profile is authoritative

The policy layer resolves a `FileSystemPermissionProfile` once for an
operation. The same immutable profile is used by:

- preflight access checks in direct filesystem tools;
- the filesystem worker backend;
- shell execution;
- elevation eligibility checks;
- audit records and structured error reporting.

Backends compile the profile. They do not infer a replacement profile from an
operation's target paths. Target paths remain operation data, not grants.

### Read, write, and elevation are separate decisions

A successful read never implies write permission. A path resolves to one of:

- `deny`: the sandbox must not expose the path;
- `read`: the path may be inspected but not modified;
- `write`: the path may be modified without elevation.

The most-specific rule wins, with later rules breaking ties. This preserves
read-only metadata carve-outs such as `.git`, `.agents`, and `.codex` beneath a
writable project root, as well as explicit unreadable roots and globs.

If a requested write resolves to `read` or has no write grant, the tool returns
`elevation_required`. It must not silently broaden the sandbox. If the path is
explicitly `deny`, unsandboxed elevation is unavailable because it would reveal
data the policy intentionally hides.

### Native OS permissions still apply

The sandbox can restrict access but cannot grant privileges the OpenSquilla
process does not possess. “Broad read” means readable wherever the host user can
read, after explicit sandbox denies. A normal host `EACCES`, sharing violation,
or ACL denial remains a filesystem error rather than an approval request.

## Canonical Profile and Operation Flow

`FileSystemPermissionProfile` remains the canonical model, but its construction
must become platform-aware without embedding Linux-only assumptions in the
shared contract. The logical profile needs a special filesystem-root target,
equivalent to Codex's `Special Root`, rather than using `Path("/")` as the
cross-platform representation of broad read access.

Before an operation starts, a platform resolver materializes special targets:

- Linux and macOS resolve filesystem-root read access to the native `/`
  baseline;
- Windows resolves it to Codex's concrete system/profile/cwd projection
  described below.

The result is an immutable, platform-resolved profile. Direct-tool preflight
and the backend compiler consume that same result. A tool must never treat an
arbitrary Windows path as readable merely because the unresolved logical
profile contains `Special Root`; if the path is outside the Codex projection,
it has no read grant unless another entry covers it.

The shared model continues to contain ordered `deny`, `read`, and `write`
entries plus denied-read globs. A backend compiler may additionally need
derived masks, mount targets, or ACL operations, but that output must preserve
the decision returned by the platform-resolved `profile.resolve(path)`.

The operation flow is:

```text
session settings + workspace + action
  -> build one logical FileSystemPermissionProfile
  -> resolve Special Root and paths for the current platform
  -> attach the resolved profile to SandboxPolicy / SandboxOperation
  -> direct-tool preflight uses that resolved profile
  -> selected backend compiles that same resolved profile
  -> shell or filesystem worker executes under compiled enforcement
```

For direct filesystem operations, the backend may add only the minimum private
transport access needed to launch its trusted worker, such as a payload file or
helper executable. Transport grants are not visible as user-requestable
filesystem access and cannot replace or widen the attached profile.

No backend may fall back to unsandboxed host execution because policy
compilation or worker startup failed.

## Platform Compilation

### Linux: bubblewrap

The Linux compiler follows Codex's `bwrap` layout:

1. Start with a read-only bind of `/` onto `/`.
2. Add the required device, process, runtime, and helper mounts.
3. Mask explicit unreadable roots and expanded unreadable globs.
4. Re-bind writable roots as writable overlays.
5. Re-apply protected subpaths beneath writable roots as read-only or masked.
6. Preserve network and process-namespace restrictions from the existing
   sandbox policy.

This order gives broad host read access without granting broad writes. It also
avoids reconstructing the visible filesystem from individual target-path binds,
which caused the observed `uv` symlink mount mismatch.

The filesystem worker and shell must enter the same helper and mount planner.
The filesystem operation path must stop using
`bubblewrap._filesystem_operation_policy` as an independent permission source.

Reference behavior:

- `codex-rs/protocol/src/permissions.rs`
- `codex-rs/linux-sandbox/src/bwrap.rs`

### macOS: Seatbelt

The macOS compiler follows Codex's Seatbelt policy generation:

1. Use a full-filesystem read rule when the profile has the host-read baseline.
2. When explicit unreadable roots exist, generate read rules that exclude those
   subpaths rather than discarding the broad read baseline.
3. Grant writes only to resolved writable roots.
4. Exclude protected metadata and explicit non-writable children from broader
   write grants.
5. Preserve the existing network and process restrictions.

Direct filesystem workers and shell processes must receive rules from the same
compiler. The filesystem operation path must stop using
`seatbelt._filesystem_operation_policy` as an independent permission source.

Reference behavior:

- `codex-rs/protocol/src/permissions.rs`
- `codex-rs/sandboxing/src/seatbelt.rs`

### Windows: restricted account and ACL projection

Windows follows Codex's actual projection behavior; it does not reinterpret
POSIX `/` as “enumerate and expose every volume.” The Windows platform resolver
materializes the `Special Root` read projection from:

- the sandbox helper directory;
- `C:\Windows`;
- `C:\Program Files`;
- `C:\Program Files (x86)` when present;
- `C:\ProgramData`;
- non-sensitive direct children of `%USERPROFILE%`;
- the operation working directory;
- declared writable roots.

The sensitive profile children excluded by Codex are:

- `.ssh`, `.tsh`, `.brev`, `.gnupg`, `.aws`, `.azure`;
- `.kube`, `.docker`, `.config`, `.npm`, `.pki`, `.terraform.d`.

The compiler grants the restricted sandbox account read/traverse access to the
projection and write access only to resolved writable roots. Explicit denied
reads and read-only/protected subpaths are applied through deny ACLs after the
base grants, matching Codex's ordering. The operation cwd is included so a
workspace outside the normal profile projection remains usable.

The direct filesystem worker must run under the same restricted account and ACL
preparation path as shell execution. The filesystem operation path must stop
using `windows_default._filesystem_operation_policy` as an independent
permission source.

If the Windows backend cannot establish the required account, grants, or deny
ACLs, the operation fails closed. It must not run directly as the host user.

Reference behavior:

- `codex-rs/windows-sandbox-rs/src/setup.rs`
- `codex-rs/sandboxing/src/windows.rs`

## Direct Filesystem Tool Consistency

The following tools must use the active profile and the selected backend in the
same way as shell execution:

- `read_file`;
- `list_dir`;
- `glob_search`;
- `grep_search`;
- `write_file`;
- `edit_file`;
- `apply_patch`;
- any media or helper tool that reads or writes a local path through the shared
  filesystem runtime.

There must be no separate hard-coded “sensitive path” denylist in a direct
filesystem tool. Sensitive paths are represented only by explicit profile
denies so that shell and direct tools reach the same decision.

### Resilient directory listing

`list_dir` treats the requested directory as the operation boundary. Once that
directory has been opened, an unstatable child must not abort the entire
listing.

For each entry:

- use non-following metadata where possible;
- identify symlinks without requiring their targets to resolve;
- report a broken symlink as a link with unavailable target metadata;
- report metadata that races or is individually inaccessible as unavailable;
- continue listing the other entries.

Failure to open or enumerate the requested directory remains an operation
error. Per-entry tolerance must not hide a denial of the requested directory
itself.

## Elevation and Automatic Review

Writes follow one shared state machine regardless of which tool requested them:

```text
write target resolves to WRITE
  -> execute in sandbox

write target resolves to READ or lacks a write grant
  -> return elevation_required with exact action fingerprint
  -> submit one approval request when the model retries with require_escalated
  -> Guardian reviews command/tool, paths, operation type, user intent, and reason
  -> allow: execute that exact action once outside the sandbox
  -> deny/error: do not execute

write target is explicitly DENY
  -> block; no unsandboxed override
```

The fingerprint binds the grant to the exact normalized operation, target
paths, arguments or patch, working directory, and relevant execution settings.
Changing any bound field creates a new request. Create and delete remain
separate actions and therefore receive separate decisions.

Automatic approval may make a low-risk operation appear immediate in the UI,
but the audit log must still show pending, reviewer outcome, and one-shot host
execution. Guardian parse failures, timeouts, malformed output, and policy
errors fail closed. This design does not weaken the existing risk reviewer; it
makes all filesystem entry points reach it consistently.

## Error Semantics

Tools return stable, actionable categories:

- explicit profile deny: `blocked` with a policy reason;
- write outside writable roots: `elevation_required`;
- reviewer deny or fail-closed error: `approval_denied` with an approval ID;
- normal OS access or filesystem failure: a structured filesystem error;
- genuine helper, namespace, Seatbelt, account, or ACL setup failure:
  `SandboxBackendError`.

An allowed path must not become `SandboxBackendError` merely because a backend
invented a narrower policy. A single broken or inaccessible directory child
must not turn a successful directory open into a backend error.

## Testing Strategy

### Shared contract tests

Table-driven tests exercise the same profile on POSIX and Windows-style paths:

- broad read baseline;
- exact writable roots;
- read-only metadata carve-outs;
- explicit denied roots and globs;
- most-specific and later-rule precedence;
- no unsandboxed override when denied reads exist.

These tests verify logical access independently from native enforcement.

### Backend compiler tests

Linux tests assert mount order: read-only `/`, deny masks, writable overlays,
then protected subpaths. macOS tests assert broad read rules with exclusion
clauses and scoped writes. Windows tests assert the exact Codex root projection,
sensitive profile-child exclusions, cwd inclusion, and grant/deny ACL ordering.

The three compiler suites must consume the same profile fixtures. Platform
modules may be unit-tested on Linux where their output is deterministic; native
integration tests remain required before claiming that a backend ships.

### Tool equivalence tests

For each platform policy fixture, compare direct-tool and shell decisions for:

- reading a system path;
- reading a home/profile path;
- reading an explicitly denied path;
- writing inside the workspace;
- writing outside the workspace;
- writing protected metadata.

The result category must match even though output formatting differs.

### Filesystem worker tests

Cover a normal directory, a broken symlink, a dangling or racing entry, an
entry with unavailable metadata, and a directory that cannot itself be opened.
The first four must preserve all listable siblings; the last must fail the
operation.

### Elevation tests

Verify the full audit sequence for an external create and a separate delete:
initial `elevation_required`, exact request fingerprint, Guardian allow/deny,
one-shot execution, replay rejection, and fail-closed malformed reviewer output.
Run the same cases through a direct write tool and shell execution.

### Native integration coverage

- Linux: mandatory local bubblewrap integration tests for `/etc`, `/home`,
  `/var`, the user home, workspace writes, external-write elevation, and denied
  reads.
- macOS: Seatbelt integration tests with the same logical scenarios on a macOS
  runner.
- Windows: restricted-account/ACL integration tests with the projected system
  roots, profile children, cwd, workspace writes, external-write elevation,
  and denied reads on a Windows runner.

Missing native evidence must be reported as unverified; passing compiler tests
alone is not sufficient to claim three-platform completion.

## Acceptance Criteria

Phase 1 is complete only when all of the following are true:

1. A sandboxed Linux shell and `list_dir` can both read allowed host directories
   such as `/etc`, `/home`, and `/var`, subject to normal OS permissions.
2. A broken symlink or individually unstatable entry does not abort an allowed
   directory listing.
3. macOS shell and direct filesystem tools receive the same full-read and
   scoped-write Seatbelt policy.
4. Windows shell and direct filesystem tools receive the same Codex-style root
   projection and ACL restrictions.
5. The same explicit denied path is unreadable through shell and every direct
   filesystem tool on each platform.
6. Workspace writes run without approval, while an otherwise allowed external
   write returns `elevation_required` through every entry point.
7. An approved external write executes exactly once; a changed operation or a
   later delete receives a new approval decision.
8. Reviewer failures and backend enforcement failures remain fail closed.
9. Unit, backend compiler, tool-equivalence, worker, approval, and available
   native integration tests pass.
10. User-facing sandbox documentation describes the platform-specific meaning
    of broad read access without claiming wider Windows coverage than Codex.

## Non-Goals

This phase does not:

- change Full Host Access or sandbox-disabled behavior;
- grant administrator/root privileges that the host process lacks;
- expose every Windows volume or sensitive profile directory beyond Codex's
  current implementation;
- add durable approval rules or long-lived write grants;
- add additive model-requested permission syntax;
- intercept and renegotiate arbitrary child-process permissions;
- change Guardian's risk taxonomy or make high-risk operations automatically
  acceptable;
- fall back to unsandboxed execution after native enforcement failure.

Those capabilities require separate designs. They are not prerequisites for
the requested Codex-style Phase 1 experience.

## Implementation Boundaries

The implementation plan may reorganize backend helpers, but it must preserve
these boundaries:

- shared policy construction owns logical permissions;
- operation runtime carries the resolved profile;
- each backend only compiles and enforces that profile;
- direct tools own user-facing input validation and result formatting, not a
  second permission system;
- elevation owns exact-action approval and host execution;
- Guardian owns the independent risk decision.

Any implementation that fixes only the reported paths, bypasses the backend for
reads, or special-cases one filesystem tool does not satisfy this design.
