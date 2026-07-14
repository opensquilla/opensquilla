# Tools, Approvals, and Sandbox

OpenSquilla tools give the agent useful capabilities. Policy layers, approval
surfaces, workspace constraints, and sandbox posture control how those tools are
allowed to act.

Use this page before running unattended automation, file edits, shell commands,
or channel-connected agents.

For a focused permissions guide, see
[`approvals-and-permissions.md`](approvals-and-permissions.md).

## Built-In Tool Areas

| Area | Examples |
| --- | --- |
| Filesystem | `read_file`, `write_file`, `edit_file`, `list_dir`, `glob_search`, `grep_search`, spreadsheet reads. |
| Shell and code | `exec_command`, `background_process`, `process`, `execute_code`. |
| Git | `git_status`, `git_diff`, `git_log`, `git_commit`, `apply_patch`. |
| Web | `web_search`, `web_discover`, `web_fetch`, `http_request`. |
| Memory | `memory_search`, `memory_save`, `memory_get`, `memory_delete`. |
| Sessions | `sessions_send`, `sessions_spawn`, `sessions_list`, `sessions_history`, `session_status`. |
| Artifacts | `publish_artifact`. |
| Media | image generation, PDF, TTS, and media helpers. |
| Skills | `skill_list`, `skill_view`, `skill_create`, `skill_edit`, `install_skill_deps`, `meta_invoke`. |
| Admin | cron and gateway administration. |
| Channels/platforms | messaging and Feishu/Lark docs, chat, drive, wiki, media, and permission helpers. |

## Permission Modes

Use stricter modes when running unattended:

```sh
opensquilla agent --permissions restricted -m "Inspect this repo"
```

Use broader modes only when you trust the task and workspace:

```sh
opensquilla agent --permissions full --workspace /path/to/project -m "Run tests and fix failures"
```

For interactive work, the Web UI approvals surface can pause sensitive tool
calls for review. For automation, choose a permission mode and workspace policy
before the run starts.

Read: [`approvals-and-permissions.md`](approvals-and-permissions.md)

## Approval Flow

With the default `approvals_reviewer = "auto_review"`, an explicit
`require_escalated` tool call is reviewed by an independent Guardian model.
The review record is internal and does not appear as an actionable Web UI
approval. Configure `approvals_reviewer = "user"` only when a human approval
surface is intentionally required.

Elevation review covers:

- out-of-root filesystem writes and patches;
- exact shell commands and background processes;
- exact Python code execution;
- unknown managed-network targets;
- external channel or webhook delivery;
- generated artifacts that will be published;
- actions that affect another service.

The normal tool call uses `sandbox_permissions = "use_default"`. If it needs a
capability outside the active sandbox, the tool returns `elevation_required`
without queueing a review. The agent may then submit the exact same operation
with `sandbox_permissions = "require_escalated"` and a precise
`justification`. The runtime suspends that request during review and resumes
the same request exactly once after approval. Fingerprints provide integrity
and audit checks; they are not a substitute for continuation identity.

Guardian allows low/medium risk by default except for clear malicious prompt
injection. High risk requires at least medium authorization and narrow scope;
critical risk is denied by default, with the policy's narrow post-denial user
re-approval override for the exact action. Its reusable agent can inspect local state
with seven read-only filesystem/git tools, but has no mutation, shell, web,
plugin, skill, memory, MCP, or sub-agent tools. Review errors and timeouts fail
closed. A denial goes back to the agent for explanation or a safer proposal,
never to an automatic human-popup fallback.

## Workspace Controls

Read-side restriction:

```sh
opensquilla agent --workspace /path/to/project --workspace-strict -m "Summarize this repo"
```

Write containment:

```sh
opensquilla agent \
  --workspace /path/to/project \
  --workspace-lockdown \
  --scratch-dir /path/to/project/.scratch \
  -m "Investigate and prepare a minimal patch"
```

`--workspace-lockdown` is intended for automation where writes must stay inside
the workspace or scratch directory.

