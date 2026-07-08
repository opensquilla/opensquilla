#!/usr/bin/env python3
"""Assert LLM treatment delivery from per-instance llm_calls.jsonl records.

Experiment arms must verify that configured treatments actually reached the
provider before a run is scored; any delivery mismatch makes the decision
``invalid``. This scans every ``llm.request`` record in each instance's
llm_calls.jsonl and asserts, on all requests:

- ``metadata.request_proof.proof_budget`` equals --expected-proof-budget
- ``payload.reasoning.effort`` equals --expected-reasoning-effort
  (OpenRouter/GLM adapter: effort string; payloads carry no numeric budget)
- ``payload.thinking_budget`` equals --expected-thinking-budget
  (DashScope/Qwen adapter: numeric budget)

The engine has a designed one-shot recovery that retries a failed provider
call with thinking disabled; the request shape is adapter-specific
(provider/openai.py): OpenRouter/GLM emits ``payload.reasoning = {"enabled":
false}``; DashScope/Qwen emits ``payload.enable_thinking = false`` with no
reasoning key and no thinking_budget. Such requests are counted separately
and excluded from the reasoning-effort and thinking-budget assertions, but
any occurrence beyond --allow-reasoning-fallbacks (default 0) is an error.
The proof-budget assertion still applies to them. (Detection assumes a
thinking-enabled arm; a deliberately thinking-off DashScope arm would count
every request as a fallback.)

Separately, an httpx stream timeout with no stream event triggers a
non-stream retry of the same budget-coordinated payload
(``_complete_non_stream``); its record carries ``metadata.fallback_from ==
"stream_timeout"`` and no ``request_proof`` block at all. These records are
excluded from the proof-budget assertion (the payload assertions still
apply), reported per instance as ``stream_fallbacks``, and never gated —
the treatment itself was delivered unchanged.

One stdout line per instance reports the request count and distinct observed
values. Exit is non-zero on any mismatch, unreadable request record, or
instance with zero ``llm.request`` records.

Known limit: lines are prefiltered on the substring ``"llm.request"`` before
JSON parsing, so a request line truncated within its first ~200 bytes (before
the ``event`` key) is skipped silently rather than counted as unparsed. Tail
truncation from a killed run cuts inside the large ``payload`` field instead,
which still matches the prefilter and lands in the unparsed-error path — and a
killed run is already invalid under the rc!=0 rule.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _instance_dirs(run_dir: Path) -> list[Path]:
    if (run_dir / "llm_calls.jsonl").is_file():
        return [run_dir]
    return sorted(child for child in run_dir.iterdir() if child.is_dir())


class _InstanceScan:
    def __init__(self) -> None:
        self.requests = 0
        self.unparsed = 0
        self.reasoning_fallbacks = 0
        self.stream_fallbacks = 0
        self.proof_budgets: set[object] = set()
        self.efforts: set[object] = set()
        self.thinking_budgets: set[object] = set()


def _scan_llm_requests(path: Path) -> _InstanceScan:
    scan = _InstanceScan()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"llm.request"' not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                scan.unparsed += 1
                continue
            if not isinstance(record, dict) or record.get("event") != "llm.request":
                continue
            scan.requests += 1
            metadata = record.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            payload = record.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            if metadata.get("fallback_from") == "stream_timeout":
                # Non-stream retry of a stream timeout re-sends the same
                # budget-coordinated payload, but its record carries no
                # request_proof metadata (provider/openai.py record_request).
                scan.stream_fallbacks += 1
            else:
                request_proof = metadata.get("request_proof")
                scan.proof_budgets.add(
                    request_proof.get("proof_budget") if isinstance(request_proof, dict) else None
                )
            reasoning = payload.get("reasoning")
            if reasoning == {"enabled": False} or payload.get("enable_thinking") is False:
                # Exact shapes the engine's one-shot thinking-disable recovery
                # emits (provider/openai.py): OpenRouter reasoning={"enabled":
                # false}; DashScope enable_thinking=false with no reasoning key
                # and no thinking_budget. Anything else is a treatment value.
                scan.reasoning_fallbacks += 1
            else:
                scan.efforts.add(reasoning.get("effort") if isinstance(reasoning, dict) else None)
                scan.thinking_budgets.add(payload.get("thinking_budget"))
    return scan


def _distinct(values: set[object]) -> str:
    return ",".join(sorted("null" if value is None else str(value) for value in values))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        action="append",
        required=True,
        type=Path,
        help=(
            "Run directory holding per-instance subdirectories with llm_calls.jsonl "
            "(or a single instance directory). May be repeated."
        ),
    )
    parser.add_argument(
        "--expected-proof-budget",
        type=int,
        default=None,
        help="Expected metadata.request_proof.proof_budget on every llm.request.",
    )
    parser.add_argument(
        "--expected-reasoning-effort",
        default=None,
        help="Expected payload.reasoning.effort string on every llm.request.",
    )
    parser.add_argument(
        "--expected-thinking-budget",
        type=int,
        default=None,
        help="Expected numeric payload.thinking_budget on every llm.request.",
    )
    parser.add_argument(
        "--allow-reasoning-fallbacks",
        type=int,
        default=0,
        help=(
            "Max engine thinking-disable recovery requests tolerated per "
            "instance (OpenRouter payload.reasoning.enabled == false, or "
            "DashScope payload.enable_thinking == false)."
        ),
    )
    args = parser.parse_args(argv)

    if (
        args.expected_proof_budget is None
        and args.expected_reasoning_effort is None
        and args.expected_thinking_budget is None
    ):
        parser.error("at least one --expected-* assertion is required")

    checked = 0
    errors = 0
    for run_dir in args.run_dir:
        if not run_dir.is_dir():
            print(f"missing_run_dir: {run_dir}", file=sys.stderr)
            errors += 1
            continue
        instance_dirs = _instance_dirs(run_dir)
        if not instance_dirs:
            print(f"no_instances: {run_dir}", file=sys.stderr)
            errors += 1
            continue
        for instance_dir in instance_dirs:
            checked += 1
            instance_id = instance_dir.name
            calls_path = instance_dir / "llm_calls.jsonl"
            if not calls_path.is_file():
                print(f"missing_llm_calls: {instance_id}", file=sys.stderr)
                errors += 1
                continue
            scan = _scan_llm_requests(calls_path)
            print(
                f"instance={instance_id} requests={scan.requests} "
                f"proof_budget={_distinct(scan.proof_budgets)} "
                f"reasoning_effort={_distinct(scan.efforts)} "
                f"reasoning_fallbacks={scan.reasoning_fallbacks} "
                f"stream_fallbacks={scan.stream_fallbacks} "
                f"thinking_budget={_distinct(scan.thinking_budgets)}"
            )
            if scan.unparsed:
                print(
                    f"unparsed_request_lines: {instance_id} count={scan.unparsed}",
                    file=sys.stderr,
                )
                errors += 1
            if scan.requests == 0:
                print(f"no_llm_requests: {instance_id}", file=sys.stderr)
                errors += 1
                continue
            if scan.reasoning_fallbacks > args.allow_reasoning_fallbacks:
                print(
                    f"reasoning_fallback_exceeded: {instance_id} "
                    f"count={scan.reasoning_fallbacks} "
                    f"allowed={args.allow_reasoning_fallbacks}",
                    file=sys.stderr,
                )
                errors += 1
            if args.expected_proof_budget is not None and scan.proof_budgets != {
                args.expected_proof_budget
            }:
                print(
                    f"proof_budget_mismatch: {instance_id} "
                    f"expected={args.expected_proof_budget} "
                    f"actual={_distinct(scan.proof_budgets)}",
                    file=sys.stderr,
                )
                errors += 1
            if args.expected_reasoning_effort is not None and scan.efforts != {
                args.expected_reasoning_effort
            }:
                print(
                    f"reasoning_effort_mismatch: {instance_id} "
                    f"expected={args.expected_reasoning_effort} "
                    f"actual={_distinct(scan.efforts)}",
                    file=sys.stderr,
                )
                errors += 1
            if args.expected_thinking_budget is not None and scan.thinking_budgets != {
                args.expected_thinking_budget
            }:
                print(
                    f"thinking_budget_mismatch: {instance_id} "
                    f"expected={args.expected_thinking_budget} "
                    f"actual={_distinct(scan.thinking_budgets)}",
                    file=sys.stderr,
                )
                errors += 1

    if errors:
        print(f"checked={checked} errors={errors}", file=sys.stderr)
        return 1

    print(f"checked={checked} errors=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
