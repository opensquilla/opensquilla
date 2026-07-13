# Codex-Exact Linux Sandbox Permissions and Guardian Design

**Date:** 2026-07-13

**Status:** Approved for implementation planning

**Source baseline:** OpenAI Codex `ea15456284`

**Scope:** Phase 1; sandbox enabled; local Linux bubblewrap execution

**Supersedes:** `2026-07-13-codex-parity-sandbox-elevation-design.md`

## Summary

OpenSquilla's first sandbox-elevation implementation copied the visible shape
of Codex but retained a separate sensitive-path denylist, a simplified
reviewer, fingerprint-led replay, and tool-specific elevation rules. Those
differences prevent the behavior the user expects: all normally readable host
files should be readable, while writes and capabilities outside the active
profile should be reviewed and continued with the narrowest sufficient
permission.

This design replaces that approximation with the current Codex semantics:

- one typed permission profile is authoritative for every local tool;
- the default workspace profile reads the host root and writes only declared
  roots;
- no default credential, home, or system path is denied for reads;
- one command may keep the sandbox and add narrow permissions, or explicitly
  request execution outside it;
- the approval coordinator reviews the exact suspended action and resumes that
  same action after approval;
- Unix shell child execution is gated at the authoritative `execve` boundary;
- Guardian is a dedicated, reusable, read-only agent session with bounded
  transcript context, read-only investigation tools, managed-network
  alignment, retries, timeouts, and denial circuit breaking;
- direct filesystem, patch, code, media, shell, and network tools use the same
  permission engine rather than their own sensitive-path rules.

This is a behavioral port of the cited Codex source baseline, not an attempt to
preserve the branch's earlier implementation choices.

## Phase Boundary

Phase 1 is complete only when the semantics in this document are implemented
for OpenSquilla's local Linux tool surface while the sandbox is enabled.

Included:

- managed workspace permission profiles;
- Linux bubblewrap filesystem and network enforcement;
- `use_default`, `with_additional_permissions`, and `require_escalated`;
- turn/session permission grants;
- the shared tool orchestrator and exact-action continuation;
- Guardian review for local shell, exec, patch, filesystem, code, media, and
  network requests;
- authoritative Unix child-exec escalation;
- current WebSocket/HTTP approval and audit surfaces;
- removal of default sensitive-path enforcement from sandboxed local tools.

Excluded from this phase:

- changing the deliberately coarse behavior when the sandbox is disabled;
- Windows and macOS sandbox implementations;
- Codex-specific remote execution environments and MCP connector approvals
  that have no corresponding OpenSquilla local operation;
- gaining operating-system privileges that the gateway process does not have.

The data model must remain backend-neutral so later platform work does not
require another approval model.

## Source-Aligned Invariants

1. Filesystem access is derived from the active permission profile, never from
   a global hard-coded sensitive-path list.
2. The default workspace profile grants read access to `/` and therefore to
   every file readable by the gateway's operating-system user.
3. Read visibility does not imply write, execution, network, device, or host
   privilege.
4. The narrowest sufficient permission is preferred: an additional writable
   directory stays sandboxed; full unsandboxed execution is a distinct mode.
5. An approval applies to the exact suspended action. Approval must not cause
   the main model to synthesize a replacement action.
6. Guardian assesses semantic risk and user authorization. A path being
   outside the workspace is not intrinsically high risk.
7. Custom denied-read rules remain enforceable. If any are active, a command
   cannot bypass the filesystem sandbox because that would discard them.
8. Automatic review fails closed. Review failure never becomes approval and
   never silently falls back to a human prompt.
9. Policy hooks run before Guardian or the user reviewer.
10. Every local tool reaches the same policy, approval, execution, and audit
    pipeline.

## Permission Model

### Permission profiles

Represent the active sandbox posture as a canonical permission profile:

```text
PermissionProfile
  managed
    filesystem: restricted(entries) | unrestricted
    network: restricted | enabled
  disabled
  external
    network: restricted | enabled
```