With the sandbox enabled, shell commands and direct filesystem tools use the
same filesystem permission profile. Linux and macOS expose the host filesystem
read-only except for explicit denied reads and normal OS permission failures.
Windows follows Codex's restricted-account projection: Windows and Program
Files roots, ProgramData, non-sensitive direct USERPROFILE children, the
operation working directory, helper runtime roots, and declared writable roots.

Only declared writable roots are writable without review. A write outside those
roots returns elevation_required. require_escalated submits the exact action to
Guardian; an allow executes that fingerprint once. A changed command, path,
content, create, or delete is a separate approval decision.

On Linux Bubblewrap, host `/` is mounted read-only by default. The workspace,
`/tmp`, `$TMPDIR`, and configured writable roots are overlaid read-write, with
top-level `.git`, `.agents`, and `.codex` carved back to read-only. There is no
default sensitive-path name blacklist in sandbox-on mode. Explicit denied-read
policy remains authoritative and prevents an unsandboxed override. On Windows,
the projection does not make every volume globally readable and excludes Codex's
sensitive profile children, including `.ssh`, `.gnupg`, `.aws`, `.azure`,
`.kube`, `.docker`, and `.config`.

## Sandbox Commands

```sh
opensquilla sandbox status
opensquilla sandbox on
opensquilla sandbox full
opensquilla sandbox bypass
opensquilla sandbox reset
```

Sandbox behavior is platform-dependent. Treat `sandbox status` and `doctor` as
the source of truth for the current machine.

Default Codex-aligned settings:

```toml
[sandbox]
sandbox = true
security_grading = true
host_root_readonly = true
approvals_reviewer = "auto_review"
approval_review_timeout_seconds = 90
approval_review_max_attempts = 3
exclude_slash_tmp = false
exclude_tmpdir_env_var = false
denied_read_roots = []
denied_read_globs = []
```

One review may make at most three attempts inside its single 90-second
deadline, retrying only parse errors and structured transient provider/session
failures. Three consecutive policy denials or ten denials in the latest fifty
reviews interrupt the turn.

The denied-read lists are optional explicit exceptions to global reads;
relative entries are workspace-relative, and active denies prevent an
unsandboxed override.

`require_escalated` is not a persistent permission mode, `approval_id` is not
model-visible, and automatic review never persists a proposed prefix rule.
Disabling the sandbox or selecting full host access retains the existing
full-host behavior.

The normal tool schema deliberately omits Codex features that are experimental
and disabled at the source baseline: additive permissions, a model-visible
permission-request tool, and patched-zsh child `execve` interception.

## Recommended Patterns

| Task | Recommended posture |
| --- | --- |
| Read-only repo summary | `--workspace` plus `--workspace-strict` |
| Local patch with tests | `--workspace`, `--workspace-lockdown`, and a scratch dir |
| Chat with possible writes | Web UI with approvals visible |
| Channel-connected agent | Conservative permissions and explicit channel config |
| Provider/debug investigation | Diagnostics on, minimal tool permissions |

## Web Safety

OpenSquilla web tools use provider configuration and guardrails. Use provider
diagnostics when web search behaves unexpectedly:

```sh
opensquilla search status
opensquilla search query "test query"
opensquilla diagnostics on
```

Search results and fetched pages are external data. They should inform the
answer, not override tool policy or user instructions.

For source-backed answers, `web_search` is the default high-level web tool.
`web_discover` is lightweight link discovery, `web_fetch` reads a specific
page, and `http_request` is reserved for raw HTTP/API requests.

## Tool Compression

Large tool results may be compacted before they are shown to the model. This is
normal and protects the active context window. See
[`features/tool-compression.md`](features/tool-compression.md).

## Artifacts and Media

Tool calls can publish artifacts and generate media. See
[`artifacts-and-media.md`](artifacts-and-media.md) for user-facing artifact,
document, image, PDF, and TTS workflows.

## Troubleshooting

If a tool does not run:

1. Check permission posture:

   ```sh
   opensquilla sandbox status
   opensquilla doctor
   ```

2. Check whether the gateway or channel surface requires approval.
3. Confirm the workspace path is correct.
4. Use diagnostics for repeated failures:

   ```sh
   opensquilla diagnostics on
   ```

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
