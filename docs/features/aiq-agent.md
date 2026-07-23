# AIQ Agent (contrib bridge)

The AIQ bridge (`src/opensquilla/contrib/aiq/`) exposes the AIQ fixed-income
agent surface as native OpenSquilla tools, plus an `aiq` agent whose persona is
AIQ TraceAgent's domain instructions ported to this runtime.

## What it is

- **42 bridged tools**, registered into the default tool registry with real
  schemas snapshotted from AIQ (`catalog.json`), validated by OpenSquilla's
  schema subset at dispatch time:
  - FINRA TRACE market data: `prints_latest`, `prints_search`,
    `prints_group_by_period`, `get_security_stats`, `analytics_vwap`,
    `securities_search`, `trace_notional`, `trace_volume_by_size`,
    `movers_search`, `sector_activity_search`, `volume_surge_search`,
    `issuer_bond_snapshot`, `etf_reference`
  - MarketAxess CP+ (entitlement-gated by AIQ): `mktx_cpp_movers`,
    `mktx_cpplus`, `mktx_history`, `bond_lookalikes`
  - Rates, math, platform: `get_rates_snapshot`, `bond_calculate`,
    `render_chart`, `draft_trade_ticket`, `get_insight`, `news_search`,
    `get_release_notes`, `fmp_fundamentals`, `eodhd_market_data`
  - Long-tail registry pair (Kimi-K3 pattern, bridged first-class):
    `search_tools`, `call_tool`
  - User memory: `remember_user_fact`, `recall_user_facts`
  - Portfolios: `generate_portfolio_proposal`, `get_portfolio_drift`,
    `get_available_benchmarks`, `portfolio_create`, `portfolio_add_holding`,
    `portfolio_remove_holding`, `portfolio_swap`, `portfolio_list`,
    `portfolio_list_holdings`, `portfolio_analytics`,
    `portfolio_liquidation_analysis`, `portfolio_delete`
- **Architecture**: the bridge holds no copies of AIQ tool code. Each handler
  lazily inserts the configured AIQ repo path on `sys.path` at call time,
  imports the tool's module, and dispatches through the OpenAI Agents SDK
  `FunctionTool.on_invoke_tool` seam — so AIQ's own argument parsing and
  per-user entitlement gates (e.g. MarketAxess CP+) stay intact.
- **FAQ routing**: before prompt assembly, a deterministic query-profile
  selector narrows the visible schema to the tools authorized for that
  request. A matched profile preloads at most one AIQ skill into private,
  request-scoped context and removes `skill_view`, avoiding a model/tool/model
  round trip. Profiles also set an ordinary-iteration ceiling and repeated-call
  recovery boundary. Unknown requests fail open to the normal OpenSquilla
  surface.
- **Policy**: every bridged tool is `exposed_by_default=False` (invisible
  unless allow-listed). Read-only data tools carry network sandbox
  descriptors (`kind="aiq.read"` / `"aiq.external.read"`, third-party HTTP
  tools also get `result_budget_class="external"`); pure-local tools are
  `kind="aiq.local"`; user-state mutations are `kind="aiq.write"`.
- **Degradation**: without the AIQ repo, its dependencies, or its credentials,
  every tool returns the standard five-key failure envelope
  (`error_class: "SafeToolError"`) with a config hint — never a crash.

## Configuration

Integration config lives in the gateway TOML (env vars override TOML):

```toml
[aiq]
# Checkout of the AIQ repo with its Python dependencies installed.
repo_path = "/path/to/aiq"
# Identity for AIQ's per-user entitlement gates (MarketAxess CP+ is
# @aiqmarkets.com / @marketaxess.com only). Optional.
user_email = "you@example.com"
```

Env overrides: `AIQ_REPO_PATH`, `AIQ_USER_EMAIL`.