Phase 1 executes the `managed` local Linux path. `disabled` represents the
existing no-sandbox posture. `external` is retained in the data model for
future externally sandboxed environments.

Filesystem entries have ordered access levels:

```text
deny < read < write
```

An entry targets an absolute path, a supported glob, or a symbolic special
path such as root, project roots, `/tmp`, or `$TMPDIR`. Resolution uses
canonical absolute paths and component boundaries. The most specific matching
entry wins, with the stronger access mode resolving equal-target conflicts.

Supported denied reads are explicit policy entries, including exact paths and
deny-only globs. They are configuration, not a built-in list of paths that
OpenSquilla considers inherently sensitive.

### Default workspace profile

The default sandbox-on workspace profile contains:

1. `:root = read`;
2. every effective project/workspace root = `write`;
3. `/tmp = write`, unless explicitly excluded;
4. `$TMPDIR = write`, unless explicitly excluded;
5. every configured writable root = `write`;
6. `.git`, `.agents`, and `.codex` below project/writable roots = `read`,
   unless a more explicit user rule grants write.

Consequences:

- `/`, `/home/lrk`, other repositories, `~/.ssh`, `~/.aws`, workspace `.env`,
  `/etc`, and `/root` are not rejected by OpenSquilla merely because of their
  names;
- the operating system may still return `EACCES`, for example when the gateway
  user cannot read `/etc/shadow`;
- project files are writable without approval;
- writes outside writable roots are denied by the profile and can follow the
  elevation pipeline;
- Git and agent metadata remain read-only inside an otherwise writable root by
  default.

The previous special case that allowed only listing `/` is removed once this
profile is authoritative.

### No default sensitive-path gate

The current global `sensitive_path` hard block is removed from sandbox-on
authorization for:

- filesystem reads and writes;
- directory listing and search;
- media loading;
- shell and code preflight;
- patch application;
- workspace and mount validation;
- bubblewrap runtime deny roots.

Code may retain compatibility parsing for historical records or UI labels,
but it must not decide sandbox-on access. A deployment that wants unreadable
paths expresses them as denied-read entries in the active permission profile.

Kernel-facing isolation is not a sensitive-path denylist. Bubblewrap still
provides a fresh `/proc`, a minimal `/dev`, PID/user namespaces, and configured
network isolation.

## Linux Bubblewrap Construction

For the default full-read restricted-write profile, construct the namespace in
this order:

1. `--ro-bind / /`;
2. `--dev /dev` to create the minimal standard device set;
3. mask explicit unreadable ancestors needed before narrower mounts;
4. `--bind` each existing writable root;
5. reapply read-only protected subpaths inside writable roots;
6. mask remaining explicit unreadable paths and expanded deny globs;
7. enter fresh user and PID namespaces;
8. enter an isolated network namespace when the network policy requires it;
9. mount a fresh `/proc`;
10. enter the canonical command cwd and execute.

Missing writable roots are skipped rather than making command startup fail.
Symlinked writable roots and protected subpaths are resolved without turning a
logical path alias into an escape. Missing protected metadata paths must be
protected against creation under a writable ancestor.

When the filesystem profile is full-write and network access is unrestricted,
the outer filesystem wrapper may be omitted. Managed network requirements or
denied reads still require the platform sandbox.

Network isolation uses the existing Codex-shaped posture:

- restricted mode denies IP socket operations while preserving process-local
  Unix IPC needed by common tools;
- proxy-routed mode uses an isolated namespace and permits only the proxy
  bridge path;
- seccomp denies process-memory inspection syscalls and applies
  `no_new_privs` when restrictions require it;
- managed-network sessions remain fail-closed even when a nominal profile
  otherwise enables network access.

## Per-Command Permission Modes

Every shell-like or executable action declares exactly one mode:

### `use_default`

Run with the turn's active permission profile unchanged. Normal reads and
workspace writes use this mode.

