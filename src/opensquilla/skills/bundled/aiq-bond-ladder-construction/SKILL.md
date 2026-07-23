---
name: aiq-bond-ladder-construction
description: >-
  How to answer "build me a bond ladder / build a portfolio" — construct it with sensible stated defaults via the construction tool; never dead-end asking "which route / what parameters?". Triggers: 'build me a bond ladder', 'build a portfolio', 'construct a book of bonds'.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🪜"
---

# Bond ladder & portfolio construction ("build me a…")

"Build me a simple bond ladder" / "build a $100mm IG portfolio…" is an ACTION request. Produce a concrete proposal with sensible defaults; do NOT reply with a menu of open-ended questions or "which route do you want?" (see the aiq-act-dont-gate skill).

## Ladders
"Build me a simple bond ladder" → build one with stated defaults, then offer to refine:
- Default: $10mm total, equal notional, IG, one rung in each of the next ten full maturity years,
  using the most-active 30-day bond in each year and unique issuers when possible.
- Make one model-visible call: `securities_search(credit_grade='IG',
  maturity_ladder_years='<first>-<last>', detail='compact', include_liquidity='true',
  liquidity_lookback_days='30', order_by='trades')`. The tool performs compact discovery and returns
  one server-ranked row per year, preferring unique issuers. Preserve every explicit range/rung.
- Do not use `generate_portfolio_proposal` as the primary path for a true ladder. It optimizes to a
  benchmark and can return clustered or barbelled maturities without one bond per rung. Use it for
  benchmark-shaped portfolios, not explicit maturity ladders.
- If a rung has no eligible bond, label that gap and use the nearest available maturity only with
  the substitution disclosed. Do not collapse the request into a generic duration portfolio.
- State the assumptions in one line ("Built a 10-rung equal-weight IG ladder, 1–10y, ~$X per rung — tell me the size, credit, or rung spacing to adjust.").
- Show at least Rung Year, Security, CUSIP, Maturity, Rating, Yield, **30D TRACE Trades**, and
  **30D TRACE Notional**. Those last two fields are liquidity evidence, not the proposed position
  sizes. Never sum `liq_notional` into "portfolio notional" or use it to weight portfolio yield.
  Under the default, each filled rung has $1mm proposed principal and ten filled rungs total $10mm;
  if a year is missing, report the smaller filled-rung total explicitly.
- Never say "no portfolio was created" and stop; produce the tool-backed rungs.

## Full portfolios
"Build a $100mm IG portfolio mirroring LQD, outperform by 25bps, 35 holdings" → call
`generate_portfolio_proposal(benchmark_id='ETF_LQD', total_amount=100000000,
target_yield_pickup_bps=25, num_holdings=35, objective='min_tracking_error')`. Do not substitute
`IG_BROAD`: LQD has its own held benchmark and live Snowflake metrics. Return the proposal table
(metric | target | actual | status) + sector allocation.
- Missing parameters get sensible defaults (stated), not a question back.
- Show the funnel/constraint checks so any unmet target is visible; flag gaps rather than hiding them.

## Never
- Never dead-end an explicit build request with only clarifying questions and zero tool calls.
- Never fabricate holdings/CUSIPs — every rung/holding comes from the construction tool or a real security search.