**No credentials go in OpenSquilla config.** Live data requires the AIQ
checkout to be importable with its own dependencies (`openai-agents`,
Snowflake connector, Neo4j driver, ...) in the OpenSquilla process's
environment, and AIQ's own secrets (its `.env`: Snowflake, Neo4j, FRED,
FMP/EODHD keys) which AIQ loads itself.

Provider: the agent defaults to Anthropic Claude — configure per
`docs/providers-and-models.md`:

```toml
[llm]
provider = "anthropic"
model = "claude-sonnet-4-5"
# key via env ANTHROPIC_API_KEY
```

## Registering the `aiq` agent

Programmatic (recommended — fills in the persona and the full allowlist):

```python
from opensquilla.agents.registry import AgentRegistry
from opensquilla.contrib.aiq.agent import ensure_aiq_agent

await ensure_aiq_agent(agent_registry)  # create-or-update + AGENTS.md persona
```

Or declaratively: add an `[[agents]]` block with `id = "aiq"` and
`tools = { allow = [...] }` (names from
`opensquilla.contrib.aiq.agent.aiq_agent_tool_allowlist()`), then
`opensquilla gateway restart`. The persona can be installed into the agent
workspace as `AGENTS.md` (the standard bootstrap-file channel); `ensure_aiq_agent`
does both steps.

## Running it

```bash
# Reproducible FAQ variant created from the shared AIQ harness baseline.
export AIQ_REPO_PATH="$HOME/Desktop/cutedsl/aiq-harness-opensquilla"

# one-shot turn
opensquilla agent -m "biggest IG wideners today" --agent aiq

# other surfaces take the same flag
opensquilla sessions list --agent aiq
opensquilla cron add --agent aiq --every 1d --text "morning TRACE movers recap"
```

The exact 21-question workbook-derived fixture is
`evals/fixed_income_benchmark/tasks/00_frequently_asked_xlsx_2026_07.jsonl`
inside that AIQ worktree. The query-profile tests cover every fixture ID
without making provider or market-data calls.

## Limitations

- Live market data needs the AIQ repo checkout **and** its credentials
  (Snowflake for TRACE/securities/MarketAxess, Neo4j for
  portfolios/insights/user facts, FRED for rates, FMP/EODHD keys for
  fundamentals/equity context). Without them, tools return clean enveloped
  errors.
- AIQ's dependencies must be installed in the same Python environment as
  OpenSquilla for the lazy import to succeed (the bridge does not use AIQ's
  own virtualenv).
- MarketAxess CP+ fields/tools are entitlement-gated by AIQ using
  `[aiq] user_email`; unauthorised identities get AIQ's own gating behavior.
- `render_chart` and `draft_trade_ticket` return UI payload JSON that AIQ's
  chat frontend renders; in OpenSquilla the JSON payload is returned as-is.
- AIQ's specialist-agent handoffs (Ops/Headline/File) are not ported;
  portfolio capability is bridged as first-class tools instead.
- The tool schemas are a build-time snapshot of the AIQ repo; a much newer or
  older AIQ checkout may drift from `catalog.json` (calls still dispatch, but
  new parameters would be unknown to the schema validator).

## Offline verification

```bash
uv run --frozen pytest -q \
  tests/test_contrib/test_aiq \
  tests/test_engine/turn_runner \
  tests/test_engine/test_runtime_agent_max_iterations.py \
  tests/test_skills_third_party_notices.py
```

Current result: 497 passed. This check makes no paid model call.

To measure the request boundary itself against the exact FAQ fixture:

```bash
uv run --frozen python scripts/experiments/benchmark_aiq_faq_surface.py \
  --tasks "$AIQ_REPO_PATH/evals/fixed_income_benchmark/tasks/00_frequently_asked_xlsx_2026_07.jsonl" \
  --iterations 1000
```

The current offline run matches all 21 tasks. Median effective tool count is
one; median provider tool-schema size falls from 45,700 to 3,517 bytes
(92.3%), and selector p50/p95 are 2.5/4.2 microseconds. These measurements do
not include model, network, or data-tool latency.
