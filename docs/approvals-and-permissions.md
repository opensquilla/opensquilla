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

With the sandbox enabled, shell commands and direct filesystem tools use the
same filesystem permission profile. Linux and macOS expose the host filesystem
read-only except for explicit denied reads and normal OS permission failures.
Windows follows Codex's restricted-account projection: Windows and Program
Files roots, ProgramData, non-sensitive direct USERPROFILE children, the
operation working directory, helper runtime roots, and declared writable roots.

Only declared writable roots are writable without review. A write outside those
roots returns elevation_required. require_escalated submits the exact action to
the configured reviewer; an allow executes that fingerprint once. A changed command, path,
content, create, or delete is a separate approval decision.

On Linux with the Bubblewrap backend, the default sandbox exposes the host
filesystem root (`/`) read-only. The workspace, configured scratch directory,
`/tmp`, `$TMPDIR`, and explicit writable mounts are overlaid as writable. The
top-level `.git`, `.agents`, and `.codex` paths under writable roots are
re-applied read-only. Direct filesystem and patch tools resolve the same
profile, so they cannot bypass the subprocess mount policy.

There is no built-in credential-path denylist while the sandbox is enabled.
On Linux and macOS, normal host paths, including `/home`, `/etc`, `~/.ssh`, and
`~/.aws`, are eligible for reads. The gateway process's operating-system
permissions remain authoritative: a file such as `/etc/shadow` is still
unreadable when the gateway user cannot read it. Explicit denied-read policy is
enforced across tools and disables unsandboxed escalation that would discard
the deny.

Windows does not expose every volume or excluded profile directory globally.
Its Codex projection excludes `.ssh`, `.tsh`, `.brev`, `.gnupg`, `.aws`,
`.azure`, `.kube`, `.docker`, `.config`, `.npm`, `.pki`, and `.terraform.d`
when those names are direct children of `USERPROFILE`.

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

This is intent for one canonical action, not a session mode. The runtime
suspends the original tool request while it is reviewed. Approval resumes that
same request object with internal continuation metadata; the main model is not
asked to invent a replacement call. A changed command, path, body, patch,
code, working directory, or destination is a new request and requires a new
review. An approved grant is consumed once. An optional `prefix_rule` is review
context only; automatic review never saves it as a durable rule.

Workspace lockdown, explicit denied reads, and write-deny policy run before
elevation review and cannot be bypassed by it. Protected project metadata is
read-only under `use_default`, but an exact `require_escalated` action can be
reviewed rather than being rejected by a hard-coded path rule.

### Automatic rule review

The default sandbox reviewer is `auto_review`. It is a local deterministic
rules engine: it does not call a model, create a reviewer agent session, add
provider cost, or wait for model retries. Every decision remains bound to the
canonical action fingerprint and can authorize that exact operation only once.

Managed Execution defaults to allow when no high-confidence hard-risk rule
matches, including unknown or unparsed operations. Hard-risk rules cover broad
or critical deletion, system/boot/disk damage, security weakening, mass
encryption, direct download-to-interpreter chains, obvious encoded execution,
and sensitive-data transfer to an external destination. Critical matches are
not automatically executed and are exposed for exact human confirmation where
an interactive approval surface exists. High-confidence sensitive upload shell
commands are blocked before execution. User-requested local access to sensitive
data is not treated as external transfer.

Malformed canonical actions and fingerprint mismatches fail closed. There are
no reviewer-model timeouts, provider failures, parse retries, or model fallback
paths in automatic review.

When a command first runs inside the sandbox and its output is narrowly
attributable to the sandbox (`permission denied`, `read-only file system`,
`SIGSYS`, or structured backend notes), OpenSquilla preserves that output,
performs a fresh review for the broader context, and internally retries the
same request once if allowed. A generic non-zero exit is never treated as a
sandbox denial.

If the selected subprocess backend is unavailable in Managed Execution, the
runtime uses the same exact one-shot review and host retry path instead of
returning a generic internal backend error. Standard mode remains fail-closed.

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
exclude_slash_tmp = false
exclude_tmpdir_env_var = false
denied_read_roots = []
denied_read_globs = []
```

Denied roots and globs are optional, empty by default, and relative values are
resolved from the active workspace. Any active denied-read rule disables the
unsandboxed override for that request.

The default tool contract intentionally exposes only `use_default` and
`require_escalated`; `approval_id` remains runtime-only continuation state and
is absent from model-visible schemas. Codex's experimental additive permissions, runtime
permission-request tool, and zsh child-`execve` interception remain disabled
and are not advertised by OpenSquilla.

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
