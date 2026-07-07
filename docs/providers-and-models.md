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

## Pricing and Cost Estimation

OpenSquilla reports real provider-billed cost when a provider returns it, and
estimates cost locally from token usage everywhere else. Every usage row and
by-model breakdown item is labeled so you can tell which kind of number you
are looking at.

### How a Cost Is Estimated

Each priced call is split into four token buckets — fresh input, cache read,
cache write, output — and each bucket is priced at its own rate. The result
carries a `basis` label:

| Basis | Meaning |
| --- | --- |
| `cache_aware` | All buckets present in the call have a known rate; the four-bucket math ran. |
| `cache_blind` | The call used cache tokens but a needed cache rate is unknown, so OpenSquilla fell back to pricing every input token (cache or fresh) at the plain input rate. This is a conservative upper bound, not the real charge — expect it to overstate cost on cache-heavy sessions. |
| `free` | The model or runtime is zero-priced (see local runtimes below). |

### Price Resolution Order

For a given `(model, provider)` pair, OpenSquilla resolves a price through
these layers, first match wins:

1. **Local runtime** — `ollama`, `lm_studio`, `ovms`, `vllm`, and `local` are
   always free, regardless of model id.
2. **User override** — `[models.<provider_id>."<model_id>"]` in your config
   (see [`configuration.md`](configuration.md) and `opensquilla.toml.example`).
3. **Model catalog** — the vendored models.dev snapshot, including per-model
   cache-read/cache-write rates where upstream publishes them.
4. **Live OpenRouter endpoint price** — looked up only when the provider is
   `openrouter` or unset (first-party provider ids never query the OpenRouter
   marketplace); falls back to the static table if OpenRouter is unreachable.
5. **Static table** — a built-in pricing table bundled with OpenSquilla.
6. **Default** — `$3` / `$15` per million input/output tokens when nothing
   else matched.

If OpenSquilla is estimating a model at the wrong price, add an override
instead of waiting for a catalog refresh:

```toml
[models.openrouter."z-ai/glm-5.2"]
input_cost_per_mtok = 0.5        # USD per million input tokens
output_cost_per_mtok = 2.0       # USD per million output tokens
cache_read_cost_per_mtok = 0.05  # USD per million cached-prompt-read tokens
cache_write_cost_per_mtok = 0.6  # USD per million cached-prompt-write tokens
```

Quote model ids that contain dots or slashes. All four fields are optional —
set only the ones you need to correct. `config.set`/`patch`/`apply` and
`opensquilla gateway reload` hot-apply these overrides; see
`opensquilla.toml.example` for more examples including self-hosted `vllm` and
`custom` endpoints.

### Cost Provenance (`costSource`)

Every usage row and by-model breakdown item carries a `costSource` (also
exposed dual-cased as `cost_source`):

| `costSource` | Meaning |
| --- | --- |
| `provider_billed` | The full cost came from a real provider-reported bill. |
| `opensquilla_estimate` | No billed cost was available; the figure is a local estimate. |
| `mixed` | The same model had both billed and unbilled calls in the aggregated row — the total is billed cost plus an estimate for the rest, not a pure bill. |
| `unavailable` | No pricing table entry and no billed cost, so no dollar figure could be produced. |

Rows also carry two additive fields: `estimateBasis` (the `cache_aware` /
`cache_blind` / `free` label above, present only when part of the row was
estimated) and `priceSource` (which resolver layer priced it — `user_override`,
`catalog`, `live_openrouter`, `static_table`, `default`, or `local_free`). The
Web UI's by-model usage cards show a small source chip for `costSource` and,
when the underlying basis is `cache_blind`, a hint that the figure is an
upper bound rather than the real cache-discounted cost.

### Which Providers Yield Billed vs. Estimated Cost

| Capability | Providers |
| --- | --- |
| Provider-billed cost | `openrouter` only |
| Cache-aware estimate possible | `anthropic`, `deepseek`, `minimax` (Anthropic-shaped), ensemble members |
| Cache-read-aware estimate only (no cache-write rate) | `openai`, `openai_responses`, `azure`, `gemini`, `openai_codex` |
| Cache-blind estimate (falls back to plain input-rate pricing when cache tokens appear) | other OpenAI-compatible provider kinds |
| Free | local runtimes (`ollama`, `lm_studio`, `ovms`, `vllm`, `local`) |
| Subscription (no invoice to compare against) | coding-plan/subscription provider kinds — treat any reported figure as an estimate, not a bill |

Use `opensquilla providers status --probe-models` and `opensquilla cost
--by-model` to see which class your configured provider/model falls into for
a given session.

### Turn and Router Budget Gates

Two per-turn agent budgets exist and behave differently:

- `max_turn_billed_cost_usd` gates only on real provider-billed cost. It is
  inert (never trips) on providers or paths that never report billed cost —
  do not rely on it alone outside `openrouter`.
- `max_turn_cost_usd` gates on the same accumulator used everywhere else in
  this section: billed cost when the provider reports it, otherwise the
  cache-aware/cache-blind estimate. It works on every provider. When it trips,
  the error (`turn_cost_budget_exceeded`) states whether the total was billed,
  estimated, or mixed.

SquillaRouter's session budget gate (`[squilla_router.budget]`, see
[`features/squilla-router.md`](features/squilla-router.md)) logs a
`spend_source` alongside each `router_budget.warn`/`router_budget.cap` event
and in the routing trail:

| `spend_source` | Meaning |
| --- | --- |
| `billed` | Accumulated spend is real provider-billed cost. |
| `estimate` | Accumulated spend is a local estimate for the whole session. |
| `estimate_mixed` | The session mixes billed and estimated cost. |
| `none` | No spend has been recorded yet. |
| `unknown` | Spend could not be determined; the gate suspends rather than acting on a guess. |

Read next: [`usage-and-cost.md`](usage-and-cost.md) for the `opensquilla cost`
CLI and how to read a session's usage rows.

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
