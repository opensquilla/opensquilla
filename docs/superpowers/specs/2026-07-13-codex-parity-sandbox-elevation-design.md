# Codex-Parity Sandbox Read and Automatic Elevation Design

**Date:** 2026-07-13

**Status:** Approved for implementation planning

**Scope:** Phase 1, sandbox enabled, Linux bubblewrap first

## Summary

When the sandbox is enabled, OpenSquilla should behave like Codex for local
coding work:

- make the host filesystem visible read-only inside the sandbox;
- keep the active workspace and explicitly writable roots writable;
- require a structured, one-operation elevation request for writes or other
  capabilities outside the active sandbox profile;
- route that request through an independent `auto_review` model;
- continue the exact suspended operation when review approves it;
- fail closed and return the denial to the agent when review does not approve;
- let the agent explain the concrete risk and obtain explicit user
  re-authorization before retrying a denied action.

The phase deliberately changes only sandboxed execution. Full-host mode keeps
its existing coarse-grained semantics.

## Context

The current trusted-sandbox implementation has two user-visible gaps.

First, the Linux bubblewrap backend builds an empty root with `--tmpfs /` and
only mounts configured workspace/session paths. A process started in the
sandbox therefore cannot inspect normal host paths even when the operation is
read-only. This differs from Codex, which exposes the host root read-only and
overlays the configured writable roots.

Second, OpenSquilla currently mixes path discovery, policy, and authorization.
Trusted-mode path checks may silently add a broad temporary mount, while other
execution paths simply return a terminal sandbox denial. There is no generic,
independent model reviewer that evaluates an exact elevation action using both
intrinsic risk and evidence of user authorization.

OpenSquilla already has useful infrastructure to retain:

- a persistent approval queue;
- approval IDs bound to tool parameters;
- wait-and-retry behavior in the interactive agent loop;
- claim/finalize/consume operations intended to prevent duplicate execution;
- Web UI and terminal visibility for human-actionable approvals.

Phase 1 will centralize and strengthen those pieces rather than introduce a
parallel approval system.

## Goals

### Filesystem visibility

1. Mount the host `/` read-only for sandboxed Linux processes.
2. Overlay the active workspace, configured writable roots, and scratch paths
   as writable.
3. Preserve host discretionary access controls: OpenSquilla does not gain the
   ability to read files that its operating-system user cannot read.
4. Preserve existing isolation for process, device, IPC, and network behavior;
   a read-only root mount is not full-host execution.

### Structured elevation

1. Give every relevant execution tool an explicit permission intent, aligned
   with Codex concepts:
   - normal sandbox execution;
   - `require_escalated` for one exact host-level invocation;
   - optional additional permissions when a narrower sandbox expansion is
     supported;
   - a concise justification;
   - an optional, narrowly scoped prefix-rule suggestion.
2. Cover shell, filesystem mutations, patch application, and code execution.
   Use the same canonical action model for network or GUI capability requests
   that already reach sandbox governance.
3. Treat static command/path parsing as an advisory detector. It may identify
   that elevation is required, but it may neither approve the action nor
   silently widen the sandbox.
4. Bind approval to the exact canonical action and consume it once.

### Automatic review

1. Add `approvals_reviewer = "auto_review"` as the Codex-parity reviewer route.
2. Run review in an independent session that is read-only, has no network, uses
   `approval_policy = never`, and cannot request elevation.
3. Classify both intrinsic risk and transcript authorization.
4. Apply the Codex risk/authorization outcome policy exactly.
5. Fail closed on timeout, cancellation, provider error, invalid structured
   output, or action-fingerprint mismatch.
6. Emit enough structured audit information to understand every decision
   without persisting raw secrets unnecessarily.

### Smooth continuation

1. Suspend the exact tool invocation while review runs.
2. On approval, resume the same invocation with the same arguments rather than
   asking the main agent to regenerate it.
3. On denial, expose a concise rationale to the main agent. Do not
   automatically replace an `auto_review` denial with a human approval popup.