### `with_additional_permissions`

Keep the command sandboxed and merge a one-command permission overlay into the
active profile. The overlay can request:

- specific filesystem read/write entries;
- network enabled for this command.

The request must be non-empty, normalized, canonicalized, and approved unless
it is already covered by a previously granted turn/session permission. Read or
write glob grants are rejected; glob entries are supported only for denied
reads. The effective runtime profile is derived by merging the base and
additional profiles, then materializing project-root-dependent entries.

This is the normal route for a narrow write outside the workspace. It does not
grant a general host shell and it preserves all other sandbox restrictions.

### `require_escalated`

Request that this exact action run without the outer filesystem sandbox after
approval. It is appropriate only when a narrow additive profile cannot express
the required operation.

If the active filesystem policy contains any effective denied-read rule,
unsandboxed execution is forbidden because it would bypass that rule. The
request remains sandboxed or is rejected rather than silently discarding the
denied-read policy. Managed network is also not implicitly retained for a true
unsandboxed run; the exact requested network effect must be part of review.

## Durable Permission Requests

Expose a `request_permissions` tool with:

- an optional reason;
- a requested filesystem/network permission profile;
- an optional environment identifier for future multi-environment support.

The response contains:

- the granted subset of the requested profile;
- scope: current turn or current session;
- `strict_auto_review` for a turn-scoped grant.

Rules:

1. empty requests are invalid;
2. `never` approval policy returns no grant;
3. a granular policy can disable permission requests;
4. a client or Guardian may grant only a subset of what was requested;
5. the runtime intersects requested and returned profiles before storing them;
6. turn grants expire with the turn; session grants persist only in the
   current session state;
7. session scope cannot be combined with `strict_auto_review`;
8. later shell-like commands automatically merge applicable stored grants;
9. `strict_auto_review` routes later actions through Guardian even when normal
   command policy would skip approval.

## Shared Tool Orchestrator

All covered local tools implement a common runtime contract:

- canonical approval keys;
- per-request sandbox permission mode;
- optional additional permissions;
- an approval requirement;
- an exact Guardian action;
- sandbox preference and cwd;
- optional network approval specification;
- the actual run operation.

The orchestrator owns approval, sandbox selection, retry semantics, and audit.
Individual tools must not reproduce this flow.

### Approval requirement

Policy resolves each exact request to:

- `skip`, optionally with a policy-authorized sandbox bypass;
- `needs_approval`, with a concrete reason;
- `forbidden`, with a terminal reason.

The normal order is:

```text
permission/config hook -> Guardian or explicit user reviewer -> execution
```

A hook may allow or deny before a reviewer. Guardian is selected only for
on-request or enabled granular approval with `approvals_reviewer =
"auto_review"`. Explicit user-review mode remains human-actionable.

### First attempt

- `use_default` runs under the active sandbox.
- `with_additional_permissions` is approved, merged, and runs under a widened
  sandbox for this command only.
- approved `require_escalated` bypasses the sandbox on the first attempt only
  when denied-read preservation permits it.
- a trusted policy rule may explicitly bypass the first sandbox attempt.

### Attributable sandbox denial and retry

If a sandboxed attempt returns an attributable filesystem or managed-network
denial and the tool supports escalation:

1. preserve the original output and structured policy-decision context;
2. verify that the active approval policy permits a retry request;
3. build a retry reason from the exact denial;
4. review the same request again for the broader execution context when
   required;
5. run a second attempt with the approved effective profile or without the
   sandbox when that is allowed;
6. return the second result without asking the main model to recreate the
   action.

Strict auto-review treats the sandboxed attempt and broader retry as separate
risk contexts, so approval of the first does not automatically approve the
second. Generic command failure is not treated as a sandbox denial.

### Exact suspended action

The runtime keeps the original request object suspended while review is in
progress. On approval it resumes that same request with the selected execution
profile. Identity includes the call/run ID and immutable canonical request.

