#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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


def required_decimal(value: object, *, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} is missing or non-numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a valid decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return parsed


def recorded_openrouter_cost(path: Path) -> Decimal:
    total = Decimal(0)
    rows = 0
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line, parse_float=Decimal, parse_int=Decimal)
            if not isinstance(row, dict):
                raise ValueError(f"result row {line_number} is not an object")
            accounting = row.get("cost_accounting")
            llm_total = accounting.get("llm_total") if isinstance(accounting, dict) else None
            if not isinstance(llm_total, dict):
                raise ValueError(f"result row {line_number} lacks llm_total cost accounting")
            request_count = required_decimal(
                llm_total.get("request_count"),
                label=f"result row {line_number} request_count",
            )
            exact_request_count = required_decimal(
                llm_total.get("exact_request_count"),
                label=f"result row {line_number} exact_request_count",
            )
            if (
                llm_total.get("cost_exact") is not True
                or request_count != exact_request_count
            ):
                raise ValueError(
                    f"result row {line_number} does not have exact OpenRouter cost"
                )
            total += required_decimal(
                llm_total.get("recorded_cost_usd"),
                label=f"result row {line_number} recorded_cost_usd",
            )
            rows += 1
    if rows == 0:
        raise ValueError("result JSONL contains no rows")
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--secret-file",
        type=Path,
        default=Path.home() / ".config" / "opensquilla" / "secrets" / "openrouter.key",
    )
    parser.add_argument(
        "--expected-key-env",
        help=(
            "Fail unless this environment variable contains the same API key as "
            "--secret-file; only the SHA-256 fingerprint is persisted."
        ),
    )
    parser.add_argument("--settle-from", type=Path)
    parser.add_argument("--settle-result-jsonl", type=Path)
    parser.add_argument("--settle-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--settle-poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--settle-tolerance-usd", type=float, default=0.000001)
    args = parser.parse_args()
    if bool(args.settle_from) != bool(args.settle_result_jsonl):
        parser.error("--settle-from and --settle-result-jsonl must be provided together")
    timeout = required_decimal(
        args.settle_timeout_seconds, label="settlement timeout seconds"
    )
    poll_interval = required_decimal(
        args.settle_poll_interval_seconds,
        label="settlement poll interval seconds",
    )
    tolerance = required_decimal(
        args.settle_tolerance_usd,
        label="settlement tolerance",
    )

    key = args.secret_file.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit("OpenRouter credential file is empty")
    key_fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if args.expected_key_env:
        environment_key = os.environ.get(args.expected_key_env, "").strip()
        if not environment_key:
            raise SystemExit(
                f"Expected OpenRouter key environment variable is empty: "
                f"{args.expected_key_env}"
            )
        environment_fingerprint = hashlib.sha256(
            environment_key.encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(key_fingerprint, environment_fingerprint):
            raise SystemExit(
                "OpenRouter secret file does not match the benchmark process key"
            )
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}"},
    )

    def fetch() -> dict[str, object]:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(
                response.read().decode("utf-8"),
                parse_float=Decimal,
                parse_int=Decimal,
            )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("OpenRouter key response lacks a data object")
        required_decimal(data.get("usage"), label="OpenRouter usage")
        required_decimal(data.get("byok_usage"), label="OpenRouter byok_usage")
        return data

    settlement = None
    if args.settle_from and args.settle_result_jsonl:
        baseline = json.loads(
            args.settle_from.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
        )
        if not isinstance(baseline, dict):
            raise ValueError("settlement baseline snapshot must be an object")
        baseline_fingerprint = str(baseline.get("api_key_sha256") or "")
        if not baseline_fingerprint or not hmac.compare_digest(
            baseline_fingerprint, key_fingerprint
        ):
            raise ValueError("settlement baseline API key fingerprint does not match")
        if baseline.get("benchmark_environment_key_verified") is not True:
            raise ValueError(
                "settlement baseline did not verify the benchmark environment key"
            )
        baseline_usage = required_decimal(
            baseline.get("usage"), label="settlement baseline usage"
        )
        expected_delta = recorded_openrouter_cost(args.settle_result_jsonl)
        deadline = time.monotonic() + float(timeout)
        attempts = 0
        while True:
            attempts += 1
            data = fetch()
            observed_delta = required_decimal(
                data.get("usage"), label="OpenRouter usage"
            ) - baseline_usage
            if observed_delta < 0:
                raise ValueError("OpenRouter usage decreased relative to the baseline")
            if observed_delta + tolerance >= expected_delta:
                settlement = {
                    "attempts": attempts,
                    "expected_recorded_cost_usd": str(expected_delta),
                    "observed_usage_delta_usd": str(observed_delta),
                    "tolerance_usd": str(tolerance),
                }
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "OpenRouter usage did not settle to the recorded benchmark cost "
                    f"within {float(timeout):g}s"
                )
            time.sleep(max(0.1, float(poll_interval)))
    else:
        data = fetch()

    def safe_json_value(value: object) -> object:
        return str(value) if isinstance(value, Decimal) else value

    safe = {
        "captured_at": datetime.now(UTC).isoformat(),
        "api_key_sha256": key_fingerprint,
        "benchmark_environment_key_verified": bool(args.expected_key_env),
        "settlement": settlement,
        **{field: safe_json_value(data.get(field)) for field in SAFE_FIELDS},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, args.output)
    print(json.dumps(safe, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