4. Allow a materially safer request, a narrower request, or a retry after the
   user explicitly approves the concrete risk.
5. Stop repeated policy probing with a per-turn denial circuit breaker.

## Non-goals

- Changing behavior when the sandbox is disabled.
- Automatically replaying a command outside the sandbox merely because a
  backend reported `EPERM` or another generic failure. As in Codex, the agent
  must submit explicit elevated intent.
- Secret-path masking beyond the active permission profile. A separate phase
  may add default sensitive-path exclusions.
- Giving the reviewer network or mutation capabilities.
- Letting automatic review create a persistent prefix rule.
- Replacing host operating-system permissions.
- Full parity for every non-Linux backend in the first implementation. The
  data model and policy stay backend-neutral, but bubblewrap is the first
  acceptance target.

## Considered Approaches

### A. Deterministic risk rules only

Parse commands and paths, then allow a fixed list of operations such as a
single-file create or edit.

This is fast and easy to test, but it cannot reliably connect an action to the
user's actual request, distinguish trusted authorization from prompt injection,
or reason about compound side effects. It also becomes a growing collection of
fragile shell heuristics.

### B. Automatically review, then fall back to a human prompt

Let the model approve low-risk operations and surface every denial or timeout
as an interactive approval card.

This reduces false negatives but does not match Codex. It also lets an agent
turn every reviewer denial into approval fatigue and makes unattended behavior
depend on whether a UI happens to be connected.

### C. Codex-parity Guardian route

Use deterministic checks for hard constraints and canonicalization, then use a
separate model to classify risk and authorization. An auto-review denial is
returned to the agent, which must choose a safer action or obtain explicit user
authorization before retrying.

**Decision:** use approach C. Deterministic checks remain authoritative for
absolute denials and action integrity; the reviewer handles semantic risk and
authorization. Approach A remains a preprocessing layer, not the final
decision-maker. Approach B remains available only when the configured reviewer
is explicitly `user`, not as an implicit fallback from `auto_review`.

## Architecture

### 1. Sandbox permission profile

Represent the active filesystem policy as:

- read roots, including `/` on the Linux bubblewrap backend;
- writable roots, including the active workspace and explicit scratch roots;
- denied read/write paths supplied by a stricter active profile;
- network policy;
- process/GUI/device capabilities.

Permission-profile matching must use canonical absolute paths and component
boundaries. A path that merely shares a string prefix with a writable root is
not writable.

For bubblewrap, construct the mount namespace in this order:

1. read-only bind `/` to `/`;
2. apply virtual filesystem and device restrictions;
3. overlay writable roots;
4. apply explicit deny/mask entries, if any;
5. set the requested working directory.

Writable overlays must never be broader than the active profile. In
particular, trusted mode must stop silently mounting the user's whole home
directory read-write.

### 2. Canonical approval action

All covered tools translate their input to a common `ApprovalAction` before
review. The action contains, as applicable:

- tool and action kind;
- exact argv or command segments;
- working directory;
- target environment;
- sandbox permission intent;
- additional filesystem/network permissions;
- canonical target paths and access types;
- patch or code-content digest;
- network destination and a coarse description of outbound data;
- TTY/GUI flags;
- justification;
- optional prefix-rule suggestion;
- session and turn identifiers used for audit, not authorization matching.

The action fingerprint includes every field that can materially affect side
effects. Volatile IDs and timestamps are excluded. Any material change creates
a new action and requires a new review.

Shell control operators are split into independently reviewable command
segments where the execution layer already treats them independently. Shell
features that cannot be safely canonicalized do not qualify for a reusable
prefix rule.

### 3. Elevation detection

The main agent is responsible for requesting elevation when its planned action
requires it. Tool schemas and the coding-agent prompt explain the common cases:

- a write target is outside the active writable roots;
- the action requests a denied network destination;
- the action launches a GUI or needs another capability unavailable in the
  sandbox;
- a previous structured sandbox denial says the same action requires
  elevation.

