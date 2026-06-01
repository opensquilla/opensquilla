# OpenSquilla Sandbox Run Mode Design

Date: 2026-05-29

Revision: v2, 2026-06-01

## Goal

OpenSquilla should make sandbox behavior understandable, live-editable, and safer by default. The current `bypass` / `elevated` / `full` vocabulary mixes two different ideas: whether to ask the user, and where the command actually runs. This design separates those ideas, keeps normal work inside the sandbox, and gives users clear recovery paths when the sandbox needs more access.

The design follows the layered style used by Codex and Claude Code: permission decisions, sandbox execution, network/path boundaries, and user approvals are separate layers. It does not copy Claude Code's complex auto-classifier as a first step. OpenSquilla should first make deterministic policy, runtime state, and UI semantics correct.

The current UI has already started moving toward this model by showing an `Execution mode` row in Chat and an `Effective execution mode` summary in Approvals. Those surfaces still read and write the old elevated/bypass state, so this design treats them as migration targets rather than finished behavior.

## Non-Goals

- Do not implement a Claude-style broad auto classifier in this phase.
- Do not expose a general "open internet" switch for sandboxed execution.
- Do not make `Trusted-Sandbox` run commands on the host.
- Do not show host execution as a normal approval option before a sandbox attempt.
- Do not replace or rewrite the existing `tests/test_sandbox` suite. New tests may be added around the new behavior.
- Do not make Squilla Router session-scoped as part of this sandbox work. It can remain visible beside sandbox controls, but its existing config path stays out of the sandbox Run Context unless a separate router-session design is approved.

## Change Containment

The implementation should keep the code change footprint as narrow as possible while still completing the behavior described here.

The new model should live primarily inside `opensquilla.sandbox`: run-mode vocabulary, operation classification, grants, backend selection, path/domain validation, doctor/explain payloads, and legacy-mode mapping should be centralized there. Other areas should call into that boundary instead of re-implementing sandbox semantics.

Expected integration points are limited to the surfaces that must display, persist, or pass through sandbox state:

- CLI sandbox commands and single-shot permission flags
- gateway RPC endpoints for session Run Context and sandbox status
- Chat and Control UI sandbox surfaces
- approval payloads and approval decisions
- tool execution context fields that currently carry legacy `elevated` strings
- additive sandbox tests

Router, provider selection, memory, channels, scheduling, skills, artifacts, and unrelated control pages should not change behavior as part of this work. If an implementation step needs to touch those areas, the change should be a thin adapter or compatibility shim, not a feature rewrite.

## User-Facing Modes

OpenSquilla exposes three run modes:

| Run Mode | Execution Target | Approval Behavior |
| --- | --- | --- |
| `Standard-Sandbox` | Sandbox | Ask for ordinary risky actions |
| `Trusted-Sandbox` | Sandbox | Skip ordinary approvals, but still ask for boundary expansion |
| `Full Host Access` | Host | No per-command prompts |

The important product rule is that bypassing approvals is not the same as host execution. `Trusted-Sandbox` means "ask less while still sandboxed." `Full Host Access` is the only global mode that runs directly on the host.

Legacy wording should be mapped at the boundary:

- old `off` -> `Standard-Sandbox`
- old `bypass` -> `Trusted-Sandbox`
- old `full` -> `Full Host Access`
- old `on`, if it meant host execution with approval, should not be presented as a new user-facing mode

The core runtime should move toward `RunMode`, `ExecutionTarget`, `ApprovalBehavior`, `OperationProfile`, and `Grant` concepts instead of spreading old `elevated` semantics further.

## CLI Run Mode Commands

The CLI should use the same three-mode semantics as the frontend, but keep the short command style OpenSquilla already uses. The command should feel like the existing `opensquilla sandbox on/full/status/reset` family, not like a second verbose UI vocabulary.

Recommended canonical commands:

| CLI | Meaning | Config Effect |
| --- | --- | --- |
| `opensquilla sandbox on` | default new chats to `Standard-Sandbox` | sandbox on, ordinary approvals on |
| `opensquilla sandbox trust` | default new chats to `Trusted-Sandbox` | sandbox on, ordinary approvals skipped |
| `opensquilla sandbox full` | default new chats to `Full Host Access` | sandbox off, host execution |

`opensquilla sandbox status` should display the global default Run Mode, backend availability, network/domain guard state, and whether a gateway restart or live reload is still needed. It should stop presenting the primary state as old `posture=bypass`.

