---
name: aiq-benchmark-methodology
description: >-
  How to assess rich/cheap vs a benchmark and report spreads correctly — G-spread vs Treasury curve and spread vs corporate index, the rich=SELL / cheap=BUY convention, and using tool-provided spread fields rather than eyeballing or manual math. Use when asked whether a bond is rich or cheap, for G-spread or index-spread comparisons, or for a directional BUY/SELL read.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "📐"
---

# Benchmark methodology (rich/cheap, spreads, directional calls)

## What "rich" and "cheap" mean
- **Rich** = trading at a LOWER yield / TIGHTER spread than its benchmark/peers → relatively
  expensive → the directional call is **SELL**. Include the word "rich" in the rationale.
- **Cheap** = trading at a HIGHER yield / WIDER spread than its benchmark/peers → relatively
  inexpensive → the directional call is **BUY**. Include the word "cheap" in the rationale.
Use the explicit keyword the user/spec expects: say SELL for rich, BUY for cheap.

## Which benchmark
- "rich/cheap to its peers" → compare against similar bonds (same sector / rating / maturity bucket).
  `securities_search` rows carry yield and spread fields; `bond_lookalikes` finds comparable bonds.
- "vs the index" / "relative to the index" → compare against the corporate-index spread the data
  layer attaches.
- "vs Treasuries" / G-spread → the G-spread is the bond's yield minus the nearest discrete Treasury
  benchmark at its maturity. `securities_search` already returns G-spread / I-spread columns and
  `get_rates_snapshot` provides the current Treasury curve — use these; do not hand-interpolate.

## CP+ price comparisons are not spread comparisons
- `px_vs_cpp = last_px - cpp_mid`, in points of par. Negative is cheap; positive is rich.
- Cite the CP+ as-of and hedge a verdict when the mark is stale relative to the print.
- `mktx_cpp_movers` returns day-over-day CP+ mid-price changes, not credit-spread changes in bps.
  Do not call a negative price move a measured "widening" or convert points to bps yourself.
- For a requested winner, report the literal tool-ranked winner first. Keep data-quality warnings
  separate from the ranking instead of replacing the winner silently.

## Use tool-provided spreads — no manual math
Read the spread/yield fields the tools return rather than computing spreads by subtracting numbers
yourself or off user-pasted prices. If the user pastes raw prices and asks you to judge rich/cheap,
pull tool-backed market data instead of doing manual arithmetic on their numbers.

## Compliance boundary
Stating that a bond is rich/cheap and the implied SELL/BUY direction is allowed market commentary.
A PERSONALIZED recommendation ("should I buy this for my retirement?") is not — refuse the
personalized advice, then offer the tool-backed rich/cheap read so the user decides for themselves.
