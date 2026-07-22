---
name: aiq-handling-empty-data
description: >-
  How to respond when a data tool returns no rows, a no_data status, or an empty result — report it honestly and never fabricate data. Use whenever a data tool returns zero rows, an empty list, or a no_data status.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🕳️"
---

# Handling empty tool output

When any tool returns zero rows, an empty list, a `status: no_data`, or a `no_data_notice`:

1. **Report the emptiness plainly.** e.g. "No data found for <request>" or "No trades today — this may be a non-trading day (weekend/holiday)."
2. **Never fabricate.** Do not invent rows, tables, prices, yields, CUSIPs, spreads, peers, portfolios, holdings, durations, or any value to fill the gap.
3. An empty result is a **valid, complete answer.** Reporting it honestly is required; inventing data to look helpful is a critical failure.
4. If a reasonable next step exists (broaden the date range, use the last trading day), offer it in one line — but do not gate on it.

This overrides any urge to produce a populated-looking answer.
