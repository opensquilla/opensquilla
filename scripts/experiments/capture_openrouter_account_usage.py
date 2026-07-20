#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SAFE_FIELDS = (
    "usage",
    "usage_daily",
    "usage_weekly",
    "usage_monthly",
    "byok_usage",
    "byok_usage_daily",
    "byok_usage_weekly",
    "byok_usage_monthly",
    "limit",
    "limit_remaining",
    "is_free_tier",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--secret-file",
        type=Path,
        default=Path("/home/codex/.config/opensquilla/secrets/openrouter.key"),
    )
    args = parser.parse_args()

    key = args.secret_file.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit("OpenRouter credential file is empty")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)["data"]

    safe = {
        "captured_at": datetime.now(UTC).isoformat(),
        **{field: data.get(field) for field in SAFE_FIELDS},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(args.output, 0o600)
    print(json.dumps(safe, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