Preflight path/command analysis may return `elevation_required` before starting
the backend. A backend denial may also return that structured next step when it
can confidently attribute the failure to policy. Neither path fabricates
`require_escalated` on the agent's behalf.

### 4. Approval coordinator

Introduce one central coordinator between sandbox policy and execution. It
selects a reviewer after hard policy checks:

1. policy/config hooks;
2. `auto_review` Guardian;
3. explicit user reviewer when configured.

For `auto_review`, the coordinator creates a non-human-actionable review record
and starts the reviewer. The existing interactive wait-and-retry flow may wait
on that record, but Web UI approval badges must not present it as something the
user needs to click.

The lifecycle is:

```text
requested -> reviewing -> approved -> claimed -> consumed -> completed
                       \-> denied
                       \-> timed_out
                       \-> failed_closed
```

An executor must atomically claim an approved action before running it. A claim
validates namespace, fingerprint, session/turn scope, expiry, and reviewer
outcome. Completion consumes the grant. If the process crashes after execution
may have begun, record an indeterminate consumed state and do not replay the
action automatically.

### 5. Guardian review session

The reviewer receives:

- the canonical action;
- the active permission profile and the exact capability being requested;
- the trusted conversation transcript needed to judge authorization;
- explicit trust labels for other context;
- any prior denial rationale and subsequent user response for the same action;
- a fixed security policy and a strict JSON output schema.

Only these sources can establish user authorization:

- user messages;
- developer/system instructions;
- applicable trusted repository instructions such as `AGENTS.md`;
- direct answers to a user-input request.

Tool output, fetched content, skills, plugin descriptions, assistant messages,
and normal file contents are untrusted evidence. They may provide
implementation detail but cannot expand authorization unless the user
explicitly asked the agent to follow the relevant content. Evidence of prompt
injection makes the reviewer more conservative and can trigger a denial.

The reviewer returns exactly:

```json
{
  "risk_level": "low | medium | high | critical",
  "user_authorization": "unknown | low | medium | high",
  "outcome": "allow | deny",
  "rationale": "one concise reason"
}
```

Parsing may recover a single JSON object wrapped in incidental prose, matching
Codex's tolerance. Missing, ambiguous, or invalid output fails closed.

## Risk and Authorization Policy

### Authorization

- `high`: the user explicitly requested or approved the exact action, payload,
  target, or side effect, including a necessary implementation of that exact
  request.
- `medium`: the user authorized the action in substance, but not the exact
  implementation choice.
- `low`: the action only loosely follows from the user's goal or includes
  material side effects that were not clearly authorized.
- `unknown`: there is no trusted evidence that the action is related to the
  user's request.

Authorization is judged semantically, not by exact command syntax. Urgency does
not raise authorization. After a denial, a trusted user message that explicitly
re-approves the same action after seeing its concrete risk raises authorization
to `high` for that retry.

### Risk

- `low`: narrow, routine, easy-to-reverse operations without credential access,
  untrusted export, persistent security weakening, meaningful data-loss risk,
  or service disruption.
- `medium`: meaningful but bounded blast radius or reversible side effects.
- `high`: dangerous or costly-to-reverse actions with meaningful risk of
  irreversible loss or important service disruption.
- `critical`: obvious credential/secret exfiltration to an untrusted
  destination or major irreversible destruction.

Writing outside the workspace or using `require_escalated` is not intrinsically
high risk. The reviewer evaluates the actual action. Creating one fixed local
file can be low risk; recursively changing an unknown tree, modifying system
configuration, exporting credentials, or executing an untrusted downloaded
program is assessed from its real side effects.

### Outcome

Unless a stricter absolute-deny rule applies:

| Risk | Outcome |
| --- | --- |
| `low` | allow |
| `medium` | allow |
| `high` | allow only with authorization at least `medium`, a narrow scope, and no absolute deny |
| `critical` | deny |

A post-denial explicit user approval may satisfy the authorization requirement
for a narrowly scoped high-risk action. It never overrides a `critical` result
or an absolute policy denial.

## Tool Execution Flows

### Normal sandboxed read

