# Configuration

OpenSquilla can be configured from the onboarding wizard, the Web UI setup
flow, CLI commands, environment variables, and TOML files. Use CLI commands for
routine setup and edit TOML only for advanced or scripted deployments.

## Config Load Order

OpenSquilla reads configuration in this order:

1. `OPENSQUILLA_GATEWAY_CONFIG_PATH`
2. `./opensquilla.toml`
3. `~/.opensquilla/config.toml`
4. built-in defaults

Use `--config ./opensquilla.toml` when you want to write or inspect a
project-local config file.

## Secret Handling

Prefer environment-variable references for secrets:

```sh
export OPENROUTER_API_KEY="sk-..."
opensquilla configure provider --provider openrouter --api-key-env OPENROUTER_API_KEY
```

Avoid committing raw API keys to TOML files, shell history, examples, or issue
reports.

## First-Run Wizard

```sh
opensquilla onboard
```

Common options:

```sh
opensquilla onboard --if-needed
opensquilla onboard --minimal
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
opensquilla onboard --provider openai --model gpt-5.4-mini --api-key-env OPENAI_API_KEY
opensquilla onboard --provider ollama --model llama3.1
opensquilla onboard status
```

The router mode defaults to `recommended`. Use `--router disabled` when you want
direct single-model routing.

## Reconfigure One Section

The `configure` command edits a selected section:

```sh
opensquilla configure provider --provider openrouter --api-key-env OPENROUTER_API_KEY
opensquilla configure router --router recommended
opensquilla configure router --router openrouter-mix
opensquilla configure router --router disabled
opensquilla configure search --search-provider duckduckgo
opensquilla configure search --search-provider tavily --api-key-env TAVILY_API_KEY
opensquilla configure channels
opensquilla configure image-generation
opensquilla configure memory-embedding
```

Supported sections:

- `provider`
- `router`
- `channels`
- `search`
- `image-generation`
- `memory-embedding`

## Configuration Decision Table

| Need | Preferred command |
| --- | --- |
| First setup | `opensquilla onboard` |
| CI or install scripts | `opensquilla onboard --if-needed` |
| Change provider | `opensquilla configure provider ...` |
| Enable or disable routing | `opensquilla configure router ...` |
| Configure web search | `opensquilla configure search ...` |
| Configure messaging platforms | `opensquilla configure channels` |
| Inspect current values | `opensquilla config get` |
| Persist an advanced key | `opensquilla config set <key> <value> --config <path>` |

## Provider Configuration

Inspect provider support:

```sh
opensquilla providers list
opensquilla providers configure openrouter
opensquilla providers status
```

Onboarding-verified providers include:

- OpenRouter
- OpenAI
- Anthropic
- Ollama
- DeepSeek
- Gemini
- DashScope / Qwen
- Moonshot AI
- Zhipu / Z.AI
- Baidu Qianfan
- Volcengine Ark

OpenSquilla also carries provider registry entries for additional
OpenAI-compatible or self-hosted backends. Use `opensquilla providers list` on
your install to see the current catalog.

Read: [`providers-and-models.md`](providers-and-models.md)

## Router Configuration

Router modes:

| Mode | Use when |
| --- | --- |
| `recommended` | You want the selected provider's default routing profile. |
| `openrouter-mix` | You want OpenRouter mixed-model defaults. |
| `disabled` | You want one configured provider/model for every turn. |

Commands:

```sh
opensquilla configure router --router recommended
opensquilla configure router --router openrouter-mix
opensquilla configure router --router disabled
```

Router-supported provider profiles depend on the installed build and configured
provider. Read [`features/squilla-router.md`](features/squilla-router.md) before
using direct model runs for evaluation.

## Search Configuration

Inspect search providers:

```sh
opensquilla search list
opensquilla search status
opensquilla search query "OpenSquilla release notes"
```

Configure search:

```sh
opensquilla configure search --search-provider duckduckgo
opensquilla configure search --search-provider bocha --api-key-env BOCHA_SEARCH_API_KEY
opensquilla configure search --search-provider brave --api-key-env BRAVE_SEARCH_API_KEY
opensquilla configure search --search-provider tavily --api-key-env TAVILY_API_KEY
opensquilla configure search --search-provider exa --api-key-env EXA_API_KEY
```

Runtime-supported search providers in this build include DuckDuckGo, Bocha,
Brave Search, Tavily, and Exa. DuckDuckGo is the no-key path. A partial-key
setup can configure only one keyed provider; an all-key setup can expose
`BOCHA_SEARCH_API_KEY`, `BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY`, and
`EXA_API_KEY` so runtime provider selection can choose by mode and capability
unless a request names an explicit provider. `search_provider` is the credential
anchor for `search_api_key` and `search_api_key_env`; it is not a hard routing
promise for automatic searches.
Additional provider metadata may be present for future or
not-yet-runtime-supported integrations.

Read: [`search.md`](search.md)

## Channel Configuration

List supported channel types:

```sh
opensquilla channels types --json
opensquilla channels describe feishu
opensquilla channels add telegram --name personal
opensquilla channels status
```

Channel saves update configuration. Restart the gateway after edits:

```sh
opensquilla gateway restart
opensquilla channels status <name> --json
```

See [`channels.md`](channels.md) for details.

## Memory Configuration

Useful commands:

```sh
opensquilla memory status
opensquilla memory index
opensquilla memory list
opensquilla memory search "project preference"
opensquilla memory show <path>
opensquilla memory dream
opensquilla memory flush-session <session-key>
```

Configure embedding behavior:

```sh
opensquilla configure memory-embedding
```

Memory can combine Markdown-backed sources with SQLite keyword and semantic
indexes. The exact memory shape depends on the configured provider and local
embedding support.

Read: [`features/memory.md`](features/memory.md)

## Sandbox and Permissions

Inspect or change posture:

```sh
opensquilla sandbox status
opensquilla sandbox on
opensquilla sandbox full
opensquilla sandbox bypass
opensquilla sandbox reset
```

Single-shot automation permissions:

```sh
opensquilla agent --permissions restricted -m "Read the repo and summarize it"
opensquilla agent --permissions full -m "Make a local patch and run tests"
```

For unattended automation that must stay inside a workspace:

```sh
opensquilla agent \
  --workspace /path/to/project \
  --workspace-lockdown \
  --scratch-dir /path/to/project/.scratch \
  -m "Investigate and propose the smallest fix"
```

Read: [`tools-and-sandbox.md`](tools-and-sandbox.md)

## Gateway Binding

Foreground:

```sh
opensquilla gateway run --listen 127.0.0.1 --port 18791
```

Managed:

```sh
opensquilla gateway start --json
opensquilla gateway status
opensquilla gateway stop
opensquilla gateway restart
```

Bind precedence:

1. `--listen`
2. `--bind`
3. `OPENSQUILLA_LISTEN`
4. `OPENSQUILLA_GATEWAY_HOST`
5. config host
6. `127.0.0.1`

## Raw Config Editing

For advanced settings, inspect `opensquilla.toml.example` and edit the active
config file directly. Use CLI commands for routine provider, router, search,
channel, and sandbox changes because they avoid common key-shape mistakes.

After changing files by hand, restart the gateway and run:

```sh
opensquilla doctor
opensquilla gateway status
```

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
