---
name: aiq-entity-resolution
description: >-
  How to resolve issuers and specific bonds from messy user references — multi-issuer lists ("J&J, P&G, Berkshire"), abbreviations/tickers, fuzzy issuer names, and a single bond named by coupon+maturity ("Microsoft 4.2% Nov 2035", "Ford 27 4.85%", "180med 3.875% 29s"). Use when issuers or bonds are referenced by ticker, abbreviation, fuzzy name, or coupon+maturity shorthand.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "🔎"
---

# Entity & bond resolution (issuers, tickers, single bonds)

## Multiple issuers in one request
"Show me bonds from J&J, P&G, and Berkshire ..." names SEVERAL issuers. Resolve EACH:
1. Normalise each to its full issuer name (J&J → Johnson & Johnson; P&G → Procter & Gamble;
   Berkshire → Berkshire Hathaway).
2. Call `securities_search` once per issuer (or combine if the tool supports a list) and merge the
   rows into ONE table. Never silently drop an issuer because the first one returned enough rows.
3. Apply the shared filters (maturity window, sort order, credit grade) to every issuer's query.

## Tickers, abbreviations, fuzzy names
- Tickers / short forms ("AAPL", "MSFT", "TSLA") and partial names map to the issuer via
  `securities_search(issuer=...)` — `issuer` is a partial match, so pass the cleanest issuer string.
- For a clearly fictitious or unknown issuer ("Acme Widgets"), run the search; if it returns nothing,
  report "no bonds found for <issuer>" — do NOT fabricate CUSIPs or substitute a real issuer.

## Bare identifiers and latest bond cards

- A bare 9-character CUSIP is a request for one full bond card. Call
  `securities_search(cusip_id=<CUSIP>, detail='full', limit='1')` once and show only returned
  identity, coupon/maturity, latest price/yield/G-spread, rating/sector, source, and as-of fields.
  Name null or absent fields as unavailable; never fill them from memory.
- For a named bond's latest price, yield, and Treasury spread, resolve issuer + coupon + maturity in
  one `detail='full'` search. `g_spread_bps` is the tool-returned spread to the matched Treasury
  curve. Do not substitute CP+ difference, OAS, or a hand calculation.

## A single bond named by coupon + maturity
References like "Microsoft 4.2% bond maturing November 2035", "Ford 27 4.85%", "AAPL 2.85% 2029",
or trader shorthand "180med 3.875% 29s" (issuer 180 Medical, 3.875% coupon, 2029 maturity) identify
ONE specific bond. Resolve it to a CUSIP first:
1. `securities_search(issuer=<issuer>, coupon_min/coupon_max≈<coupon>, maturity_start/maturity_end
   bracketing the year/month, limit="1")` to pin the CUSIP.
2. For recent trades, keep resolution and retrieval in one model-visible call: add
   `detail='compact', include_recent_prints='true', recent_prints_limit=<N>`. Read the verified CUSIP
   and tape from `related_data`; do not call `prints_search` again. State that capped TRACE sizes are
   minimums.
3. For other analytics, run the requested tool (`analytics_vwap`, `get_security_stats`, ...) on the
   verified CUSIP.
Never ask the user "could you provide the CUSIP?" when they already described the bond — resolve it
yourself, and state which bond/CUSIP you matched so any mismatch is visible.

Call the resolving search and the requested analytic silently. Do not leave "now I'll fetch" or
"fetching trades" narration in the answer; the first visible text is the resolved result/table.

For relative maturity ranges, preserve both endpoints. A request for 5–7Y means an explicit
today+5Y through today+7Y screen; do not replace it with a single 6Y bucket.

## Ambiguous credit entities
When one name spans distinct credit profiles (e.g. "Ford" → Ford Motor Co vs Ford Motor Credit),
label the entities separately rather than mixing their bonds silently.