Fingerprints remain useful for persistence, cache keys, and tamper detection,
but they are not the primary continuation mechanism. The old flow that asks
the main model to issue a second equivalent call is removed. A material change
to argv, cwd, patch, code, targets, TTY state, requested permissions, or network
destination is a new request and needs a new review.

## Authoritative Unix Child-Exec Escalation

Preflight parsing cannot reliably see the final executable after shell
expansion, functions, scripts, or nested process launches. Phase 1 therefore
ports Codex's authoritative Unix child-exec gate.

For shell executions that support the gate:

1. the sandboxed shell announces each child `execve` with source, executable,
   argv, cwd, and requested additional permissions;
2. the parent runtime pauses that child before execution;
3. execution policy and permission hooks evaluate the exact child action;
4. Guardian or the user reviewer is invoked when required;
5. denial terminates that child action without substituting another command;
6. approval resumes it under the default, additional, or escalated profile;
7. the result remains attributed to the originating shell tool call.

When denied reads are active, a child `require_escalated` request cannot become
unsandboxed. Additional permissions stay sandboxed.

Shell-string parsing remains an advisory preflight and user-facing explanation
aid. It is not authoritative for path-sensitive approval and must not silently
widen mounts. If authoritative interception is unavailable for a shell form,
the runtime fails closed for an otherwise required child escalation rather
than guessing.

## OpenSquilla Tool Mapping

Codex primarily exposes shell, exec, and patch actions. OpenSquilla has
additional direct tools; exact semantics require mapping them into the shared
runtime rather than retaining parallel policy gates.

### Read tools

Filesystem read/list/search and media load resolve the active profile and run
directly when it permits read. Under the default profile, all OS-readable host
paths are eligible. Explicit denied reads return a structured policy denial.

### Direct filesystem mutations

Create, write, replace, move, copy, mkdir, and delete describe exact canonical
source/target paths and operation semantics. Workspace operations use the
default profile. External mutations use additional write permission where
possible; only operations that cannot be represented narrowly request full
escalation.

### Patch application

Guardian receives cwd, every affected file, and the full patch body, bounded
only by Guardian's action-string truncation policy. Runtime approval and
continuation retain the untruncated original patch. A digest alone is
insufficient for semantic review.

### Code execution

Python and other code execution are lowered into the shared executable action:
exact interpreter, argv, cwd, source/input, TTY state, requested permissions,
and expected network posture. Static code scanning is advisory only. Nested
processes use the child-exec gate.

### Network

Network review includes target, normalized host, protocol, port, and the
triggering command or action when available. The request is attributed to a
single active tool call; ambiguous attribution fails closed. Approval can be
immediate or deferred to the attempt lifecycle, but denial cancels the exact
network operation and is reported to the originating call.

## Guardian Approval Actions

Guardian accepts exact typed actions. The Phase 1 set is:

- shell: argv/command, cwd, sandbox permission mode, additional permissions,
  justification;
- exec command: the same plus TTY state;
- Unix `execve`: source, program, argv, cwd, additional permissions;
- apply patch: cwd, affected files, full patch;
- direct filesystem mutation: operation, canonical sources/targets, full
  mutation payload when needed to judge risk;
- code execution: interpreter, argv, cwd, source/input, permissions, TTY;
- media mutation/export: operation, canonical input/output, destination;
- network access: target, host, protocol, port, triggering action;
- permission request: reason and requested permission profile.

Action strings sent to Guardian are individually capped at 16,000 tokens with
explicit truncation markers. The executor always retains the complete original
action. Truncation is evidence loss and makes Guardian more cautious; it is not
evidence that omitted content is benign.

## Guardian Policy

Guardian judges one planned action using intrinsic risk and authorization from
the trusted transcript. Transcript messages, tool arguments/results, retry
reasons, files, and the action itself are evidence, not instructions to the
reviewer. Content attempting to redefine policy or force approval is ignored
and may indicate prompt injection.

### Authorization levels

