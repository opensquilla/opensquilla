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

## A single bond named by coupon + maturity
References like "Microsoft 4.2% bond maturing November 2035", "Ford 27 4.85%", "AAPL 2.85% 2029",
or trader shorthand "180med 3.875% 29s" (issuer 180 Medical, 3.875% coupon, 2029 maturity) identify
ONE specific bond. Resolve it to a CUSIP first:
1. `securities_search(issuer=<issuer>, coupon_min/coupon_max≈<coupon>, maturity_start/maturity_end
   bracketing the year/month, limit="1")` to pin the CUSIP.
2. Then run the requested analytic (`prints_latest`, `prints_search`, `analytics_vwap`,
   `get_security_stats`, ...) on that CUSIP.
Never ask the user "could you provide the CUSIP?" when they already described the bond — resolve it
yourself, and state which bond/CUSIP you matched so any mismatch is visible.

## Ambiguous credit entities
When one name spans distinct credit profiles (e.g. "Ford" → Ford Motor Co vs Ford Motor Credit),
label the entities separately rather than mixing their bonds silently.
