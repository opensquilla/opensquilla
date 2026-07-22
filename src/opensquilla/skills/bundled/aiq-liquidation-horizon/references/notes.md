# liquidation-horizon — notes & caveats

## Model
days_to_liquidate = position_size / (ADV × participation_rate).

We assume you will trade up to `participation_rate` of average daily volume each
session and that ADV is stable. The default participation rate is 20% — a
common "don't-move-the-market" cap for credit. Lower it (e.g. 0.10) for thin
names, raise it (e.g. 0.30) if the user is comfortable being a larger share.

## Liquidity bands (whole sessions)
| Days | Read |
|------|------|
| ≤ 1 | liquid — exits within a session |
| ≤ 3 | fairly liquid |
| ≤ 10 | moderately liquid |
| > 10 | illiquid relative to size |

## Position vs ADV
`position_vs_adv_x` is the raw size/ADV multiple, independent of participation
rate. > ~3× ADV usually means a multi-day, market-impactful unwind.

## Caveats to surface to the user
- ADV from TRACE understates true tradeable volume because large blocks are
  display-capped at 1MM / 5MM. Treat the estimate as conservative (slower).
- Liquidity is regime-dependent; a stress event can collapse ADV. This is a
  steady-state estimate, not a fire-sale estimate.
- Use the same units for `position_size` and `adv` (both notional, or both par).
