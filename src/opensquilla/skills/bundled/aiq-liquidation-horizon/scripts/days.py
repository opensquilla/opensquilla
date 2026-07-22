#!/usr/bin/env python3
"""liquidation-horizon / days.py

Estimate days-to-liquidate for a position under a participation-rate cap.
Pure stdlib.

Contract:
  argv[1] -> path to a JSON file (or stdin), shaped:
    {"position_size": .., "adv": .., "participation_rate": .., "label": ".."}
  stdout -> a single JSON object with the liquidation estimate.
"""
import json
import math
import sys

POS_KEYS = ("position_size", "position", "size", "notional")
ADV_KEYS = ("adv", "avg_daily_volume", "adv_notional", "daily_volume", "average_daily_volume")
POV_KEYS = ("participation_rate", "max_participation", "pov", "rate")


def _first(d, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


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


def _label(days):
    if days <= 1:
        return "liquid (exits within a session)"
    if days <= 3:
        return "fairly liquid"
    if days <= 10:
        return "moderately liquid"
    return "illiquid relative to size"


def compute(payload):
    position = _to_float(_first(payload, POS_KEYS))
    adv = _to_float(_first(payload, ADV_KEYS))
    pov = _to_float(_first(payload, POV_KEYS))
    label = payload.get("label")

    if pov is None:
        pov = 0.20
    # Allow either fraction (0.20) or percent (20) input.
    if pov > 1:
        pov = pov / 100.0

    if position is None or position <= 0:
        return {"error": "position_size must be a positive number"}
    if adv is None or adv <= 0:
        return {"error": "adv (average daily volume) must be a positive number"}
    if pov <= 0 or pov > 1:
        return {"error": "participation_rate must be in (0, 1]"}

    daily_capacity = adv * pov
    days = position / daily_capacity

    return {
        "label": label,
        "position_size": round(position, 4),
        "adv": round(adv, 4),
        "participation_rate": round(pov, 4),
        "daily_capacity": round(daily_capacity, 4),
        "days_to_liquidate": round(days, 2),
        "days_to_liquidate_whole": int(math.ceil(days)),
        "position_vs_adv_x": round(position / adv, 3),
        "liquidity_label": _label(days),
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
