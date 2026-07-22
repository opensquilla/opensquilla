---
name: aiq-negation-and-exclusion
description: >-
  How to handle negation / exclusion queries correctly — "bonds that have NOT traded in N days", "exclude callables", "non-financial issuers", "without HY". The result must satisfy the negation; never return the inverse (items that DID match the excluded condition). Use when a query contains NOT / exclude / non- / without conditions.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🚫"
---

# Negation & exclusion queries

The single biggest failure mode here is answering with the INVERSE of what was asked. A
"has NOT traded" query must never be answered with bonds that DID trade.

## "Have not traded" / untraded / silent bonds
"Which IG bonds maturing after 10y have NOT traded at all in the past N days?":
1. Call `securities_search` with `liquidity_max_trades='0'` and
   `liquidity_lookback_days` = the user's window (e.g. '3' for "past 3 days", '30' for "past month").
2. The server-side filter returns ONLY bonds meeting the negation — do not post-filter, and do NOT
   use `prints_search` (that finds bonds that traded, the opposite).
3. Apply every other constraint (credit_grade='IG', maturity_start to enforce ">10y", sector).
4. **Zero rows is a valid, correct answer** ("no matching bonds are completely untraded in the
   window") — surface it. NEVER widen to traded bonds to fill the table; that inverts the request.
5. State the lookback window you used in the reply.

## "Exclude X" / "non-X" / "without X" filters
Map the exclusion onto a tool parameter or a filtered query:
- "exclude callables" / "non-callable only" → `is_callable='false'`.
- "non-financial" / "everything but Financials" → run the screen without that sector, or filter it
  out of the rows; do not return Financials.
- "investment-grade, no HY" → `credit_grade='IG'`.
Then briefly restate the exclusion you applied so the user can see it was honoured.

## Verify before answering
Before sending, re-read the request: does every returned row satisfy the NEGATION? If any row
matches the thing the user wanted excluded, the answer is wrong — fix the filter, don't ship it.
