---
name: aiq-charting-and-visualization
description: >-
  How to answer "plot / graph / chart X over time" (G-spread, price, yield, CP+) — resolve the bond(s) from context and RENDER a chart from a real time series; never reply by only asking which bond. Triggers: 'plot', 'graph', 'chart', 'show me X over time'.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "📈"
---

# Charts & visualization ("plot / graph X over time")

When the user says "plot", "graph", "chart", or "show me X over time", they expect a RENDERED chart, not a table and NOT a question back. Act, don't gate (see the aiq-act-dont-gate skill).

## Resolve the target first — don't ask "which bond?"
- If the request names a bond ("graph the G-spread for AAPL 3.35 2027") → resolve it via `securities_search` and chart that CUSIP.
- If it says "these bonds" / "them" / "the ones above" → use the CUSIP(s) from the most recent result in the conversation. Never ask the user to re-specify what they just referenced.
- If it names an issuer ("curve of amazon bonds") → pull the issuer's outstanding bonds and chart the curve (yield vs maturity).
- Only if there is genuinely no bond in scope AND none named, pick the single most-recently-discussed bond and say which you charted.

## Build the series, then render
- **G-spread over time** → `prints_group_by_period(group_by='day', include_g_spread='true')` for the CUSIP, then `render_chart(y_keys=['g_spread_bps'])`. This is the TRUE daily G-spread series — never substitute a CP+ mid-yield or a single-point snapshot.
- **Price / yield over time** → `prints_group_by_period(group_by='day')` then `render_chart` on the price or yield key.
- **Issuer curve** → call `render_chart` once with `source_mode='issuer_yield_curve'`, the named
  `issuer`, and `data='[]'`. The renderer obtains the issuer's bonds and creates the yield-vs-maturity
  projection itself. Do not call `securities_search` first or manually copy rows into chart data.
  After rendering, summarize only observable facts: point count, maturity/yield range, and visible
  slope/shape. The chart does not establish *why* the curve has that shape. Do not call it
  "typical," attribute it to duration/credit compensation, or invent supply, demand, positioning,
  or issuance effects without a separate returned source. End with "The chart alone does not
  establish the cause" when the user did not provide causal evidence.
- History floor is 2023-01-01; if the requested window predates it, chart from the floor and say so.
- One chart per axis scale — never mix price and spread/yield on the same chart.

## Never
- Never end a chart request with only "which bond would you like?" when a bond is named or in context.
- Never fabricate series points; if a tool returns no series, say the data isn't available for that bond/window.
- Never emit an interim "now I'll render" / "let me chart" sentence. Call the tools silently and
  make the first visible text the final, evidence-limited summary.
