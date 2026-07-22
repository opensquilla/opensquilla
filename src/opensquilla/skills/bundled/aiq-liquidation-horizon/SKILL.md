---
name: aiq-liquidation-horizon
description: >-
  Estimate days-to-liquidate for a position given its size and the bond's average daily volume (ADV), under a participation-rate cap. Use for "how many days to unwind / exit this position without moving the market" questions. Triggers: 'how long to liquidate', 'days to exit this position', 'unwind without moving the market'.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  version: "1.0"
  opensquilla:
    emoji: "⏳"
---

# Liquidation Horizon (executable)

Estimates how many trading days it takes to exit a position at a given maximum
participation rate of average daily volume (ADV). Computed exactly — the agent
should never guess liquidation-days arithmetic.

## When to use
- "How long to liquidate $20MM of this bond without being more than 20% of volume?"
- "Days to exit this position." / "Is this position liquid relative to my size?"

## How to use
1. Get the bond's recent volume: ADV from `prints_group_by_period` (sum/period)
   or `get_security_stats`, plus the position size from the user / portfolio.
2. Run the bundled script from this skill's directory:
   `python3 scripts/days.py input.json` (or pipe the JSON on stdin). It prints a
   single JSON result object to stdout.
3. Quote `days_to_liquidate` and the participation assumption verbatim.

## Input schema (JSON)
```json
{
  "position_size": 20000000,        // notional to exit
  "adv": 5000000,                   // average daily volume (same units as size)
  "participation_rate": 0.20,       // optional, default 0.20 (20% of ADV)
  "label": "F 6.100 08/32"          // optional, echoed back
}
```
Field aliases: `position`/`size`/`notional` for position_size;
`avg_daily_volume`/`adv_notional`/`daily_volume` for adv;
`max_participation`/`pov` for participation_rate.

## Output (stdout JSON)
```json
{
  "label": "F 6.100 08/32",
  "position_size": 20000000,
  "adv": 5000000,
  "participation_rate": 0.20,
  "daily_capacity": 1000000,        // adv * participation_rate
  "days_to_liquidate": 20.0,        // ceil to whole sessions: 20
  "days_to_liquidate_whole": 20,
  "liquidity_label": "illiquid relative to size",
  "position_vs_adv_x": 4.0          // position / adv multiple
}
```

A position that is many multiples of ADV (long horizon) is illiquid; ≤ ~1×
ADV unwinds within days. See `references/notes.md` for bands and caveats.
