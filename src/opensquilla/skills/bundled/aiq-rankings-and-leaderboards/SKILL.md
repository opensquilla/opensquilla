---
name: aiq-rankings-and-leaderboards
description: >-
  How to answer "top N / most active / biggest movers / volume surge / most-traded" rankings — pick the RIGHT tool (securities_search leaderboard vs movers_search vs volume_surge_search vs sector_activity_search) instead of scanning the raw tape, and include the ranking metric as a column. Use for top-N, most-active, biggest-movers, volume-surge, or most-traded questions.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🏆"
---

# Rankings, leaderboards & "most active" queries

Before calling a tool, lock the ranking contract: **N, universe, metric, direction,
window, and filters**. Keep every element through the answer. Use the tool's
server-side sort, preserve its row order, and show the ranking metric as a column.
Do not scan raw rows and re-rank them in prose.

Route by intent:

- **"Top N bonds by trade count / most-traded / most-active / traded notional"** →
  `securities_search(detail='compact', include_liquidity='true', order_by=...)`. Map the metric
  literally: trade count → `trades`, par volume → `quantity`, notional value → `notional`. Set
  `liquidity_lookback_days` to a relative window, or both `liquidity_start` and `liquidity_end` for
  an exact date/window. Pass the requested N as `limit`. Show the requested metric and any secondary
  metric the user named. Do NOT use `prints_search` (raw trades) or `trace_notional(group_by='issuer')`
  (issuer rows) for a bond-level ranking. Preserve `meta.liquidity.metric_contract`: `notional` is
  TRACE price × reported par in USD and `quantity` is reported par; dissemination caps make both
  lower bounds. Neither is MarketAxess BondTicker **Est Vol**, so never use that label or compare
  the values as if they were the same measure.

- **"Top N names / issuers"** → `trace_notional(group_by='issuer')`, with the requested metric,
  window, and filters. One issuer may have many bonds, so `securities_search` would rank tranches
  and repeat names instead of producing one row per issuer.

- **"Break down market volume/notional by sector, credit grade, or sector × grade"** →
  `trace_notional(group_by='sector'|'credit_grade'|'sector_credit')`. This is an aggregate breakdown,
  not a bond leaderboard; do not substitute `securities_search`.

- **"Biggest movers / wideners / tighteners / price gappers / today vs prior session"** →
  `movers_search`. `direction='widener'` for wideners, `direction='tightener'` for tighteners,
  OMIT `direction` for generic "biggest movers" / "gappers". Pass `credit_grade='IG'|'HY'` if named.
  (`gapper` is NOT a valid direction value — omit direction instead.)
  Use at least three current-session prints for a leaderboard. `price_delta` is points of par;
  `yield_delta_bps` and `g_spread_delta_bps` are basis points. Never convert a price-point move to
  bps or silently compare a stale prior-print endpoint as if it were yesterday.

- **"Cheapest/richest vs CP+"** → `securities_search` with `order_by='cpp_cheap'|'cpp_rich'`
  and `detail='full'` plus the requested filters. Cheapest means the most negative `px_vs_cpp`; richest means the most
  positive. Name the first returned row as the literal winner. If that row is stale or suspect,
  keep it as the winner and flag the quality issue; optionally show a separately labelled
  "clean-data alternative". Never silently replace the metric winner with a preferred bond.

- **"CP+ movers"** → `mktx_cpp_movers`. Its delta is CP+ **mid-price change in points of par**,
  not credit-spread change in bps. Never relabel a price decline as a measured spread widening.
  If the user explicitly asks for CP+ spread-bps movers, state that this tool cannot supply that
  metric and offer the price-move result as a clearly labelled proxy.
  Every cross-sectional row must share the same `DATE_CURR`; show `DATE_CURR` and `DATE_PREV` (or
  `GAP_DAYS`) so a missing prior mark cannot masquerade as an adjacent-day comparison.

- **"Volume surge / volume spike / unusual volume / louder than usual / today vs trailing average"**
  → `volume_surge_search`. When it is offered directly, call it directly; otherwise reach it via
  `search_tools("volume surge")` then `call_tool("volume_surge_search", ...)`. Pass `credit_grade`
  and/or `sector` from the user's framing; default to 10 rows when N is omitted. Don't gate for
  clarification — call with the filter they named (or none).
  For a ranked list use at least three current-session prints. The tool's `volume_avg_20d` is the
  average across prior *active print days* inside a 20-calendar-day window, not an average that
  includes zero-volume days; show `active_days` so denominator coverage is visible.

- **"Which sectors are most active / sector flow / sector heatmap / per-sector spread moves"** →
  `sector_activity_search` (one row per GICS sector; don't truncate to top-5 unless asked). NOT for
  per-bond drills inside a sector — use `securities_search`/`prints_search` with a `sector` filter.

## Named-universe integrity

Treat a named index, ETF, portfolio, or watchlist as a hard filter. Verify exact membership before
ranking. If AIQ has no constituents for that named universe (for example, an unsupported Bloomberg
index), say that exact-universe ranking is unavailable. Offer LQD/HYG or a market-wide screen as a
proxy, but do not run it and label its rows as members of the requested universe.

For "how many CUSIPs are in LQD/HYG," call `etf_reference` once for that exact held-constituent
dataset and report its returned count, holdings as-of, and source. Do not estimate the count or call
a market-wide security search.

## Compact → full expansion

`detail` changes only the response projection; it does not change the universe, filters, date
window, server-side ordering, pagination, or ranking math.

- Start bond activity leaderboards with `detail='compact'`. It contains identity, ranking metrics,
  the liquidity window, source, and truncation metadata and normally suffices for the answer.
- Market-wide activity rankings are activity-first: a recently traded CUSIP can appear before its
  security-master record arrives. Preserve any row-level `identity_status` / `identity_warning`.
  Do not guess a missing coupon or maturity, and do not turn a placeholder maturity into a perpetual
  bond claim. A partial identity is a data-quality disclosure, not a reason to call another tool.
- Do **not** automatically repeat a successful compact call. Use `detail='full'` only when the user
  explicitly asks for the expanded record or the task requires spread, benchmark, duration,
  outstanding-amount, callable/taxable, or CP+ fields.
- To expand, call the same `securities_search` with `detail='full'` and copy every original filter,
  date, `order_by`, `limit`, and `offset` unchanged. Full is a richer view of the same ranked page,
  not a fresh search with widened scope.

## Presentation
Preserve the tool order, return exactly N rows when available, and show the metric, units, source,
window/as-of, and material truncation. Before sending, verify the displayed metric is monotonic in
the requested direction. After the table, stop unless the user asked for analysis.

If the user asks why a bond is liquid, restrict the explanation to tool-returned observables such
as trade count, notional, recency, days traded, and a licensed liquidity score. Do not invent
institutional demand, portfolio rebalancing, benchmark membership, dealer positioning, new-issue
distribution, or investor motives. Give each row an "Observed Evidence" entry made only of
semicolon-separated literal field=value pairs copied from its returned score, trades, notional,
days, and last_trade fields. Do not add adjectives, comparisons, or explanatory prose. If no
licensed score or tradability value was returned, say so once rather than inventing one. When
`mktx_liq` is present, label it a MarketAxess-modelled 1–24 score where higher means easier to
trade. Never turn issuer identity, benchmark status, sector, coupon, or maturity into a liquidity
reason. Those causal stories are hypotheses unless another tool explicitly supports them; label
them as such or omit them.