Compatibility aliases can remain for scripts, but their output should say what they now mean:

| Alias | New Meaning |
| --- | --- |
| `opensquilla sandbox trusted` | alias for `trust` |
| `opensquilla sandbox bypass` | deprecated alias for `trust`, not host execution |
| `opensquilla sandbox reset` | reset to `on` unless a separate install-profile decision says otherwise |

Do not add a prominent `sandbox off` command. If old config or slash-command code sees `off`, treat it as legacy "normal sandboxed approvals" and map it to `Standard-Sandbox`; do not teach users that "off" is a safe label for the new model.

CLI default changes affect new chats and future gateway starts. They must not silently rewrite an existing chat's saved Run Context; the resume/restart rules below still apply.

## Frontend Placement

The app now has a global topbar center slot that Chat uses for session identity and run status. That topbar slot should remain mostly read-only: it may show current state, but it should not become the primary sandbox configuration surface.

The chat composer gear remains the quick control for the current chat session. It should stay very light and only expose controls that users naturally toggle while composing a message:

- `Run Mode`
- `Squilla Router`
- `Visual effects`

`Run Mode` is the only sandbox control in the composer gear. `Squilla Router` stays in the same popover for convenience but continues to use the existing router configuration path. `Visual effects` is a local UI preference and is not part of sandbox policy.

Workspace switching, mount management, allowed domains, and sandbox diagnostics belong in the `Control -> Sandbox` page or in contextual prompts such as Path Access Request. The composer gear should not include `Workspace` or `Open Sandbox...`.

Advanced sandbox management belongs in a new sidebar page:

`Control -> Sandbox`

The page should sit near `Health`, because it is a runtime control and diagnostic surface, not just raw configuration. `Settings -> Config` remains the place for low-level defaults and advanced raw config.

The UI style should match the current OpenSquilla control-center look: restrained, compact, and clear. The primary surface should avoid long explanatory text; detailed meaning should live in hover tooltips, row details, and "Why?" explain panels.

## Sandbox Page

The `Sandbox` page is the productized control center for execution boundaries.

It should be registered as a standard Control view, using the same standard view wrapper as Overview, Health, Config, and Approvals. This matters because standard views clear Chat-specific topbar center content when the user leaves Chat.

### Status

Shows whether sandboxing is actually available:

- backend: bubblewrap, seatbelt, noop
- state: ready, degraded, disabled
- network guard state
- last check time
- refresh action
- doctor findings and repair hints

If a required backend or network guard is missing, the page should say that plainly. Users should not have to infer whether "sandbox on" is real.

### Workspace

Manages the active session workspace:

- current workspace
- change workspace
- recent workspaces
- use default workspace

The chat gear may offer quick switching, but full management lives here.

### Mounts

Manages additional directories visible inside the sandbox:

- path
- access: read-only or read-write
- scope: this chat or this workspace
- state: active, blocked, needs review
- remove action

Default access is read-only. Read-write access requires a clearer user decision and must pass backend validation.

### Allowed Domains

Manages narrow network permissions:

- explicit domains
- package-install domain bundles
- scope: this chat or this workspace
- source: manually added or approved during execution
- remove action

This section should not be labeled as a general "Network" mode and should not expose "open internet" as a sandbox option.

### Rules & Activity

Combines durable grants and recent activity:

- `Always Allow This Type` rules
- denied rules
- recent blocks
- Host Once history
- explanation detail
- revoke action

This is the main entry point for understanding why a specific operation was allowed, denied, or paused.

## Run Context

The gateway should keep a session-scoped `Run Context`. It is the current runtime card for a chat session:

- run mode
- workspace
- mounted directories
- allowed domains and domain bundles
- recent sandbox doctor summary
- temporary grants

Changes from the chat gear or Sandbox page update the session Run Context and apply to future tool calls without restarting the gateway. They do not affect already-running commands.

Squilla Router can remain visible in the same composer popover, but it is not owned by sandbox Run Context in this phase. Router continues to use the existing router configuration mechanism unless another design explicitly makes router behavior session-scoped.

Default scopes should be narrow:

| Item | Default Scope | May Expand To |
| --- | --- | --- |
| Run Mode | current chat | global default for new chats, or explicit user reset |
| Workspace | current chat | recent workspace |
| Mount | current chat | current workspace |
| Domain | current chat | current workspace |
| Package domain bundle | current workspace | not global by default |
| Host Once | one execution | never persistent |

## Resume And Restart Semantics