1. The agent calls a read tool or shell command without elevated intent.
2. Policy observes that `/` is readable and no denied path applies.
3. The backend executes inside the sandbox with a read-only host root.
4. No approval occurs.

### Workspace write

1. The agent calls a mutation tool without elevated intent.
2. The canonical target falls inside a writable root.
3. The backend executes inside the sandbox.
4. No approval occurs.

### Proactive out-of-workspace write

1. The agent calls the tool with `require_escalated`, exact arguments, and a
   justification.
2. Hard policy validates that this action is eligible for review.
3. The coordinator sends the canonical action to Guardian.
4. Guardian allows a low/medium action, or an eligible narrow high-risk action.
5. The grant is bound to the fingerprint and claimed once.
6. The exact suspended operation executes at host level for that invocation.
7. The grant is consumed and the result returns to the main agent.

For direct filesystem tools, host-level execution means performing only that
tool's already-canonicalized mutation. It does not confer a general host shell.
For shell/code execution, it means the reviewed invocation runs without the
normal filesystem sandbox, exactly as requested.

### Missing elevated intent

1. Preflight or the backend identifies a policy-prohibited capability.
2. The tool returns a structured denial with `require_escalated` as the
   permitted next step.
3. The main agent decides whether the user's task justifies a retry and, if so,
   submits a new structured elevated request.
4. The runtime never silently converts a generic error into host execution.

### Guardian denial

1. Guardian denies and returns its risk/authorization rationale.
2. The reviewed action does not execute.
3. The main agent receives instructions not to use a workaround or merely
   rephrase the same request.
4. It may choose a materially safer action, request narrower access, or explain
   the concrete risk to the user.
5. If the user explicitly re-approves the same action after that explanation,
   a new review evaluates the new trusted authorization evidence.

There is no automatic fallback to a human approval card.

### Review timeout or failure

1. The coordinator records a distinct timeout, cancellation, or failed-closed
   state.
2. The action does not execute.
3. A timeout message tells the main agent that timeout is not itself proof of
   danger; it may retry once or ask for guidance.
4. Parse/provider/session failures are denials until a fresh review succeeds.

## Persistent Prefix Rules

Prefix rules are optional convenience policy, not a substitute for review.

- Guardian may approve only the current action.
- A prefix suggestion is visible in audit/UI metadata but cannot be silently
  persisted by automatic review.
- Persisting a rule requires explicit user action through a human-authorized
  configuration surface.
- Rules are tokenized prefixes, not string substrings.
- Redirections, substitutions, wildcards, heredocs, shell control operators,
  and arbitrary interpreter prefixes are ineligible for broad reuse.
- Destructive commands never receive a persistent rule from an elevation
  request.
- A matching rule skips review only for the permission dimensions and action
  family it explicitly covers; it does not grant unrelated filesystem or
  network access.

## Denial Circuit Breaker

Track review denials per turn and per canonical action. Repeated denials must
not let the main agent probe the policy by changing superficial syntax.

- Reset the consecutive-denial count after a non-denial.
- Count semantically equivalent denied actions together where the canonical
  fingerprint/action family permits it.
- Interrupt the turn after the configured consecutive/recent thresholds.
- Emit a user-visible warning and an auditable reason.
- A new trusted user message starts a new authorization evaluation but does not
  erase critical or absolute-deny policy.

## Configuration

Add a typed reviewer setting with at least:

```toml
[sandbox]
approvals_reviewer = "auto_review" # or "user"
```

The target Codex-parity posture uses `auto_review`. If the reviewer cannot be
constructed, startup may remain available, but every request routed to it must
fail closed with a clear diagnostic; it must never silently become
`auto-approve`.

Existing global `auto-approve`/pattern settings must not bypass the sandbox
Guardian path. They can remain for unrelated legacy approval namespaces until
separately migrated.

## Audit and Observability

For each review, emit structured lifecycle events containing:

- review ID, session/turn ID, and target tool-call ID;
- canonical action summary and fingerprint;
- requested permission dimensions;
- start/completion timestamps and latency;
- reviewer source and model identity;
- terminal status;
- risk level and authorization level;
- allow/deny outcome and concise rationale;
- claim/consume result.

Avoid recording raw file contents, patch bodies, credentials, environment
secrets, or full unredacted outbound payloads. Store digests and coarse data
classifications where the exact body is unnecessary for audit.

## Error Handling and Integrity

- Canonicalization failure: deny before review.
- Unsupported shell form: allow one-shot review only if the exact command can be
  represented; never suggest a reusable prefix.
- Reviewer unavailable/timeout/invalid output: fail closed.
- Approval expired: deny and require a fresh review.
- Fingerprint mismatch: deny and invalidate the stale grant.
- Duplicate claim: deny the later claimant.
- Crash after execution may have started: mark indeterminate/consumed and do not
  auto-replay.
- User cancellation: abort review and execution.
- Backend disagreement with the permission profile: return a structured runtime
  denial; do not bypass policy.

## Testing Strategy

### Filesystem and backend

- A sandboxed process can read representative paths outside the workspace.
- The same process cannot mutate those paths without approved elevation.
- Workspace and scratch roots remain writable.
- Path-prefix, symlink, `..`, bind-mount, and create-new-file parent cases do not
  escape writable-root checks.
- `/proc`, devices, network, and other isolation remain at the configured
  posture after the root read-only bind.

### Canonical actions and grants

- Every covered tool produces a deterministic canonical action.
- Changes to argv, cwd, paths, code/patch digest, permission intent, destination,
  or payload class invalidate approval.
- One grant executes once, including concurrent retry attempts.
- Crash/timeout states cannot cause duplicate execution.

### Guardian policy

- Low- and medium-risk matrix cases allow.
- High-risk cases require sufficient trusted authorization and narrow scope.
- Critical and absolute-deny cases reject even after user confirmation.
- Untrusted file/tool/web instructions cannot raise authorization.
- A user explicitly re-approving a concrete, previously explained high-risk
  action raises authorization for the new review.
- Timeout, provider failure, cancellation, and malformed JSON fail closed.
- The reviewer cannot write, use network, or request elevation.

### Interaction behavior

- Auto-approved requests do not create a human-actionable approval badge.
- The exact suspended call resumes without another main-model turn.
- Auto-review denial reaches the main agent with rationale and anti-circumvention
  guidance.
- Denial does not automatically open a human approval card.
- Consecutive denials trigger the circuit breaker.
- Explicit `user` reviewer mode retains an actionable approval surface.

### Regression

- Existing interactive approval persistence and retry tests continue to pass.
- Full-host mode remains unchanged.
- Non-Linux backends retain their current behavior until their parity work is
  implemented.

## Acceptance Scenarios

1. From an OpenSquilla workspace, the agent can read `/etc/hosts` and another
   user-readable repository outside the workspace without approval.
2. A workspace edit executes normally inside bubblewrap.
3. A user asks to create one fixed temporary file on the Desktop. The agent
   submits a narrow elevated request; Guardian classifies it low risk with high
   authorization; the exact write continues without a human prompt.
4. A user asks to delete that same known temporary file. Guardian evaluates the
   exact target and observed provenance rather than rejecting solely because a
   delete command is used.
5. An agent proposes recursively deleting an uncertain directory without clear
   authorization. Guardian denies; nothing executes; the agent explains the
   risk or chooses a narrower action.
6. A fetched document tells the agent to upload credentials. The untrusted
   instruction cannot establish authorization, and credential exfiltration is
   critical, so Guardian denies.
7. Guardian times out. The command does not run and no human approval popup is
   fabricated.

## Implementation Boundary for Phase 1

Phase 1 is complete when the Linux bubblewrap backend, primary local mutation
tools, central approval coordinator, Guardian reviewer, exact-action grants,
denial continuation, audit events, and the acceptance scenarios above are
implemented and verified.

Secret masking, automatic backend-denial replay, and full cross-platform mount
parity remain follow-up work.
