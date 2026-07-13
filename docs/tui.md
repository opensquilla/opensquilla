# Terminal Chat (TUI)

Terminal chat, also called the TUI, is the command-line chat surface for
OpenSquilla. Use it when you want an interactive conversation in a shell,
especially while working in a local project directory.

## Start Chat

Start terminal chat:

```sh
opensquilla chat --ui tui
```

The supported macOS and Linux RC keeps bare `opensquilla chat` on the minimal
`plain` renderer while `opensquilla chat --ui tui` opts into the packaged
full-screen host. `--ui auto` exercises the final startup policy and may fall
back to plain only before full-screen startup. After the RC gate and at least
seven days with no unresolved P0/P1 data, approval, input, or
terminal-restoration issue, the next rollout release changes the bare command
to `auto`. Release installs do not require Bun, npm, tmux, a source checkout,
or a first-run host download.

The packaged host is available on macOS arm64/x86_64 and Linux
arm64/x86_64. Native Windows needs its ConPTY host and remains an independent
platform follow-up; the session, history, approval, attachment, and UI-selection
contracts do not change for that release.

For the implicit local configuration, chat checks readiness before taking over
the terminal and starts the lifecycle-managed Gateway when necessary. An
explicit `OPENSQUILLA_GATEWAY_URL` is operator-owned: chat never starts a local
Gateway as a silent replacement.

You can still manage the local Gateway explicitly:

```sh
opensquilla gateway start --json
opensquilla chat --ui tui
```

Use a specific model for the session:

```sh
opensquilla chat --ui tui --model gpt-5.4-mini
```

Resume an existing session:

```sh
opensquilla chat --ui tui --session <session-key>
```

Choose the terminal presentation explicitly when diagnosing startup:

```sh
opensquilla chat --ui tui    # require packaged OpenTUI
opensquilla chat --ui plain  # minimal rescue renderer
```

Terminal chat is interactive and requires a real TTY. For scripts, pipes, CI,
or one-shot automation, use:

```sh
opensquilla agent -m "Inspect this workspace"
```

## Gateway and Standalone Modes

By default, `opensquilla chat` uses the gateway-backed chat path, so it shares
sessions, configuration, approvals, usage, and model/provider state with the Web
UI and other gateway clients.

Use standalone mode when you want direct terminal chat without the gateway
daemon:

```sh
opensquilla chat --standalone
```

Standalone mode accepts workspace flags for local file and tool work:

```sh
opensquilla chat --standalone --workspace /path/to/project --workspace-strict
```

In gateway mode, `--workspace` is ignored by terminal chat. Use a gateway-visible
path with `/path`, or use `/file` to upload a local file from the CLI machine.

## Common Commands

Type `/help` in terminal chat to see the commands supported by the current mode.

Commands available in both gateway and standalone chat include:

| Command | Purpose |
| --- | --- |
| `/help` | Show command help. |
| `/status` or `/session` | Show the active session and model. |
| `/new [title]` | Start a new session. |
| `/model [model]` | Show or change the active model. |
| `/cost` | Show usage for the current chat state. |
| `/clear` or `/reset` | Clear the current session context. |
| `/compact` or `/cmp` | Compact long context when possible. |
| `/save [path]` | Save the transcript. |
| `/image <path> [prompt]` | Send an image file with an optional prompt. |
| `/path <path> [prompt]` | Attach a file by path. |
| `/theme ...` | Change terminal theme settings when the active backend supports it. |
| `/quit` or `/exit` | Leave chat. |

Gateway-backed chat also supports session and operations commands:

| Command | Purpose |
| --- | --- |
| `/sessions [limit]` | List recent sessions. |
| `/resume <id>` | Resume a session. |
| `/delete <id>` | Delete a session. |
| `/models` | List available models. |
| `/usage` | Show aggregate usage. |
| `/meta` | List MetaSkills. |
| `/meta <name>` | Run a MetaSkill in the current session. |
| `/file <path> [prompt]` | Upload a local file and send it with a prompt. |
| `/permissions ...` | Inspect or change interactive permission mode. |
| `/approvals ...` | Inspect or reset approval state. |
| `/forget` | Clear remembered approvals. |

Standalone chat supports the core commands above, but `/models`, `/meta`, and
gateway-wide usage or approval commands require gateway mode.

## Files and Images

Use `/image` for image files:

```text
/image ./screenshot.png Describe the UI issue
```

Use `/path` when the file path is visible to the running chat process:

```text
/path ./docs/quickstart.md Summarize the setup steps
```

In gateway mode with a remote gateway, prefer `/file` so the CLI uploads the
local file before sending the turn:

```text
/file ./report.pdf Extract the action items
```

## TUI Host and Source Development

Release installers pair the platform-neutral OpenSquilla package with a
same-version, platform-specific TUI host. A missing or mismatched host is a
strict error under `--ui tui`; `--ui auto` may fall back before entering the
alternate screen. On macOS and Linux, install, upgrade, reinstall, and rollback
replace core and host together; mixing release versions is unsupported.

Maintainers can explicitly use the source host while developing:

```sh
bun install --frozen-lockfile --cwd=src/opensquilla/cli/tui/opentui/package
OPENSQUILLA_TUI_DEV_SOURCE_HOST=1 uv run opensquilla chat --ui tui
```

`OPENSQUILLA_TUI_BACKEND` is a compatibility/development override when `--ui`
is omitted. `OPENSQUILLA_TUI_DEV_SOURCE_HOST=1` is the explicit permission to
run Bun/source instead of an installed companion. Users should prefer the
public `--ui` option and the release installer.

Read [`features/tui-frontend.md`](features/tui-frontend.md) for OpenTUI backend
status, Router HUD details, and replay benchmarks. Read
[`tui-real-terminal-harness.md`](tui-real-terminal-harness.md) only when you are
running maintainer integration tests for terminal rendering.

## Related Pages

- [`cli.md`](cli.md) for the full CLI reference.
- [`sessions.md`](sessions.md) for listing, resuming, exporting, and deleting
  sessions.
- [`approvals-and-permissions.md`](approvals-and-permissions.md) for permission
  profiles and approval workflows.
- [`features/meta-skill-user-guide.md`](features/meta-skill-user-guide.md) for
  `/meta` workflows.
- [`features/tui-product-contract.md`](features/tui-product-contract.md) for
  ownership, shared-session, fallback, and legacy-freeze rules.

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
