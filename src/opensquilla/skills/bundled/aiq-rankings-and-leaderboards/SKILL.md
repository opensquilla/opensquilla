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

- **"Top N by trade count / most-traded / most-active / top N by volume"** → `securities_search` with
  `include_liquidity='true'` and `order_by` reflecting the metric; set `liquidity_lookback_days` to
  the stated window (e.g. '7' for "last 7 days"). Show the ranking metric (trade count, total volume)
  AND the secondary metric the user asked for (e.g. total volume alongside trade count) as columns.
  Do NOT use `prints_search` for rankings — it returns individual prints, not a ranking.

- **"Biggest movers / wideners / tighteners / price gappers / today vs prior session"** →
  `movers_search`. `direction='widener'` for wideners, `direction='tightener'` for tighteners,
  OMIT `direction` for generic "biggest movers" / "gappers". Pass `credit_grade='IG'|'HY'` if named.
  (`gapper` is NOT a valid direction value — omit direction instead.)

- **"Cheapest/richest vs CP+"** → `securities_search` with `order_by='cpp_cheap'|'cpp_rich'`
  and the requested filters. Cheapest means the most negative `px_vs_cpp`; richest means the most
  positive. Name the first returned row as the literal winner. If that row is stale or suspect,
  keep it as the winner and flag the quality issue; optionally show a separately labelled
  "clean-data alternative". Never silently replace the metric winner with a preferred bond.

- **"CP+ movers"** → `mktx_cpp_movers`. Its delta is CP+ **mid-price change in points of par**,
  not credit-spread change in bps. Never relabel a price decline as a measured spread widening.
  If the user explicitly asks for CP+ spread-bps movers, state that this tool cannot supply that
  metric and offer the price-move result as a clearly labelled proxy.

- **"Volume surge / volume spike / unusual volume / louder than usual / today vs trailing average"**
  → `volume_surge_search`, which is a long-tail tool: reach it via `search_tools("volume surge")`
  then `call_tool("volume_surge_search", ...)` — it is NOT a first-class tool, so calling it
  directly errors "tool not found". Pass `credit_grade` and/or `sector` from the user's framing;
  default limit 50. Don't gate for clarification — call with the filter they named (or none).

- **"Which sectors are most active / sector flow / sector heatmap / per-sector spread moves"** →
  `sector_activity_search` (one row per GICS sector; don't truncate to top-5 unless asked). NOT for
  per-bond drills inside a sector — use `securities_search`/`prints_search` with a `sector` filter.

## Named-universe integrity

Treat a named index, ETF, portfolio, or watchlist as a hard filter. Verify exact membership before
ranking. If AIQ has no constituents for that named universe (for example, an unsupported Bloomberg
index), say that exact-universe ranking is unavailable. Offer LQD/HYG or a market-wide screen as a
proxy, but do not run it and label its rows as members of the requested universe.

## Presentation
Preserve the tool order, return exactly N rows when available, and show the metric, units, source,
window/as-of, and material truncation. Before sending, verify the displayed metric is monotonic in
the requested direction. After the table, stop unless the user asked for analysis.
