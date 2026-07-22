---
name: aiq-bond-trade-stats
description: >-
  Compute volume-weighted average price (VWAP), median/mean price & yield, and total notional from a set of TRACE prints. Use whenever the user asks for VWAP or an average/median over individual trades. Triggers: 'VWAP', 'average print price', 'median yield', 'total notional traded'.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  version: "1.0"
  opensquilla:
    emoji: "📊"
---

# Bond Trade Statistics (executable)

Computes trade-level aggregates over a list of TRACE prints **exactly**, so the
agent never hand-computes (and never hallucinates) VWAP, medians, or notional.

## When to use
- "What's the VWAP for AAPL 4.20 05/30 today?"
- "Average / median print price (or yield) for this CUSIP."
- "Total notional traded in these prints."

## How to use
1. Pull the raw prints with `prints_search` / `prints_latest` (one CUSIP, or a
   filtered set). You need per-print `price`, `quantity`, and optionally `yield`.
2. Run the bundled script from this skill's directory:
   `python3 scripts/compute.py input.json` (or pipe the JSON on stdin). It prints a
   single JSON result object to stdout.
3. Quote the numbers from the result verbatim. Do **not** recompute them.

## Input schema (JSON)
```json
{
  "prints": [
    {"price": 101.25, "quantity": 1000000, "yield": 4.18},
    {"price": 101.40, "quantity": 250000,  "yield": 4.15}
  ],
  "label": "AAPL 4.200 05/30"        // optional, echoed back
}
```
- `prints`: list of objects. `price` and `quantity` are required per row;
  `yield` is optional. Field aliases accepted: `px`/`last_price` for price,
  `qty`/`size`/`notional` for quantity, `yld`/`ytm` for yield.

## Output (stdout JSON)
```json
{
  "n_prints": 2,
  "total_quantity": 1250000,
  "vwap_price": 101.28,
  "mean_price": 101.325,
  "median_price": 101.325,
  "min_price": 101.25,
  "max_price": 101.40,
  "vwap_yield": 4.174,        // null if no yields supplied
  "median_yield": 4.165,
  "price_stdev": 0.106
}
```

VWAP = Σ(price·qty) / Σ(qty). All figures rounded to a sensible precision; the
script preserves source precision for the inputs.

See `references/methodology.md` for edge-case handling.