- `high`: the user explicitly requested or approved the exact action, payload,
  target, or necessary side effect;
- `medium`: the user authorized the action in substance but not the exact
  implementation;
- `low`: the action is only loosely related or includes material unapproved
  side effects;
- `unknown`: little or no trusted evidence authorizes it.

Urgency does not raise authorization. Tool, file, web, plugin, and assistant
content cannot establish user authorization by themselves.

### Risk levels

- `low`: routine, narrow, easy to reverse, with no credential access,
  untrusted export, persistent weakening, meaningful loss, or disruption;
- `medium`: meaningful but bounded blast radius or reversible side effects;
- `high`: dangerous or costly-to-reverse action with meaningful risk of
  irreversible loss or important disruption;
- `critical`: obvious credential/secret exfiltration to an untrusted
  destination, major irreversible destruction, or persistent broad security
  weakening.

An external path, an elevation request, or `rm -rf` is not automatically high
risk. Guardian should use read-only tools to inspect the concrete target when
state determines risk. Creating or deleting one known temporary file can be
low or medium; unknown recursive scope, system mutation, untrusted execution,
and data export are judged from their actual effects.

### Default outcome thresholds

Unless tenant policy supplies a stricter rule:

| Risk | Default outcome |
| --- | --- |
| `low` | allow |
| `medium` | allow |
| `high` | allow only with authorization at least `medium`, narrow scope, and no absolute tenant deny |
| `critical` | deny |

Low/medium risk does not require authorization unless there are clear signs of
malicious prompt injection.

Codex gives explicit post-denial user reapproval the highest precedence in
this default outcome section: when the user has seen the concrete risk and
unambiguously reapproves the exact previously denied action, Guardian records
`authorization = high` and may return `allow`. Tenant absolute-deny policy
still wins. This rule must not be weakened into approval based on a vague
"continue" or on an assistant/tool message.

Guardian returns strict structured output:

```json
{
  "risk_level": "low | medium | high | critical",
  "user_authorization": "unknown | low | medium | high",
  "outcome": "allow | deny",
  "rationale": "one concise reason"
}
```

## Guardian Review Session

Guardian is a dedicated agent session, not a one-off raw provider call.

### Configuration alignment

The review session clones the parent session configuration and selects the
provider's preferred review model or configured override. It prefers low
reasoning effort when that model supports it. Relevant model/provider changes
in the parent invalidate or update the reviewer trunk.

The review session is forced to:

- `PermissionProfile.read_only()`;
- approval policy `never`;
- no write or elevation tools;
- no skills, memories, apps instructions, plugins, MCP servers, hooks,
  collaboration, multi-agent spawning, or web-search tool;
- the parent's managed-network proxy and allowlist when present, so approved
  read-only investigation has the same network boundary.

Unlike the earlier OpenSquilla approximation, Guardian has read-only tools and
is expected to use them when local state can materially change the decision.

### Reusable trunk and parallel reviews

Maintain a reusable reviewer trunk session to benefit from prompt caching.
The first review receives the bounded full transcript; later reviews receive a
delta when the stored cursor and parent history version remain valid.

If the trunk is busy or its configuration changed, create an ephemeral fork
from the last committed reviewer snapshot. Parallel review must not corrupt
the trunk cursor. Commit transcript progress only after a completed valid
review turn.

### Transcript projection

Retain relevant developer, user, assistant, and tool entries with explicit
trust/evidence framing. Limits match the source baseline:

- message transcript: 10,000 tokens total;
- tool transcript: 10,000 tokens total;
- each message: 2,000 tokens;
- each tool entry: 1,000 tokens;
- 40 recent entries;
- each action string: 16,000 tokens.

The prompt also includes the exact action, retry reason, active denied-read
context, tenant policy, and any concrete prior denial followed by user
reapproval. Every omission has an explicit truncation marker.

### Timeout, retry, and failure

