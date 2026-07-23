---
name: aiq-bond-activity-leaderboards
description: >-
  Answer bond-level top-N TRACE activity rankings with one compact
  securities_search call while preserving the requested metric, date, cap
  caveat, and identity-quality warnings.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
---

# Bond activity leaderboards

Lock six fields before calling: bond grain, requested N, universe, metric,
direction, and date/window. Keep all six unchanged through the answer.

Call `securities_search` exactly once with `detail='compact'`,
`include_liquidity='true'`, the requested `limit`, and server-side descending
sort. Map the user's metric literally:

- trade count / most active -> `order_by='trades'`
- par volume -> `order_by='quantity'`
- traded notional value -> `order_by='notional'`

For an exact session, set both `liquidity_start` and `liquidity_end`. For a
relative window, use `liquidity_lookback_days`. Do not substitute
`trace_notional`, which returns grouped aggregates, or `prints_search`, which
returns raw prints. Do not repeat a successful compact call: missing security
terms are a data-quality condition, not a reason to expand or retry.

Preserve tool order and show the requested metric plus trade count. State the
effective date/window returned by the tool. `notional` means TRACE price times
reported par in USD; `quantity` means reported par. Dissemination size caps
make both lower-bound aggregates. Neither field is BondTicker `Est Vol`, so
never apply that label or compare their totals as equivalent measures.

Activity ranking is intentionally trade-first. A recent CUSIP may appear
before the reference master has complete terms. Preserve `identity_status` and
`identity_warning`; omit or label an unverified coupon/maturity rather than
guessing it. Never call a placeholder maturity perpetual.

Return exactly N rows when available, the exact as-of/window, source, units,
and cap caveat. If asked why a row is liquid, use only returned trade count,
notional, active days, last trade, or licensed liquidity score. These
observables do not establish demand, ownership, dealer positioning, benchmark
membership, or any other cause.
