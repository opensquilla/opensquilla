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
opensquilla configure search --search-provider brave --api-key-env BRAVE_SEARCH_API_KEY
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

## Router Tier Configuration

Each `squilla_router.tiers.<name>` entry routes a tier to a full provider
identity, not just a model name. Self-hosted OpenAI-compatible endpoints are
supported, including blank-auth deployments.

| Field | Meaning |
| --- | --- |
| `provider` | Provider id (`openrouter`, `inception`, `openai_compatible`, ...). |
| `model` | Model id sent to that provider. |
| `base_url` | Endpoint override; defaults to the provider's standard URL. |
| `api_key` / `api_key_env` | Tier-scoped credential (literal value or env var name). Leave empty for blank-auth endpoints. |
| `description` | Shown in the WebUI router panel. |
| `supports_image` | Marks the tier eligible for image routes. |
| `thinking_level` | Default thinking level for the tier. |
| `context_window_tokens` | Real context window of the model. Set this for self-hosted or small models: unknown models otherwise inherit an optimistic 200k default (a one-time warning `routed_tier.context_window_defaulted` is logged when that happens). |
| `toolset` | Named toolset to offer on this tier (`full` for everything). |
| `max_tool_schema_chars` | Tool-schema budget for small-context models. Units are compact-JSON serialization characters (the same accounting as request proof), not wire bytes. |
| `tool_support` | `auto` (probe/catalog decides), `on` (operator vouches the model calls tools; required for models that ignore the boot probe, e.g. diffusion models), `off` (never send tools). |
| `tool_probe_mode` | `required` or `auto` `tool_choice` used by the boot-time tool probe. |

A probe that gets a 200 response without a tool call leaves the capability
`unknown`; tool-required turns are refused on `unknown`/`unsupported` routes,
and ordinary turns proceed without tools. Set `tool_support = "on"` after
verifying a route with `scripts/live_compat_tool_route_smoke.py`.

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
opensquilla configure search --search-provider brave --api-key-env BRAVE_SEARCH_API_KEY
```

Runtime-supported search providers in this build include Brave Search and
DuckDuckGo. Additional provider metadata may be present for future or
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