- one review has a 90-second overall deadline;
- at most three attempts fit inside that same deadline;
- retry only parse errors and structured transient provider/session errors:
  overload, HTTP connection failure, stream connection failure, internal
  server error, or stream disconnection;
- do not retry timeout, cancellation, prompt-build failure, or non-transient
  session error;
- timeout returns the distinct `timed_out` decision;
- cancellation returns `abort`;
- final prompt/session/parse failures synthesize a high-risk,
  unknown-authorization denial and fail closed.

A timeout message states that timeout is not evidence the action is unsafe;
the main agent may retry once or ask the user. A denial message forbids
circumvention and permits only a materially safer alternative or an exact
retry after informed user reapproval.

## Denial Circuit Breaker

Track completed Guardian decisions per turn:

- a denial increments the consecutive count and records `true` in a rolling
  50-review window;
- a non-denial resets the consecutive count and records `false`;
- interrupt the turn after 3 consecutive denials or 10 denials in the latest
  50 reviews;
- trigger the interruption only once per turn;
- timeout, abort, and infrastructure failure follow Codex's explicit
  count/non-count classification rather than being treated as ordinary valid
  denials;
- clear state when the turn ends.

The user-visible interruption explains both counters and prevents repeated
policy probing.

## Approval and Continuation States

Internal automatic review states are:

```text
requested -> in_progress -> approved -> executing -> completed
                         \-> denied
                         \-> timed_out
                         \-> aborted
                         \-> failed_closed
```

Automatic reviews are not human-actionable. Explicit user reviews remain
visible in the existing approval UI.

An approved action stays attached to the suspended call. Persistent approval
records may store canonical keys for approved-for-session behavior, but a
one-shot automatic approval cannot be generalized into a prefix rule or a
different payload. If execution may have begun and the process crashes, mark
the action terminal/indeterminate and do not replay it automatically.

## Audit and Secret Handling

Emit structured lifecycle events for:

- review/run/call/turn/session IDs;
- action kind and bounded summary;
- permission mode and additional profile;
- reviewer source and model;
- start, attempt, completion, timeout, and latency;
- risk, authorization, outcome, and rationale;
- sandbox first-attempt and retry outcomes;
- network target and policy decision;
- circuit-breaker interruption.

Guardian receives exact content needed for semantic review, including full
patch/code/mutation payloads subject to prompt truncation. Long-term logs do
not need to persist those bodies: store bounded summaries, digests, and
redacted structured fields. Never place raw credentials or environment values
in routine logs.

## Configuration and Compatibility

The sandbox configuration exposes:

```toml
[sandbox]
approvals_reviewer = "auto_review" # or "user"
exclude_slash_tmp = false
exclude_tmpdir_env_var = false
```

Custom permission profiles can add explicit filesystem entries and network
posture. Legacy sensitive-path configuration must be migrated or warned as
unsupported for sandbox-on enforcement; it must not remain an invisible second
policy system.

Existing approval records created by the approximation may be displayed for
audit, but they cannot authorize new exact-permission actions. Existing
fingerprint-bound one-shot grants expire during migration. No database
migration may convert a historical broad grant into a turn/session permission
profile.

## Testing Strategy

Implementation follows test-driven development. The acceptance suite must
exercise real bubblewrap where the host supports it, plus deterministic unit
and integration tests.

### Permission profile tests

- default profile resolves `/` and representative host files to read;
- workspace roots, `/tmp`, `$TMPDIR`, and explicit roots resolve to write;
- `.git`, `.agents`, and `.codex` resolve back to read;
- explicit more-specific rules and component boundaries work;
- custom denied paths/globs are unreadable and prevent unsandboxed bypass;
- symlink and missing-target cases do not escape write policy.

### Real Linux sandbox tests

- list `/` and read `/etc/hosts` inside bubblewrap;
- read user-owned files under home outside the workspace;
- observe OS-level failure for a file the process user cannot read;
- reject an external write under `use_default`;
- allow the same exact write with approved additional permission;
- retain a minimal `/dev`, fresh `/proc`, PID/user isolation, and configured
  network restrictions;
