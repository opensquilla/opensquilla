---
name: aiq-transaction-cost-analysis
description: >-
  How to run TCA / execution-quality analysis on a user's fill — "we bought $5M at 111.3, was it a good execution?", "analyze this trade vs VWAP", slippage vs arrival/VWAP, and flagging illiquid or stale prints. Benchmark the fill against tool-backed market data, never against assumed numbers. Use when a user supplies a fill and asks about execution quality, slippage, or a trade vs VWAP/arrival.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "💱"
---

# Transaction-cost analysis (execution quality)

When the user gives an execution (side, size, bond, fill price) and asks whether it was good,
benchmark the FILL against real market data — do not assert "good"/"bad" from intuition.

1. **Resolve the bond to a CUSIP** from the description (coupon + maturity + issuer) via
   `securities_search`. See the aiq-entity-resolution skill if the reference is shorthand.

2. **Pull the right benchmark price(s)** for the fill:
   - Arrival / last print around the trade → `prints_latest` or `prints_search` (filter to the
     stated time window if given, e.g. "2:00-3:00 PM ET yesterday").
   - VWAP over the relevant window → `analytics_vwap(cusips=[...], window=...)` for `vwap_price`.

3. **Compute slippage in price and basis points**, signed by side:
   - Buy: positive slippage (paid UP vs benchmark) is a cost; a fill BELOW VWAP/arrival is favorable.
   - Sell: the mirror — sold ABOVE benchmark is favorable.
   - slippage_bps ≈ (fill − benchmark) / benchmark × 10000, sign-adjusted for side.
   Report the fill, the benchmark used (name it: "5-day VWAP", "arrival print at HH:MM"), and the
   slippage in both price points and bps. Show your benchmark so the read is auditable.

4. **Flag data-quality caveats — they change the conclusion:**
   - Thin/illiquid name (very low `trade_count` / `total_par` in the window) → the VWAP is a weak
     benchmark; say so explicitly rather than over-claiming precision.
   - Stale last print (old timestamp) → flag staleness; don't treat an old print as live arrival.
   - If there are NO comparable prints in the window, say the execution can't be benchmarked from the
     tape rather than inventing a benchmark.

5. **No manual math on numbers the user pasted in lieu of market data.** Anchor every benchmark to a
   tool result; the only arithmetic you do is the slippage of their fill against tool-backed prices.
