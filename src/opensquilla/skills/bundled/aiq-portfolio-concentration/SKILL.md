---
name: aiq-portfolio-concentration
description: >-
  Compute portfolio concentration metrics — % weights, top-N concentration, and the Herfindahl-Hirschman Index (HHI) — over holdings grouped by issuer, sector, or rating. Use for "how concentrated is this book" / "biggest exposures" questions. Triggers: 'how concentrated is this portfolio', 'top exposures', 'HHI', 'diversification read'.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  version: "1.0"
  opensquilla:
    emoji: "🥧"
---

# Portfolio concentration

Compute exposure concentration only from the resolved portfolio's holdings and
tool-returned analytics. Never infer weights from a portfolio name or from a
partial chat table.

## When to use
- "How concentrated is this portfolio by issuer / sector?"
- "What are my top 5 exposures and what % of the book are they?"
- "Give me the HHI / a diversification read on these holdings."

## How to use

1. If the request does not identify a portfolio and no active portfolio exists
   in context, ask which portfolio once. Do not invent holdings or weights.
2. Resolve it with `portfolio_list` and retrieve its complete holdings with
   `portfolio_list_holdings`; do not repeat either successful call.
3. Call `portfolio_analytics` for the requested sector, issuer, rating,
   duration, or cash-flow view. Prefer its returned group weights and totals to
   hand aggregation.
4. For "what sector risk do I have," show every returned sector weight, the top
   concentrations, and any explicit benchmark difference the tool supplies.
   Sector identity alone is not a risk diagnosis; label concentration as the
   observable and do not invent a macro scenario.
5. Render a chart only when the user asks for one. A text/table question should
   stop after analytics.

If HHI is explicitly requested and the analytics tool does not return it, use
the complete returned group weights: `HHI = Σ(weight_pct²)` on the 0–10,000
scale. State that it was calculated from the displayed complete weights. Do not
calculate HHI from a truncated top-N list. Conventional bands are below 1,500
diversified, 1,500–2,500 moderately concentrated, and above 2,500 concentrated.