A chat's Run Context should behave like part of the chat, not like a live mirror of the latest global gateway default.

The global default only initializes new chats. Once a chat has a Run Context, reopening that chat after a gateway restart should load the chat's saved Run Context first. If the user created a chat under `Standard-Sandbox`, then later restarts the gateway with a looser default such as `Full Host Access`, the old chat still semantically remains `Standard-Sandbox` until the user explicitly changes that chat.

Legacy or migrated chats may not have a saved Run Context. Those chats should initialize from the current global default once, and explain/audit should record that the value came from migration/default initialization rather than an explicit old chat setting.

Current gateway capability still bounds execution. If a saved chat asks for sandbox execution but the current gateway has sandboxing disabled, unavailable, or degraded below the required level, OpenSquilla should enter a mismatch state and fail closed. It must not silently run the old sandbox chat on the host.

The rule is asymmetric:

- if current gateway policy is stricter than the saved chat context, the stricter policy can pause or constrain execution;
- if current gateway policy is looser than the saved chat context, the old chat must not silently loosen.

The mismatch UI should offer explicit recovery actions:

- Re-enable Sandbox
- Switch This Chat to `Full Host Access`
- Keep Blocked
- Start New Chat With Current Default

Example status text:

> This chat was last configured as `Standard-Sandbox`, but sandbox is disabled in the current gateway.

In short: an existing chat keeps its saved mode; execution proceeds only when the current gateway can satisfy that mode or the user explicitly changes the chat.

## Tool Execution Flow

Every tool call should pass through the same conceptual pipeline:

1. Load the session Run Context.
2. Build an Operation Profile from the tool call, arguments, command text, and hints.
3. Preflight path and domain boundaries.
4. Resolve policy from Run Context plus Operation Profile.
5. Execute in the sandbox or host according to the resolved target.
6. If sandbox execution fails, classify the failure.
7. Only if the failure appears sandbox-related, offer Host Once.
8. Record explain/audit information.

`Standard-Sandbox` and `Trusted-Sandbox` both execute in the sandbox. `Full Host Access` executes on the host.

Approving a risky operation should not implicitly become permission to run that operation on the host. Approval answers "may this operation proceed under the resolved policy." Host execution is allowed only by `Full Host Access` or by a Host Once grant created after a sandbox-related failure.

## Platform Backend Strategy

OpenSquilla should keep the same conceptual backend shape across platforms: policy decides what should be visible, then the platform backend enforces that boundary. A backend is not just "how to start a process"; it is the mechanism that makes filesystem, network, environment, and process limits real.

Recommended backend mapping:

| Platform | Primary Backend | Product Meaning |
| --- | --- | --- |
| Linux | bubblewrap + process limits + network guard | native sandbox |
| macOS | Seatbelt profile + process limits + network guard | native sandbox |
| WSL2 | Linux backend from inside WSL2 | treat as Linux if dependencies pass doctor |
| native Windows | Windows restricted-token backend | native sandbox, in scope now |
| no supported backend | fail closed when sandbox is required | never silent noop |

For native Windows, the best fit is the Codex-style restricted-token backend, adapted behind OpenSquilla's existing Python `Backend` interface. Codex's design is the closest match because it keeps execution native to Windows while still creating an OS-level boundary: restricted tokens, capability/ACL-based filesystem roots, Windows Filtering Platform network control, dedicated setup/refresh helpers, private desktop support, and Job Object lifecycle control.

This Windows backend is part of the current implementation scope, not a future roadmap item. Claude Code is still useful here as a safety lesson: its native Windows PowerShell path treats sandboxing as unavailable and refuses execution when policy requires sandboxing. OpenSquilla should copy that fail-closed behavior while setup is missing, broken, or incomplete.

OpenClaw's Docker backend is useful as an optional future backend, especially for users who already run Docker Desktop. It should not be the default native Windows answer for OpenSquilla because it changes the execution environment into a container, complicates Windows path and PowerShell workflows, and adds a heavy dependency. Docker is a good operational sandbox; it is not the cleanest default fit for a Windows-native local assistant.

The Windows backend should be exposed as something like `windows_restricted_token` and selected by `backend=auto` only when doctor confirms it is installed and usable. It should provide:

