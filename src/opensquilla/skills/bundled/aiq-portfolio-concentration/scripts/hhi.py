#!/usr/bin/env python3
"""portfolio-concentration / hhi.py

Compute portfolio concentration: per-group weights, top-N concentration, and
the Herfindahl-Hirschman Index (HHI). Pure stdlib.

Contract:
  argv[1] -> path to a JSON file (or stdin), shaped:
    {"holdings": [{"group": "..", "value": ..}, ...], "group_by": "..", "top_n": N}
  stdout -> a single JSON object with concentration statistics.
"""
import json
import sys
from collections import defaultdict

GROUP_KEYS = ("group", "issuer", "sector", "rating", "name", "ticker", "key")
VALUE_KEYS = ("value", "market_value", "mv", "notional", "weight", "par", "quantity")


def _first(row, keys):
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.replace(",", "").replace("$", "").replace("%", "").strip()
        if v == "":
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_input():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            return json.load(fh)
    return json.load(sys.stdin)


def _label(hhi):
    if hhi < 1500:
        return "diversified"
    if hhi < 2500:
        return "moderately concentrated"
    return "highly concentrated"


def compute(payload):
    rows = payload.get("holdings") or payload.get("rows") or payload.get("data") or []
    group_by = payload.get("group_by")
    top_n = int(payload.get("top_n") or 5)

    sums = defaultdict(float)
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        g = _first(row, GROUP_KEYS)
        v = _to_float(_first(row, VALUE_KEYS))
        if g is None or v is None or v <= 0:
            skipped += 1
            continue
        sums[str(g)] += v

    total = sum(sums.values())
    if total <= 0:
        return {
            "n_groups": 0,
            "skipped_rows": skipped,
            "error": "no usable holdings (need a group + positive value)",
        }

    weights = {g: v / total for g, v in sums.items()}
    # HHI on a 0..10000 scale: sum of squared percentage weights.
    hhi = sum((w * 100.0) ** 2 for w in weights.values())
    sum_sq = sum(w * w for w in weights.values())
    effective_n = 1.0 / sum_sq if sum_sq > 0 else float(len(weights))
    n = len(weights)
    # Normalized HHI in [0,1]: (H* - 1/n) / (1 - 1/n), where H* = sum_sq.
    hhi_norm = (sum_sq - 1.0 / n) / (1.0 - 1.0 / n) if n > 1 else 1.0

    ranked = sorted(sums.items(), key=lambda kv: kv[1], reverse=True)
    top = [
        {"group": g, "value": round(v, 4), "weight_pct": round(100.0 * v / total, 4)}
        for g, v in ranked[: max(top_n, 0)]
    ]

    return {
        "group_by": group_by,
        "total_value": round(total, 4),
        "n_groups": n,
        "skipped_rows": skipped,
        "hhi": round(hhi, 2),
        "hhi_normalized": round(hhi_norm, 4),
        "effective_n": round(effective_n, 3),
        "concentration_label": _label(hhi),
        "top_n": top,
        "top_n_weight_pct": round(sum(t["weight_pct"] for t in top), 4),
    }


def main():
    try:
        payload = load_input()
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"error": f"could not parse input: {exc}"}))
        sys.exit(2)
    print(json.dumps(compute(payload)))


if __name__ == "__main__":
    main()
