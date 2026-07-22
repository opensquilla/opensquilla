#!/usr/bin/env python3
"""bond-trade-stats / compute.py

Compute VWAP, mean/median price & yield, total notional and price stdev over a
set of TRACE prints. Pure stdlib so it runs in the skill sandbox.

Contract:
  argv[1] -> path to a JSON file (or read JSON from stdin), shaped:
    {"prints": [{"price": .., "quantity": .., "yield": ..}, ...], "label": ".."}
  stdout -> a single JSON object with the computed statistics.
"""
import json
import statistics
import sys

PRICE_KEYS = ("price", "px", "last_price", "last_px")
QTY_KEYS = ("quantity", "qty", "size", "notional", "volume")
YIELD_KEYS = ("yield", "yld", "ytm", "last_yield")


def _first(row, keys):
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.replace(",", "").replace("$", "").strip()
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


def compute(payload):
    rows = payload.get("prints") or payload.get("rows") or payload.get("data") or []
    label = payload.get("label")

    prices, qtys, yields = [], [], []
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        p = _to_float(_first(row, PRICE_KEYS))
        q = _to_float(_first(row, QTY_KEYS))
        y = _to_float(_first(row, YIELD_KEYS))
        if p is None or q is None or q <= 0:
            skipped += 1
            continue
        prices.append(p)
        qtys.append(q)
        if y is not None:
            yields.append((y, q))

    n = len(prices)
    if n == 0:
        return {
            "n_prints": 0,
            "skipped_rows": skipped,
            "error": "no usable prints (need price + positive quantity)",
        }

    total_qty = sum(qtys)
    vwap_price = sum(p * q for p, q in zip(prices, qtys)) / total_qty

    out = {
        "label": label,
        "n_prints": n,
        "skipped_rows": skipped,
        "total_quantity": round(total_qty, 4),
        "vwap_price": round(vwap_price, 4),
        "mean_price": round(statistics.fmean(prices), 4),
        "median_price": round(statistics.median(prices), 4),
        "min_price": round(min(prices), 4),
        "max_price": round(max(prices), 4),
        "price_stdev": round(statistics.pstdev(prices), 4) if n > 1 else 0.0,
        "vwap_yield": None,
        "median_yield": None,
    }

    if yields:
        y_total_qty = sum(q for _, q in yields)
        out["vwap_yield"] = round(sum(y * q for y, q in yields) / y_total_qty, 4)
        out["median_yield"] = round(statistics.median([y for y, _ in yields]), 4)

    return out


def main():
    try:
        payload = load_input()
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"error": f"could not parse input: {exc}"}))
        sys.exit(2)
    print(json.dumps(compute(payload)))


if __name__ == "__main__":
    main()
