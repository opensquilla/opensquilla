# CLI Reference

The `opensquilla` CLI is the fastest way to configure, run, inspect, and
automate OpenSquilla.

Run:

```sh
opensquilla --help
opensquilla <command> --help
```

## Main Commands

| Command | Purpose |
| --- | --- |
| `opensquilla init` | Initialize a workspace. |
| `opensquilla doctor` | Diagnose readiness and print recovery steps. |
| `opensquilla onboard` | Run or inspect first-run setup. |
| `opensquilla configure` | Reconfigure provider, router, channels, search, image generation, or memory embedding. |
| `opensquilla gateway` | Run and manage the gateway server. |
| `opensquilla chat` | Start interactive terminal chat. |
| `opensquilla agent` | Run a single automation-friendly agent turn. |
| `opensquilla sessions` | List, inspect, resume, abort, delete, or export sessions. |
| `opensquilla skills` | List, search, view, install, update, publish, and inspect skills. |
| `opensquilla memory` | Inspect and maintain memory. |
| `opensquilla channels` | Configure and inspect messaging channels. |
| `opensquilla providers` | Configure and inspect LLM providers. |
| `opensquilla search` | Configure and use web search. |
| `opensquilla sandbox` | Inspect or change default sandbox posture. |
| `opensquilla cron` | Manage scheduled OpenSquilla runs. |
| `opensquilla cost` | Inspect usage and estimated cost. |
| `opensquilla diagnostics` | Enable or disable runtime diagnostics logging. |
| `opensquilla replay` | Replay a recorded turn from the decision log. |
| `opensquilla migrate` | Import state from external agent runtimes. |
| `opensquilla models` | Inspect available models. |
| `opensquilla agents` | Manage durable agents. |
| `opensquilla mcp-server` | Run the OpenSquilla MCP server bridge. |
| `opensquilla dist` | Emit a reproducible workspace-state inventory. |
| `opensquilla reset` | Reset a session and flush memory synchronously. |

## Run Surfaces

Web UI and gateway:

```sh
opensquilla gateway run
opensquilla gateway start --json
opensquilla gateway status
opensquilla gateway restart
opensquilla gateway stop
```

Terminal chat:

```sh
opensquilla chat
opensquilla chat --model gpt-5.4-mini
opensquilla chat --session <session-key>
opensquilla chat --standalone --workspace /path/to/project
```

One-shot automation:

```sh
opensquilla agent -m "Review the current directory"
opensquilla agent --json -m "Return a short machine-readable summary"
opensquilla agent --workspace /path/to/project --workspace-strict -m "Inspect this repo"
opensquilla agent --timeout 600 --max-iterations 30 -m "Run a bounded investigation"
```

Useful automation flags:

| Flag | Purpose |
| --- | --- |
| `--workspace` | Set the workspace root. |
| `--workspace-strict` | Restrict read-side file tools to the workspace. |
| `--workspace-lockdown` | Contain writes to workspace or scratch directory. |
| `--scratch-dir` | Place temporary scripts/logs/candidate patches in a known directory. |
| `--timeout` | Set total agent wall-clock timeout. |
| `--max-iterations` | Bound the model/tool loop. |
| `--max-provider-retries` | Bound transient provider retries. |
| `--length-capped-continuations` | Bound automatic continuations after length-limited provider output. |
| `--thinking` | Override reasoning level. |
| `--permissions` | Select restricted, bypass, or full permission posture. |
| `--transcript-path` | Write a JSONL transcript for automation. |
| `--usage-path` | Write usage JSON. |
| `--session-db-path` | Persist session replay across invocations. |

## Configuration Commands

Provider and router:

```sh
opensquilla onboard
opensquilla onboard status
opensquilla configure provider --provider openrouter --api-key-env OPENROUTER_API_KEY
opensquilla configure router --router recommended
opensquilla providers list
opensquilla providers configure openrouter
opensquilla providers status
```

Search:

```sh
opensquilla search list
opensquilla search configure duckduckgo
opensquilla search query "latest OpenSquilla release"
opensquilla configure search --search-provider duckduckgo
```

Channels:

```sh
opensquilla channels types
opensquilla channels describe telegram
opensquilla channels add telegram --name personal
opensquilla channels list
opensquilla channels status
opensquilla channels enable personal
opensquilla channels disable personal
opensquilla channels restart personal
opensquilla channels remove personal
```

Raw config:

```sh
opensquilla config get llm.provider
opensquilla config set gateway.port 18791
```

More detail:

- [`configuration.md`](configuration.md)
- [`providers-and-models.md`](providers-and-models.md)
- [`search.md`](search.md)
- [`channels.md`](channels.md)

## Skills and Meta-Skills

```sh
opensquilla skills list
opensquilla skills search pdf
opensquilla skills view pdf-toolkit
opensquilla skills install <skill-name>
opensquilla skills update --all
opensquilla skills uninstall <skill-name>
opensquilla skills inspect meta-skill-creator
opensquilla skills meta proposals list
opensquilla skills meta runs list
opensquilla skills meta runs show <run-id>
opensquilla skills meta runs steps <run-id>
opensquilla skills meta runs replay <run-id> --dry-run
```

Use `skills inspect` when you want to see the compiled step plan for a
meta-skill before invoking it.

Read:

- [`features/skills.md`](features/skills.md)
- [`features/meta-skills.md`](features/meta-skills.md)
- [`features/meta-skill-user-guide.md`](features/meta-skill-user-guide.md)
- [`authoring/meta-skills.md`](authoring/meta-skills.md)

## Sessions and History

```sh
opensquilla sessions list
opensquilla sessions show <session-key>
opensquilla sessions resume <session-key>
opensquilla sessions abort <session-key>
opensquilla sessions export <session-key>
opensquilla sessions delete <session-key>
```

Read: [`sessions.md`](sessions.md)

## Memory

```sh
opensquilla memory status
opensquilla memory index
opensquilla memory list
opensquilla memory search "preference"
opensquilla memory show <path>
opensquilla memory dream
opensquilla memory flush-session <session-key>
opensquilla memory repair list
opensquilla memory raw-fallbacks list
```

Read: [`features/memory.md`](features/memory.md)

## Durable Agents and Scheduling

```sh
opensquilla agents list
opensquilla agents add research --name Research --workspace /path/to/research
opensquilla agents delete research
opensquilla cron list
opensquilla cron add --every 1h --text "Summarize important updates" --name hourly-summary
opensquilla cron status <job-id>
opensquilla cron runs <job-id>
```

Read:

- [`agents.md`](agents.md)
- [`scheduling.md`](scheduling.md)

## Cost, Diagnostics, and Replay

```sh
opensquilla cost
opensquilla diagnostics status
opensquilla diagnostics on
opensquilla diagnostics off
opensquilla replay --session <session-key> --turn <turn-id>
```

Use diagnostics and replay when you need to understand why a turn behaved a
certain way.

Read:

- [`usage-and-cost.md`](usage-and-cost.md)
- [`diagnostics-and-replay.md`](diagnostics-and-replay.md)

## MCP Server Bridge

```sh
opensquilla mcp-server run
opensquilla mcp-server run --gateway ws://localhost:18792/ws
```

Read: [`mcp-server.md`](mcp-server.md)

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
