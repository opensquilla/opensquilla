# Terminal Chat (TUI)

Terminal chat, also called the TUI, is the command-line chat surface for
OpenSquilla. Use it when you want an interactive conversation in a shell,
especially while working in a local project directory.

## Start Chat

Start the default terminal chat:

```sh
opensquilla chat
```

This uses the stable Python-native terminal backend. It does not require Bun,
npm, tmux, or OpenTUI dependencies.

If gateway-backed chat cannot connect, start the gateway first:

```sh
opensquilla gateway start --json
opensquilla chat
```

Use a specific model for the session:

```sh
opensquilla chat --model gpt-5.4-mini
```

Resume an existing session:

```sh
opensquilla chat --session <session-key>
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

## OpenTUI Preview

The default terminal chat is the supported path for normal use. OpenTUI is an
opt-in preview backend for evaluating a richer terminal UI from a source
checkout. It is not required for day-to-day terminal chat.

From a source checkout:

```sh
bun install --frozen-lockfile --cwd=src/opensquilla/cli/tui/opentui/package
OPENSQUILLA_TUI_BACKEND=opentui uv run opensquilla chat
```

Leave `OPENSQUILLA_TUI_BACKEND` unset to use the stable terminal chat.

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

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
