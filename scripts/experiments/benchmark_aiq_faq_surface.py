"""Measure AIQ FAQ tool-surface selection without calling a model or data tool."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

from opensquilla.contrib.aiq.catalog import AiqToolDef, load_catalog
from opensquilla.contrib.aiq.query_profiles import select_aiq_tool_surface

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True, help="21-question FAQ JSONL")
    parser.add_argument(
        "--iterations",
        type=int,
        default=1_000,
        help="Number of selector passes over the complete task file",
    )
    return parser


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != 21:
        raise ValueError(f"expected the 21-question FAQ fixture, found {len(rows)} rows")
    if len({str(row.get("id")) for row in rows}) != len(rows):
        raise ValueError("task ids must be unique")
    return rows


def _serialized_tool_bytes(tools: list[AiqToolDef]) -> int:
    payload = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": tool.params,
                "required": tool.required,
            },
        }
        for tool in tools
    ]
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _skill_bytes(skill_name: str | None) -> int:
    if not skill_name:
        return 0
    path = REPO_ROOT / "src" / "opensquilla" / "skills" / "bundled" / skill_name / "SKILL.md"
    return len(path.read_bytes())


def main() -> int:
    args = _parser().parse_args()
    if args.iterations < 1:
        raise ValueError("--iterations must be positive")

    tasks = _load_tasks(args.tasks)
    catalog = list(load_catalog())
    by_name = {tool.name: tool for tool in catalog}
    full_schema_bytes = _serialized_tool_bytes(catalog)

    rows: list[dict[str, Any]] = []
    for task in tasks:
        selection = select_aiq_tool_surface(str(task["query"]))
        if selection is None:
            effective_names = tuple(by_name)
            selected_tools = catalog
            profile = None
            skill_name = None
            maximum = None
            guidance_bytes = 0
        else:
            # The turn-runner adapter preloads the selected skill and removes
            # skill_view before provider tool schemas are assembled.
            effective_names = tuple(
                name
                for name in selection.tool_names
                if not (selection.preload_skill and name == "skill_view")
            )
            selected_tools = [by_name[name] for name in effective_names if name in by_name]
            profile = selection.profile
            skill_name = selection.skill_name
            maximum = selection.max_iterations
            guidance_bytes = len(selection.guidance.encode("utf-8"))
        schema_bytes = _serialized_tool_bytes(selected_tools)
        skill_bytes = _skill_bytes(skill_name)
        rows.append(
            {
                "id": task["id"],
                "profile": profile,
                "effective_tools": list(effective_names),
                "effective_tool_count": len(effective_names),
                "preloaded_skill": skill_name,
                "max_iterations": maximum,
                "provider_tool_schema_bytes": schema_bytes,
                "tool_schema_reduction_pct": round(
                    (1 - schema_bytes / full_schema_bytes) * 100, 2
                ),
                "preloaded_skill_bytes": skill_bytes,
                "guidance_bytes": guidance_bytes,
                "request_control_bytes": schema_bytes + skill_bytes + guidance_bytes,
            }
        )

    # Warm the regex and selector module before measuring the deterministic boundary.
    for task in tasks:
        select_aiq_tool_surface(str(task["query"]))
    timings_us: list[float] = []
    started = time.perf_counter_ns()
    for _ in range(args.iterations):
        for task in tasks:
            call_started = time.perf_counter_ns()
            select_aiq_tool_surface(str(task["query"]))
            timings_us.append((time.perf_counter_ns() - call_started) / 1_000)
    total_ms = (time.perf_counter_ns() - started) / 1_000_000

    schema_sizes = [float(row["provider_tool_schema_bytes"]) for row in rows]
    request_control_sizes = [float(row["request_control_bytes"]) for row in rows]
    reductions = [float(row["tool_schema_reduction_pct"]) for row in rows]
    output = {
        "benchmark": "aiq_faq_tool_surface_v1",
        "offline_only": True,
        "task_count": len(tasks),
        "unmatched_task_count": sum(row["profile"] is None for row in rows),
        "full_aiq_catalog": {
            "tool_count": len(catalog),
            "provider_tool_schema_bytes": full_schema_bytes,
        },
        "selected_surface": {
            "median_tool_count": statistics.median(
                row["effective_tool_count"] for row in rows
            ),
            "max_tool_count": max(row["effective_tool_count"] for row in rows),
            "median_provider_tool_schema_bytes": statistics.median(schema_sizes),
            "max_provider_tool_schema_bytes": max(schema_sizes),
            "median_request_control_bytes": statistics.median(request_control_sizes),
            "max_request_control_bytes": max(request_control_sizes),
            "median_schema_reduction_pct": statistics.median(reductions),
            "preloaded_skill_tasks": sum(bool(row["preloaded_skill"]) for row in rows),
            "zero_tool_tasks": sum(row["effective_tool_count"] == 0 for row in rows),
            "profiles": dict(sorted(Counter(row["profile"] for row in rows).items())),
        },
        "selector_latency": {
            "calls": len(timings_us),
            "total_ms": round(total_ms, 3),
            "p50_us": round(_percentile(timings_us, 0.50), 3),
            "p95_us": round(_percentile(timings_us, 0.95), 3),
            "p99_us": round(_percentile(timings_us, 0.99), 3),
        },
        "tasks": rows,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
