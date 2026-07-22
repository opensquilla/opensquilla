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

# Portfolio Concentration (executable)

Computes exposure concentration **exactly** from a list of holdings, so the
agent never eyeballs percentages or hand-computes an HHI.

## When to use
- "How concentrated is this portfolio by issuer / sector?"
- "What are my top 5 exposures and what % of the book are they?"
- "Give me the HHI / a diversification read on these holdings."

## How to use
1. Gather holdings (from a portfolio tool or the user's upload): each needs a
   market value (or notional) and a grouping key (issuer / sector / rating).
2. Run the bundled script from this skill's directory:
   `python3 scripts/hhi.py input.json` (or pipe the JSON on stdin). It prints a
   single JSON result object to stdout.
3. Quote `hhi`, `top_n`, and the per-group weights verbatim.

## Input schema (JSON)
```json
{
  "holdings": [
    {"group": "AAPL", "value": 5000000},
    {"group": "MSFT", "value": 3000000},
    {"group": "F",    "value": 2000000}
  ],
  "group_by": "issuer",   // optional label, echoed back
  "top_n": 5              // optional, default 5
}
```
- `holdings`: list of objects with a grouping key and a value.
  - Group field aliases: `group`, `issuer`, `sector`, `rating`, `name`, `ticker`.
  - Value field aliases: `value`, `market_value`, `mv`, `notional`, `weight`,
    `par`, `quantity`.
- Rows sharing a group are summed before weighting.

## Output (stdout JSON)
```json
{
  "total_value": 10000000,
  "n_groups": 3,
  "hhi": 3800,                  // 0–10000 scale (sum of squared % weights)
  "hhi_normalized": 0.07,       // 0–1, adjusts for number of groups
  "effective_n": 2.63,          // 1/Σwᵢ² — "effective number of names"
  "concentration_label": "moderately concentrated",
  "top_n": [
    {"group": "AAPL", "value": 5000000, "weight_pct": 50.0},
    {"group": "MSFT", "value": 3000000, "weight_pct": 30.0}
  ],
  "top_n_weight_pct": 80.0
}
```

HHI bands (sum-of-squared-percent convention): <1500 diversified,
1500–2500 moderate, >2500 concentrated. See `references/hhi.md`.
