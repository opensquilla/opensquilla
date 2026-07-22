# portfolio-concentration — HHI reference

## Herfindahl-Hirschman Index (HHI)
HHI = Σ (wᵢ × 100)²  where wᵢ is each group's fractional weight of the book.

- A perfectly diversified book of N equal names has HHI = 10000 / N.
- A single-name book has HHI = 10000.

### Bands (sum-of-squared-percent convention)
| HHI | Read |
|-----|------|
| < 1500 | diversified |
| 1500–2500 | moderately concentrated |
| > 2500 | highly concentrated |

These mirror the US DOJ/FTC merger-guideline thresholds, repurposed here as a
familiar yardstick for credit-book concentration.

## Effective number of names
effective_n = 1 / Σ wᵢ². It answers "this book behaves like how many
equally-weighted names?" — a 10-name book where one name is 50% has an
effective_n well below 10.

## Normalized HHI
hhi_normalized rescales the raw index to [0, 1] adjusting for the group count,
so books with different numbers of names are comparable:
  (Σwᵢ² − 1/n) / (1 − 1/n).
0 = perfectly even, 1 = fully concentrated in one group.

## Grouping
Pass `group` set to whatever dimension the user asked about (issuer, sector,
rating). Re-run with a different grouping to answer "by sector" vs "by issuer".
Rows sharing a group are summed first.