- restricted-token process launch, ideally through a small helper executable instead of spreading Win32 API calls through the Python gateway;
- workspace and mount enforcement through ACL/capability roots, with deny rules for credentials and sensitive paths;
- network denial or allowlist/proxy enforcement through Windows Filtering Platform or an equivalent account/process-scoped mechanism;
- Job Object controls for kill-on-close, process-tree cleanup, and resource limits where available;
- environment allowlisting equivalent to the Unix backends;
- setup and doctor output that clearly says whether the helper, accounts, ACL state, and network filters are healthy.

During rollout, native Windows with `Standard-Sandbox` or `Trusted-Sandbox` should fail closed whenever `windows_restricted_token` is unavailable, not installed, unhealthy, or unable to enforce the requested policy. It must not fall back to `noop` or host execution just because the user asked for sandbox mode.

## Operation Profile And Hints

OpenSquilla already has hint-like fields, but they should become inputs to operation classification rather than unused metadata. A hint should never directly authorize a tool call.

An Operation Profile describes what the call is trying to do:

- tool: shell, file read, file write, web fetch, package manager
- operation: read, write, delete, install dependencies, start service, access network, modify config, unknown
- target: workspace, mounted directory, external path, sensitive path
- network: none, allowed domain, unknown domain, private network, metadata endpoint
- risk: low, medium, boundary, sensitive, destructive, unknown
- confidence: recognized, partial, unknown
- hints used as supporting evidence

Hints affect classification:

- `needs_network` triggers domain checks.
- `writes_outside_workspace` triggers mount or rejection paths.
- `high_impact` raises risk.
- `crosses_trust_boundary` forces a boundary-expansion decision even in `Trusted-Sandbox`.
- `trusted_source` may reduce false positives, but cannot bypass sensitive paths, unknown domains, or host fallback checks.

Unknown operations are not low risk. They should be classified conservatively:

- `unknown_normal`: no obvious danger; may run sandboxed, with approval in `Standard-Sandbox`.
- `unknown_suspicious`: sudo, downloaded script execution, base64 execution, credential references, docker socket, or similar; ask strongly or reject.
- `unknown_sensitive`: sensitive paths, credentials, system dirs, local metadata, or unsafe mounts; reject by default.

## Approval Matrix

| Operation Class | Standard-Sandbox | Trusted-Sandbox | Full Host Access |
| --- | --- | --- | --- |
| normal read | run sandboxed | run sandboxed | run on host |
| normal workspace write | run sandboxed | run sandboxed | run on host |
| medium risk | ask, then sandbox | run sandboxed | run on host |
| boundary expansion | ask | ask | run on host |
| sensitive or destructive | reject or strong ask | reject or strong ask | run on host |

Boundary expansion includes:

- adding a new mount
- allowing a new domain
- allowing a package-install domain bundle
- changing a mount from read-only to read-write
- creating an `Always Allow This Type` rule
- Host Once fallback

Normal approvals should offer:

- Approve Once
- Always Allow This Type
- Deny
- Deny This Type

`Always Allow This Type` must bind to the Operation Profile, not just the tool name. A useful grant includes the tool, operation kind, target scope, execution target, network need, workspace or session, and expiry/scope. Approving one shell command must not approve every future shell command.

Current approval surfaces also need migration. `ApprovalsView` and the global approval modal should stop offering `Bypass Approvals` as `elevatedMode=bypass`. If a shortcut remains, it should be framed as switching the session to `Trusted-Sandbox`, and it must keep execution sandboxed.

The Approvals page may keep an execution-mode summary, but it should read the new Run Context instead of old elevated/localStorage state.

## Host Once

Host Once is a recovery action, not a run mode.

It appears only after:

- the operation was first attempted in the sandbox
- the failure looks sandbox-related
- the original operation profile still matches
- the operation is eligible for host fallback

The approval should show:

- original command or action
- sandbox failure reason
- paths and domains involved
- why sandbox execution cannot continue

Options:

- Run on Host Once
- Keep Blocked

The grant is fingerprint-bound to the original operation and consumed after one execution. It is never saved as a durable rule.

## External Path Access

If the user asks to inspect or modify an absolute path outside the current sandbox view, OpenSquilla should not jump to host execution. It should first ask whether to add a mount.

Example: the user says "look at `/home/usr1/1`."

Flow:

1. Detect that the path is outside the current workspace and mounts.
2. Validate the path.
3. If safe, ask a Path Access Request.
4. Default to read-only for inspect/analyze/search intent.
5. Offer read-write only when the user clearly asks to modify.
6. Mount the path and continue sandboxed.

If the path is sensitive, explain why it cannot be mounted. If the path does not exist, ask whether to mount the nearest safe parent or create a file inside the current workspace instead.

