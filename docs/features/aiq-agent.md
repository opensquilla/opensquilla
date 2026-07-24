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
- **Architecture**: the bridge holds no copies of AIQ tool code. Its preferred
  backend calls AIQ's authenticated MCP endpoint, so OpenSquilla does not
  import or depend on the OpenAI Agents SDK for tool execution. AIQ remains
  responsible for schemas, JWT identity, and per-user entitlement gates. A
  local-development fallback can still import an AIQ checkout and dispatch
  through `FunctionTool.on_invoke_tool`.
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
# Preferred: AIQ's authenticated MCP SSE endpoint.
mcp_url = "https://api.aiqmarkets.com/api/mcp/sse"

# Local-development fallback when mcp_url is omitted.
repo_path = "/path/to/aiq"
# Identity for AIQ's per-user entitlement gates (MarketAxess CP+ is
# @aiqmarkets.com / @marketaxess.com only). Optional.
user_email = "you@example.com"
```

Env overrides: `AIQ_MCP_URL`, `AIQ_MCP_BEARER_TOKEN`, `AIQ_REPO_PATH`,
`AIQ_USER_EMAIL`.

**No credentials go in OpenSquilla config.** For MCP, provide the current JWT
only as `AIQ_MCP_BEARER_TOKEN`; it is sent on both the SSE stream and session
message requests. For the local fallback, the AIQ checkout must be importable
with its own dependencies (`openai-agents`, Snowflake connector, Neo4j driver,
...) and its own `.env` credentials.

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
# Preferred tool backend.
export AIQ_MCP_URL="http://127.0.0.1:5002/api/mcp/sse"
export AIQ_MCP_BEARER_TOKEN="<fresh-development-user-JWT>"

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

## July 23, 2026 tool-contract changes

Three FAQ-critical parameters that existed in AIQ had fallen out of the
OpenSquilla schema snapshot:

- `mktx_cpp_movers.lookback_days` now supports 1–90 days; the “last month”
  profile sends 30.
- `render_chart.source_mode` and `render_chart.issuer` now support the
  tool's internal issuer-yield-curve retrieval path.
- `generate_portfolio_proposal.target_yield_pickup_bps` now preserves a
  benchmark-relative pickup instead of coercing it into an absolute yield.

The matching request profiles name the exact parameters. A new offline guard
checks every bridged tool against the live AIQ checkout:

```bash
uv run python scripts/experiments/check_aiq_catalog.py \
  --aiq-repo /absolute/path/to/aiq \
  --json
```

It compares parameter names, structural types, array item types, and semantic
required fields. AIQ's OpenAI strict schemas mark optional properties as
required, so the guard treats defaulted and nullable properties as optional.
Curated descriptions, defaults, and narrower enums are intentionally allowed
to differ. The current 42-tool result is `[]` (no drift).

## AIQ dashboard development adapter

AIQ can expose this agent through its existing dashboard SSE contract while
keeping OpenSquilla as a separate gateway process. The AIQ-side path requires
the default-off `AIQ_FAQ_RUNTIME_V2_ENABLED` master rollout gate, the
path-specific `AIQ_OPENSQUILLA_DEV_ENABLED` server flag, and an explicit
`orchestrator=opensquilla` request; native AIQ remains the default. The
adapter translates gateway text, tool, terminal, usage, and error events,
persists the related OpenSquilla session key in AIQ thread metadata, and
enforces a bounded turn deadline.

The dashboard integration is development-only. In particular, the gateway's
configured `AIQ_MCP_BEARER_TOKEN` is the tool identity; the inbound browser
user's JWT is not forwarded per request. Do not treat one privileged gateway
as a production multi-user entitlement boundary.

See `docs/source/guides/opensquilla-dev-orchestrator.md` in the AIQ checkout
for feature flags, startup order, smoke tests, observability, limitations, and
rollback.

## Limitations

- The preferred MCP backend needs a reachable AIQ API and a valid
  `AIQ_MCP_BEARER_TOKEN`. AIQ owns its Snowflake, Neo4j, rates, FMP/EODHD, and
  entitlement configuration; those dependencies are not installed in
  OpenSquilla.
- The local import fallback needs the AIQ checkout, credentials, and
  dependencies in the same Python environment as OpenSquilla. It does not use
  AIQ's virtualenv automatically.
- MarketAxess CP+ fields/tools are entitlement-gated by the JWT identity on
  the MCP path and `[aiq] user_email` on the local fallback. Unauthorized
  identities retain AIQ's own gating behavior.
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
  tests/test_engine/turn_runner/test_agent_bootstrap_stage_unit.py \
  tests/test_engine/turn_runner/test_prompt_assembler_stage_unit.py \
  tests/test_mcp/test_sse_client.py \
  tests/test_skills_third_party_notices.py
```

The current affected bridge/profile/turn-runner/MCP-SSE/skill-notice run is
172 passed. These checks make no paid model call.

To measure the request boundary itself against the exact FAQ fixture:

```bash
uv run --frozen python scripts/experiments/benchmark_aiq_faq_surface.py \
  --tasks "$AIQ_REPO_PATH/evals/fixed_income_benchmark/tasks/00_frequently_asked_xlsx_2026_07.jsonl" \
  --iterations 1000
```

The current offline run matches all 21 tasks. Median effective tool count is
one; median provider tool-schema size falls from 47,071 to 3,687 bytes
(92.17%), and selector p50/p95 are 2.542/4.416 microseconds across 21,000
selections. These measurements do not include model, network, or data-tool
latency.