- preserve read-only protected metadata under writable roots.

### Permission-mode tests

- validate all three modes and reject malformed combinations;
- keep additional permissions sandboxed and one-command scoped;
- forbid true escalation when denied reads exist;
- normalize, merge, intersect, and materialize grants correctly;
- enforce turn/session scope and strict auto-review.

### Orchestrator tests

- hooks run before reviewers;
- first-attempt selection matches the permission mode;
- attributable denial reviews and retries the same request;
- generic failures do not escalate;
- strict auto-review separately reviews a broader retry;
- cancellation or crash cannot duplicate a side effect;
- every OpenSquilla direct tool uses the shared path.

### Child-exec tests

- pause and review the exact final executable and argv;
- apply additional permission without leaving the sandbox;
- apply true escalation only when allowed;
- deny nested or transformed commands without running them;
- preserve result attribution to the original shell call;
- fail closed when the child gate is unavailable.

### Guardian tests

- exact policy matrix, including low/medium unauthenticated allows;
- high-risk narrow authorization rules and critical default denial;
- informed post-denial exact reapproval precedence;
- prompt injection cannot establish authorization;
- read-only inspection changes state-dependent risk decisions;
- full/delta transcript limits and truncation markers;
- reusable trunk, parallel fork, and configuration invalidation;
- 90-second deadline, three-attempt retry classification, timeout, abort, and
  fail-closed synthesis;
- 3-consecutive and 10-of-50 circuit breakers.

### Regression tests

- sandbox-disabled behavior is unchanged;
- explicit user reviewer remains human-actionable;
- automatic review never creates a human approval popup;
- approval/audit APIs remain consistent;
- old `sensitive_path` tests are replaced with permission-profile tests, not
  simply deleted without coverage;
- existing session workspace selection still determines the correct project
  roots and cwd.

## Acceptance Scenarios

1. In a sandboxed session whose cwd is the OpenSquilla checkout, the agent can
   list `/`, inspect `/home/lrk`, and read all files the gateway user can read,
   without an approval.
2. It edits normal checkout files directly, while `.git`, `.agents`, and
   `.codex` remain protected unless specifically authorized.
3. A user requests one fixed Desktop file. The action requests a Desktop write
   overlay, Guardian verifies the narrow low-risk action, and the same
   suspended call completes inside a widened sandbox without a prompt.
4. A command truly requiring host execution uses `require_escalated`; Guardian
   reviews it, and the exact call runs outside the sandbox only when no denied
   read policy would be lost.
5. A shell expands into a child executable requiring broader permission. The
   child pauses at `execve`, is reviewed with its final argv/cwd, and resumes or
   terminates according to that decision.
6. A known single-file delete is assessed from its actual target and user
   request, not rejected merely for using delete syntax.
7. An uncertain recursive mutation or credential export is denied; no
   alternate action is synthesized and repeated probing trips the circuit
   breaker.
8. Guardian can perform read-only inspection of a deletion target, but cannot
   mutate it, request elevation, use plugins/skills, or escape the parent's
   managed-network boundary.
9. A Guardian timeout leaves the action unexecuted and distinct from a policy
   denial.
10. A deployment adds an explicit denied-read glob for secrets. It is enforced
    across all tools and also disables true unsandboxed escalation that would
    bypass it.

## Completion Criteria

Phase 1 is complete only when:

- all source-aligned invariants are implemented;
- the default sensitive-path hard block is absent from sandbox-on execution;
- every included local tool routes through the shared permission engine;
- additional permissions, durable permission requests, exact continuation,
  Unix child-exec gating, and the complete Guardian session are operational;
- old approximation-only paths are removed rather than left as competing
  authorization systems;
- the full focused suite and repository regression suite pass;
- real bubblewrap acceptance scenarios pass on Linux;
- documentation describes the implemented semantics without calling a partial
  subset "Codex parity."