## Cross-Platform Path Validation

Path validation must be server-side and cross-platform. It cannot rely on string matching alone.

Required normalization:

- expand user home markers
- normalize absolute paths
- resolve symlinks
- inspect ancestor directories
- distinguish files, directories, sockets, and special files
- handle case-insensitive filesystems
- handle Windows drive letters
- handle UNC and network paths
- handle Windows junctions and reparse points
- handle WSL path translations
- handle macOS `/private` path aliases
- handle container path mapping when host and sandbox paths differ

Always reject ordinary mounts to:

- filesystem root
- `/etc`, `/proc`, `/sys`, `/dev`, `/boot`
- Docker or Podman sockets
- SSH and GPG credential directories
- cloud credential directories for AWS, GCP, Azure, Cloudflare, and similar
- GitHub CLI or Git credential stores
- browser profiles
- password manager stores
- system keychains and private certificate stores
- shell history and token caches

High-risk paths may be allowed read-only after confirmation, but read-write requires strong confirmation:

- user home root
- large parent directories
- Desktop and Downloads
- `.config`
- `.git`
- project-external source trees
- directories with `.env`, `credential`, `secret`, `token`, or similar signals

Safe paths include normal project directories, sibling project directories, and temporary work directories, after normalization and ancestor checks.

If validation is uncertain, fail closed.

## Allowed Domains

Sandboxed execution should not get arbitrary network access. OpenSquilla should expose `Allowed Domains`, not a general network mode.

In the first implementation slice, Allowed Domains apply to sandboxed shell/code/package-manager egress and package-install bundles. Existing explicit network tools that currently use the network action path, such as `web_fetch` or `http_request`, should keep their current `network.http` behavior unless a separate migration explicitly brings them under domain approval. This keeps existing sandbox network tests stable while still improving the highest-risk shell/code egress path.

Rules:

- allow explicit domains
- optionally allow controlled wildcard subdomains such as `*.example.com`
- do not treat `*.example.com` as allowing `example.com` unless both are present
- reject top-level or overly broad wildcards such as `*.com`
- reject private networks and localhost by default
- reject metadata services by default
- reject raw IP access by default unless explicitly supported by a separate high-risk flow
- re-check DNS resolution to avoid domains pointing at private networks
- re-check redirects; redirects to unapproved domains must pause again
- prefer HTTPS; HTTP requires clearer warning

When a sandboxed operation reaches an unknown domain, the user may choose:

- Allow Once
- Always Allow This Domain for This Workspace
- Deny
- Deny This Domain

`Trusted-Sandbox` may skip ordinary tool approvals, but unknown domains remain boundary expansion and still ask.

## Package Install Domain Bundles

Package managers often need several well-known domains. Asking for every domain during `pip install` or `npm install` would be noisy, so OpenSquilla should support narrow domain bundles.

Examples:

- Python package indexes: `pypi.org`, `files.pythonhosted.org`
- Node package registry: `registry.npmjs.org`
- Rust crates: `crates.io`, `static.crates.io`
- Go modules: `proxy.golang.org`, `sum.golang.org`
- GitHub release/source download: only when needed by the operation ecosystem

A bundle grant is scoped to:

- workspace
- operation kind
- package ecosystem
- sandbox execution

It is not a global network permission. It does not allow arbitrary shell network access.

## Doctor And Explain

Doctor is a health check for sandbox capability. It does not grant permission.

Doctor should be visible through:

- CLI doctor command
- Health page summary
- Sandbox page Status section

Explain is operation-specific. It answers why something ran, asked, failed, or was blocked.

Explain should appear in:

- approval requests under a "Why?" affordance
- Sandbox page activity details
- audit logs

Examples:

- "This path is outside the current workspace, so OpenSquilla needs a mount before it can stay sandboxed."
- "This domain is not currently allowed for this workspace."
- "Host Once is available because sandbox execution failed due to a sandbox restriction."

## Testing Strategy

The existing sandbox tests are the baseline and should not be rewritten or loosened. New tests may be added alongside them to cover new behavior.

Additive test coverage should include:

- `Trusted-Sandbox` resolves to sandbox execution, never host execution.
- `Full Host Access` is the only global host execution mode.
- CLI `sandbox trust` maps to `Trusted-Sandbox` and keeps sandbox execution enabled.
- CLI `sandbox bypass` remains only as a deprecated alias for `trust`.
- CLI `sandbox full` is the only canonical CLI path to `Full Host Access`.
- ordinary approval payloads do not contain Host Once.
- Host Once appears only after a sandbox-related failure.
- Host Once grants are one-use and fingerprint-bound.
- approving a normal risky operation does not implicitly switch execution to host.
- Chat Run Mode changes no longer send `elevatedMode=bypass` for `Trusted-Sandbox`.
- Approvals and global approval modal no longer use bypass to imply host execution.
- external paths trigger Path Access Request before host fallback.
- sensitive paths cannot be mounted through symlinks, case tricks, ancestors, junctions, or WSL/Windows path variants.
- unknown operations do not become low risk by default.
- hints influence Operation Profile classification but cannot directly authorize.
- unapproved domains pause or fail closed.
- package install bundles are limited to the matching ecosystem and workspace.
- explicit network-tool tests keep their existing expectations unless a dedicated network-tool migration is approved.
- session Run Context changes apply to the next call without gateway restart.
- old chats with saved `Standard-Sandbox` do not become host/full when the global default later changes to `Full Host Access`.
- saved sandbox Run Context with sandbox unavailable or disabled produces mismatch/fail-closed behavior, not host execution.
- legacy chats without saved Run Context initialize from the current global default and record that source.
- stricter current gateway policy can constrain saved session context; looser policy cannot silently expand it.
- sandbox-enabled execution does not silently degrade to noop unless an explicit, documented user setting allows that posture.
- native Windows sandbox execution uses `windows_restricted_token` when available.
- native Windows with sandbox required fails closed when `windows_restricted_token` is missing, unhealthy, or cannot enforce the requested policy.
- WSL2 uses the Linux backend path only when Linux sandbox dependencies pass doctor.
- Docker is not selected as the default Windows backend unless a separate explicit Docker-backend design is approved.

## ROI

### P0

1. Replace `bypass/elevated` user semantics with the three Run Modes.
2. Migrate CLI sandbox commands to the short OpenSquilla-style commands `on`, `trust`, and `full`, with `bypass` kept only as a deprecated alias.
3. Add session Run Context so frontend changes apply without gateway restart.
4. Migrate Chat composer gear from old `Execution mode`/bypass behavior to `Run Mode`, while preserving Router and Visual effects and avoiding Workspace/Sandbox-page shortcuts in the composer.
5. Migrate Approvals and global approval modal away from `Bypass Approvals -> elevatedMode=bypass`.
6. Add external path mount requests with cross-platform validation.
7. Make Host Once a sandbox-failure-only fallback.
8. Add native Windows `windows_restricted_token` backend support and fail closed with doctor/explain when setup is missing or unhealthy.

### P1

9. Make Operation Profile and hints drive policy classification.
10. Add Allowed Domains and package-install domain bundles for sandboxed shell/code/package-manager egress.
11. Add `Control -> Sandbox` page.
12. Add doctor/explain surfaces for sandbox status and decisions.

### P2

13. Strengthen backend isolation with resource limits, `no_new_privs`, seccomp or platform equivalents, and better fail-closed behavior.
14. Consider worktree/session isolation for coding workflows.

### P3

15. Defer broad Claude-style auto classification until deterministic policy and UI semantics are stable.

## Implementation Planning Notes

- Session Run Context should use gateway runtime/session state first and persist enough state to survive gateway restarts. Global defaults initialize new chats; they do not overwrite saved chat context.
- Workspace-scoped grants should use the same persistence boundary as existing approval settings unless implementation planning finds a narrower local store already exists.
- CLI posture commands should keep the existing short-command style. `on`, `trust`, and `full` are the canonical commands; `trusted` and `bypass` are aliases. They should not introduce a fourth mode.
- Keep old `elevated` strings at compatibility boundaries only. New policy code should reason in Run Mode, execution target, approval behavior, operation profile, and grant scope.
- The Windows backend should be introduced as a new backend adapter plus helper boundary, not by spreading Windows-specific process, ACL, or firewall code through unrelated tools.
- Migration should update all user-facing old-mode copy: Chat composer, Approvals, global approval modal, Config help, slash command help, API errors, and tool context comments.
- The first package bundle slice should cover Python, Node, Rust, and Go package managers. GitHub release/source downloads should be added only where a recognized package operation needs them.
- Cross-platform path validation should have platform-neutral unit tests using path resolver abstractions plus platform-specific tests gated by OS where the behavior depends on Windows junctions, UNC paths, drive letters, WSL mapping, or macOS `/private` aliases.
