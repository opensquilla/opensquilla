#!/usr/bin/env python3
"""Create a one-row, non-benchmark DRACO canary and its frozen config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

CANARY_TASK_ID = "opensquilla-draco-b2-readiness-canary-v1"
CANARY_PROMPT = (
    """This is a benchmark readiness canary, not a scored benchmark task.

You must use both available tools before answering:
1. Call web_search for "IANA example domains".
2. Call web_fetch on https://example.com/.

Then answer in two short bullets: identify the organization associated with example domains """
    "and state the page title or purpose observed at example.com. Include the fetched URL."
)
CANARY_RUBRIC = {
    "id": "opensquilla-draco-b2-readiness-canary-rubric-v1",
    "sections": [
        {
            "id": "readiness",
            "title": "Readiness",
            "criteria": [
                {
                    "id": "reports-example-domain-evidence",
                    "weight": 10,
                    "requirement": (
                        "Reports that IANA maintains/reserves example domains and "
                        "describes the example.com page, including its URL"
                    ),
                }
            ],
        }
    ],
}


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--benchmark-input", type=Path, required=True)
    parser.add_argument("--output-input", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    args = parser.parse_args()
    if args.output_input.resolve(strict=False) == args.output_config.resolve(
        strict=False
    ):
        parser.error("canary input and config outputs must be distinct files")
    for output in (args.output_input, args.output_config):
        if output.exists():
            parser.error(f"refusing to overwrite canary artifact: {output}")

    benchmark_ids: set[str] = set()
    benchmark_prompts: set[str] = set()
    with args.benchmark_input.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                parser.error(f"invalid benchmark JSONL line {line_number}: {exc}")
            if not isinstance(row, dict):
                parser.error(f"benchmark JSONL line {line_number} is not an object")
            benchmark_ids.add(str(row.get("task_id") or row.get("id") or ""))
            benchmark_prompts.add(
                str(
                    row.get("prompt")
                    if row.get("prompt") is not None
                    else row.get("problem") or ""
                )
            )
    if CANARY_TASK_ID in benchmark_ids or CANARY_PROMPT in benchmark_prompts:
        parser.error("canary task overlaps the formal benchmark input")

    canary_row: dict[str, Any] = {
        "id": CANARY_TASK_ID,
        "prompt": CANARY_PROMPT,
        "answer": json.dumps(CANARY_RUBRIC, ensure_ascii=False, separators=(",", ":")),
        "domain": "Readiness Canary",
        "metadata": {"formal_benchmark_member": False, "schema": "draco-canary/v1"},
    }
    input_bytes = (
        json.dumps(canary_row, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    config = json.loads(args.base_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        parser.error("base experiment config must contain a JSON object")
    benchmark_input = config.get("benchmark_input")
    runner = config.get("runner")
    judge = config.get("judge")
    if not all(isinstance(item, dict) for item in (benchmark_input, runner, judge)):
        parser.error("base config is missing benchmark_input/runner/judge objects")
    config["benchmark_input"] = {
        "name": "DRACO readiness canary (excluded from benchmark metrics)",
        "sha256": hashlib.sha256(input_bytes).hexdigest(),
        "task_count": 1,
        "task_ids": [CANARY_TASK_ID],
        "enforce_reference_input": True,
    }
    config["runner"] = {**runner, "concurrency": 1}
    config["judge"] = {**judge, "concurrency": 1}
    config_bytes = (
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    # Validate and render both artifacts before publishing either one.  A bad
    # base config must not leave a half-created canary pair behind.
    atomic_write(args.output_input, input_bytes)
    atomic_write(args.output_config, config_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
