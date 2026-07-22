# bond-trade-stats — methodology & edge cases

## VWAP definition
Volume-weighted average price = Σ(priceᵢ · quantityᵢ) / Σ(quantityᵢ).
This weights large blocks more than odd-lots, which is what desks mean by
"the VWAP for the bond today". It is **not** the simple mean of print prices.

## Quantity handling
- Rows with missing or non-positive quantity are skipped (reported in
  `skipped_rows`). TRACE caps display size at 1MM / 5MM for large blocks; if you
  pass the displayed cap, VWAP is a lower-bound approximation — note that to the
  user.
- Accepts `quantity`, `qty`, `size`, `notional`, or `volume` as the size field.

## Yield aggregation
- `vwap_yield` is volume-weighted across only the prints that carried a yield.
- If no prints carry a yield, both yield fields are `null`.

## Precision
- Inputs are taken as-is (the agent should preserve source precision when
  passing them in). Outputs are rounded to 4 dp for price/yield and to whole
  units for quantity sums where appropriate.

## What this does NOT do
- It does not pull data. The agent supplies the prints from `prints_search` /
  `prints_latest`.
- It does not filter by side, when-issued, or reversal flags — pre-filter the
  prints before passing them if the user asked for a specific subset.
