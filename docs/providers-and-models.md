# Providers and Models

OpenSquilla supports multiple LLM providers through one configuration surface.
You can run direct single-model mode or enable SquillaRouter for tiered routing.

Use this page when you need to configure a provider, inspect model support, or
choose between direct model mode and router mode.

## Inspect Providers

List provider metadata from the local install:

```sh
opensquilla providers list
opensquilla providers list --json
```

Show runtime provider diagnostics from the running gateway:

```sh
opensquilla providers status
opensquilla providers status openrouter --json
opensquilla providers status --probe-models
```

`providers list` does not require a running gateway. `providers status` does.

## Configure a Provider

Interactive:

```sh
opensquilla providers configure openrouter
```

Non-interactive onboarding-style configuration:

```sh
export OPENROUTER_API_KEY="sk-..."
opensquilla configure provider --provider openrouter --api-key-env OPENROUTER_API_KEY
```

Direct provider examples:

```sh
opensquilla configure provider --provider openai --model gpt-5.4-mini --api-key-env OPENAI_API_KEY
opensquilla configure provider --provider anthropic --model claude-sonnet-4-5 --api-key-env ANTHROPIC_API_KEY
opensquilla configure provider --provider gemini --model gemini-2.5-flash --api-key-env GEMINI_API_KEY
opensquilla configure provider --provider ollama --model llama3.1
```

Prefer environment-variable references for API keys so secrets are not written
directly into configuration files.

## Onboarding-Verified Providers

This build exposes onboarding support for:

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

The provider registry may contain additional compatible providers for advanced
or self-hosted setups. Use `opensquilla providers list` on your install for the
current catalog.

### OpenAI: `openai` vs `openai_responses`

OpenAI is exposed as two provider ids that share the same `OPENAI_API_KEY` and
base URL (`https://api.openai.com/v1`):

- `openai` — the chat/completions request shape. Use this for standard
  chat-style turns and broad tool compatibility.
- `openai_responses` — the native Responses-API shape (capabilities `chat` and
  `responses`). Use this when you want Responses-API behavior rather than the
  chat/completions surface.

Both read the same key and base URL, so switching between them needs only a
`provider` change.

## Model Inspection

List models:

```sh
opensquilla models list
```

If runtime-backed model inspection cannot connect, start the gateway:

```sh
opensquilla gateway run
```

For provider metadata that does not require the gateway, use:

```sh
opensquilla providers list
```

## Direct Model vs Router

Direct model mode:

```sh
opensquilla configure router --router disabled
opensquilla configure provider --provider openai --model gpt-5.4-mini --api-key-env OPENAI_API_KEY
```

Router mode:

```sh
opensquilla configure router --router recommended
```

| Mode | Use when |
| --- | --- |
| Direct model | You are testing one exact model, reproducing provider behavior, or auditing provider billing. |
| Router mode | You want normal personal-agent use where cost and task complexity vary by turn. |

For routing details, see
[`features/squilla-router.md`](features/squilla-router.md).

## Provider Troubleshooting

Start with:

```sh
opensquilla doctor
opensquilla providers status
opensquilla diagnostics on
```

Check:

- the API key environment variable is set in the gateway process environment;
- the model id matches the provider;
- the base URL is correct for compatible APIs;
- proxy settings match your network;
- router is disabled when debugging one exact provider/model;
- the gateway was restarted after config changes.

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
