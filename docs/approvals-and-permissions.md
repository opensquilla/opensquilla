# Approvals and Permissions

Approvals and permissions control how OpenSquilla tools are allowed to act.
They matter most when an agent can write files, run shell commands, publish
artifacts, post into channels, or call external services.

Use this page before running unattended automation or giving a channel-connected
agent broad tool access.

## Permission Profiles

Single-shot automation accepts an explicit permission profile:

```sh
opensquilla agent --permissions restricted -m "Inspect this repo"
opensquilla agent --permissions on -m "Run with host execution and approvals"
opensquilla agent --permissions bypass -m "Trusted local automation"
opensquilla agent --permissions full -m "Fully trusted local automation"
```

Practical meaning:

| Profile | Use when |
| --- | --- |
| `restricted` / `off` | The task should stay conservative and avoid elevated execution. |
| `on` | Host execution is allowed, but approval checks still matter. |
| `bypass` | You trust the task enough to auto-grant approvals while keeping sensitive-path checks. |
| `full` | You fully trust the task and environment. Use sparingly. |

For automation, prefer the narrowest profile that can complete the task.

## Workspace Containment

Set a workspace for file and shell work:

```sh
opensquilla agent \
  --workspace /path/to/project \
  --workspace-strict \
  -m "Summarize this repo"
```

Contain writes to the workspace or scratch directory:

```sh
opensquilla agent \
  --workspace /path/to/project \
  --workspace-lockdown \
  --scratch-dir /path/to/project/.scratch \
  -m "Investigate and prepare a minimal patch"
```

Use `--workspace-lockdown` for unattended runs where accidental writes outside
the project would be unacceptable.

## Interactive Approvals

Interactive chat surfaces can pause sensitive tool calls for a human decision.
Gateway-backed terminal chat supports:

```text
/approvals
/approvals reset
/permissions status
/permissions on
/permissions off
/permissions bypass
/permissions full
/forget
```

Use these commands when you need to inspect or reset cached approval decisions
during a chat.

The Web UI also provides an approvals surface for reviewing pending actions
outside the message scrollback.

## Sandbox Posture

Inspect sandbox posture:

```sh
opensquilla sandbox status
opensquilla sandbox status --json
```

Set posture:

```sh
opensquilla sandbox on
opensquilla sandbox bypass
opensquilla sandbox full
opensquilla sandbox reset
```

Restart the gateway after changing global sandbox posture:

```sh
opensquilla gateway restart
```

### Sandboxed read and write boundaries

On Linux with the Bubblewrap backend, the default sandbox exposes the host
filesystem root (`/`) read-only. The workspace, configured scratch directory,
and explicit writable mounts are overlaid as writable. This lets coding agents
inspect normal host files without making the entire host writable. Host OS
permissions and any stricter sensitive-path or deny rules still apply.
For example, ordinary system files such as `/etc/hosts` are readable, while
credential and privilege material such as `/etc/shadow`, `/etc/sudoers*`, and
`/etc/ssh` remains blocked.

An ordinary tool call cannot write outside those writable roots. Shell,
filesystem, patch, and Python tools first return `elevation_required`; they do
not silently add a read-write mount or replay a failed sandbox command on the
host.

### Exact one-operation elevation

When the user's request requires an out-of-root mutation, the agent can retry
the exact call with:

```text
sandbox_permissions = "require_escalated"
justification = "Create the one fixed file requested by the user."
```

This is intent for one canonical action, not a session mode. The approval is
bound to the command or tool, effective working directory, target paths,
content/patch/code digest, relevant network destinations, and other material
side effects. A changed command, path, body, patch, or code digest requires a
new review. An approved grant is consumed once. An optional `prefix_rule` is
review context only; automatic review never saves it as a durable rule.

Sensitive-path blocks, workspace lockdown, write-deny globs, and protected
metadata checks run before elevation review and cannot be bypassed by it.

### Automatic Guardian review

The default sandbox reviewer is `auto_review`. It makes a separate, no-tools
model call using the exact canonical action and a trust-labelled conversation
projection. Tool output, fetched pages, files, and assistant text cannot count
as user authorization.

The reviewer classifies both risk and user authorization:

| Classification | Automatic outcome |
| --- | --- |
| Low or medium risk | May be allowed when the action is supported by trusted user intent. |
| High risk | Requires at least medium authorization and a narrow, bounded scope. |
| Critical risk | Always denied. |

Timeouts, provider errors, invalid output, cancellation, and fingerprint
mismatches fail closed. A completed denial is returned to the agent with its
rationale; it does not become a human approval card. The agent must choose a
safer/narrower action or explain the risk and obtain a new explicit user
instruction before retrying. Three completed model denials in one turn open a
circuit breaker against repeated probing.

Automatic network decisions follow the same route. An allow creates only a
fingerprint-bound, `allow_once` grant for the current target; it never selects
`allow_same_type` or persists a domain/package rule.

To use the legacy human reviewer deliberately, configure:

```toml
[sandbox]
approvals_reviewer = "user"
```

The relevant automatic-review defaults are:

```toml
[sandbox]
host_root_readonly = true
approvals_reviewer = "auto_review"
approval_review_timeout_seconds = 20
approval_review_max_attempts = 3
```

These rules apply only while the sandbox is enabled. Full-host/sandbox-off mode
keeps its existing coarse-grained behavior.

## Recommended Defaults

| Situation | Recommended approach |
| --- | --- |
| First run in a repo | `--workspace` plus `--workspace-strict` |
| Read-only investigation | `--permissions restricted` |
| Local patch with tests | `--workspace-lockdown` plus a scratch directory |
| Web UI task with writes | Keep approvals visible and review sensitive actions |
| Channel-connected agent | Conservative permissions and explicit channel setup |
| Unattended automation | Bound timeout/iterations and choose the narrowest workable permissions |

## Troubleshooting

If a tool is denied:

```sh
opensquilla sandbox status
opensquilla doctor
```

Then check:

- whether the surface supports live approvals;
- whether the workspace path is correct;
- whether cached approvals need to be reset;
- whether the task should run with a different permission profile.

Read next:

- [`tools-and-sandbox.md`](tools-and-sandbox.md)
- [`web-ui.md`](web-ui.md)
- [`channels.md`](channels.md)

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
