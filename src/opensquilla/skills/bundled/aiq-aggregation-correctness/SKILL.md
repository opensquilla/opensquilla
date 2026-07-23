---
name: aiq-aggregation-correctness
description: >-
  How to compute and report aggregates correctly — VWAP (volume-weighted, not simple average), median vs mean, trade-count and total-volume rollups, and cross-sector averages. Use the tool's aggregate; never hand-average tool rows or user-pasted prints. Use when computing or reporting VWAP, medians, averages, trade counts, or total volume over fixed-income trade data.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🧮"
---

# Aggregation correctness (VWAP, median, counts, sector averages)

## VWAP is volume-weighted — never a simple average
VWAP = Σ(price × size) / Σ(size). A plain mean of prices is WRONG whenever sizes differ.
- "5-day VWAP for CUSIP X", "compare the last trade to its 5-day VWAP", "volume-weighted price by
  issuer/sector" → call `analytics_vwap` (params: `cusips`, `issuer`, `sector`, `window` e.g. '5d',
  `group_by` 'cusip'|'issuer'|'sector'). It returns `vwap_price`, `vwap_yield`, `trade_count`,
  `total_par`, `notional_usd`, `median_price`, and price/yield ranges. Present `vwap_price`,
  `vwap_yield`, `trade_count`, and `total_par` together; do not recompute from raw prints.
- If the user PASTES prints and asks for the VWAP ("99.5 at 1mm, 99.6 at 2mm, 99.4 at 500k"), this
  is the defined VWAP formula on the given numbers, so compute it exactly:
  (99.5·1.0 + 99.6·2.0 + 99.4·0.5) / (1.0+2.0+0.5) and return the weighted result, NOT the simple
  mean. (This differs from fabricating market data — here the inputs are fully supplied.)

## Median vs mean
"Median price/yield" is the middle value, not the average. Prefer the tool's `median_price` /
median fields; never approximate a median with a mean.

## Counts and volume rollups
"How many trades larger than $X", "top N by trade count", "total volume traded" → use the tool's
count/`total_par`/`notional_usd` fields. When the user filters by a size threshold ("> $5mm"),
ensure the count reflects ONLY trades over that threshold, and show the threshold you applied.

"How big was TRACE volume in IG yesterday" → call `trace_notional` once with the prior completed
session resolved to an exact date and `group_by='credit_grade'`. Select the returned IG bucket; do
not sum displayed bond rows or substitute a bond leaderboard. Report the tool's trade count and
notional with the exact session date/source. TRACE dissemination size caps make notional a lower
bound, so retain the returned cap caveat.

## Cross-sector / cross-group averages
"Average yield by sector", "which sector is cheapest" → `trace_notional(group_by='sector')` returns
`avg_yield` per sector. Do not average per-bond rows yourself; use the grouped aggregate so weighting
and inclusion rules are consistent.

## Golden rule
Whenever a tool already returns the aggregate, EMIT THE TOOL'S NUMBER. Re-deriving an aggregate from
displayed rows risks rounding/weighting errors and is a correctness failure.
