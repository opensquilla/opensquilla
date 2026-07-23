---
name: aiq-new-issuance-queries
description: >-
  How to answer new-issuance / primary-market queries ("bonds issued today", "new issuances in the last 30 days", "$1bn+ deals this month", "new HY supply in Energy") — route to securities_search with issue_start/issue_end, not the trade tape. Use when asked about bonds issued, priced, or brought to market in a given window (primary-market supply).
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🆕"
---

# New-issuance (primary-market) queries

New-issuance asks about when a bond was **issued / came to market**, NOT when it last traded.
Route ALL of these to `securities_search` using the issue-date window — never `prints_search`.

1. **Map the time phrase to `issue_start` / `issue_end`** (both `YYYY-MM-DD`):
   - "issued today" → `issue_start` = `issue_end` = today.
   - "in the last month" / "last 30 days" → `issue_start` = today − 30d, `issue_end` = today.
   - "this week" / "last week" → the corresponding 7-day window.
   - "new issuances in 2024" → `issue_start='2024-01-01'`, `issue_end='2024-12-31'`.
   Resolve "today" from the current date; never leave the window open-ended.

2. **Carry EVERY other constraint into a tool parameter** (none silently dropped):
   - sector ("in the Real Estate sector") → `sector`.
   - credit grade ("IG"/"HY"/"investment-grade") → `credit_grade`.
   - issuer ("from Apple") → `issuer`.
   - coupon / yield / maturity bounds → `coupon_min/max`, `yield_min/max`, `maturity_start/end`.

3. **Offering size ($1bn+) is NOT a usable filter.** `offering_amt` is ~99.98% null, so there is
   no `offering_min`/`offering_max` LLM parameter. Do NOT invent one and do NOT fabricate an
   offering-size column. Run the rest of the screen, return the matches, and state in one line that
   offering size isn't available as a reliable filter rather than gating or refusing the whole query.

4. **Show the issue date as a visible column** (and sector/industry when the query was sector-scoped),
   so the user can see each row satisfies the window.

5. **Empty is a valid answer.** "No bonds were issued today" (e.g. a weekend/holiday) is complete and
   correct — report it; never backfill with bonds issued on other dates or with secondary-market trades.

## Recent performance in one call

For "how have new issue IG bonds performed over the last 5 trading sessions," make one
`securities_search` call with `detail='compact'`, the resolved recent issue-date window,
`credit_grade='IG'`, and `include_period_history='day'`. The tool batches daily TRACE history for at
most five representative, deduplicated coupon/maturity tranches into `related_data`; do not call
`prints_group_by_period` separately.

Calculate a tranche's change only from the earliest and latest returned daily VWAP values and name
both endpoint dates. Never assume an issue price of par, and never use a current price below 100 as
proof of negative performance. If the returned period lists are empty or do not span the requested
sessions, call it a coverage gap and say performance is not measurable from the available history.
Do not infer demand, flows, dealer inventory, or liquidity causes from price performance alone.
