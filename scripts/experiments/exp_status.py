#!/usr/bin/env python3
"""Print the current OpenSquilla experiment ledger status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from exp_common import (
    LedgerError,
    active_processes,
    active_swe_containers,
    contamination_class_for,
    exp_dir,
    git_info,
    ledger_root_from_env,
    load_contaminations,
    read_json,
    run_dir_contamination_classes,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--handoff-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        status = collect_status(args.source_root, args.handoff_root)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(render_text(status))
    return 0


def collect_status(source_root: Path, handoff_root: Path) -> dict[str, Any]:
    ledger_root = ledger_root_from_env()
    current = read_json(ledger_root / "current.json")
    baselines = read_json(ledger_root / "baselines.json")
    mechanisms = read_json(ledger_root / "mechanisms.json")
    source = git_info(source_root)
    handoff = git_info(handoff_root)
    processes = active_processes()
    warnings = []
    active_exp_id = current.get("active_experiment")
    active_manifest = None
    active_manifest_payload: dict[str, Any] = {}
    active_live_status: dict[str, Any] | None = None
    if active_exp_id:
        run_dir = exp_dir(ledger_root, str(active_exp_id))
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            active_manifest = str(manifest_path)
            active_manifest_payload = read_json(manifest_path)
        else:
            warnings.append(f"active experiment manifest missing: {active_exp_id}")
        live_status_path = run_dir / "live_status.json"
        if live_status_path.exists():
            active_live_status = read_json(live_status_path)
    containers = active_swe_containers(active_manifest_payload)
    if active_exp_id and not processes and not containers:
        warnings.append(
            f"active experiment {active_exp_id} but no live runner processes or SWE "
            "containers; verify live_status.json (stale active state?)"
        )
    qwen_baseline = _extract_baseline(baselines, "qwen")
    glm_baseline = _extract_baseline(baselines, "glm")
    for label, baseline in (("qwen", qwen_baseline), ("glm", glm_baseline)):
        head = baseline.get("source_head")
        if (
            head
            and not str(source.head).startswith(str(head))
            and not str(head).startswith(source.short_head)
        ):
            warnings.append(f"{label} baseline source_head differs from current source HEAD")
    contaminations = load_contaminations(ledger_root)
    for label, baseline in (("qwen", qwen_baseline), ("glm", glm_baseline)):
        contamination_classes: list[str] = []
        artifact = baseline.get("artifact")
        if artifact:
            artifact_class = contamination_class_for(
                ledger_root, str(artifact), contaminations
            )
            if artifact_class:
                contamination_classes.append(artifact_class)
        baseline_exp_id = baseline.get("exp_id")
        if baseline_exp_id:
            contamination_classes.extend(
                run_dir_contamination_classes(ledger_root, str(baseline_exp_id))
            )
        if contamination_classes:
            joined = ", ".join(sorted(set(contamination_classes)))
            warnings.append(
                f"{label} baseline is quarantined ({joined}); "
                "re-baseline on clean runs"
            )
    return {
        "ledger_root": str(ledger_root),
        "source": source.__dict__,
        "handoff": handoff.__dict__,
        "active_experiment": active_exp_id,
        "active_manifest": active_manifest,
        "active_live_status": active_live_status,
        "processes": processes,
        "containers": containers,
        "qwen_baseline": qwen_baseline,
        "glm_baseline": glm_baseline,
        "mechanisms": mechanisms,
        "warnings": [*current.get("warnings", []), *warnings]
        if isinstance(current.get("warnings", []), list)
        else warnings,
        "current": current,
    }


def _extract_baseline(baselines: dict[str, Any], model: str) -> dict[str, Any]:
    value = baselines.get(model, {})
    if isinstance(value, dict) and isinstance(value.get("current_best"), dict):
        return dict(value["current_best"])
    if isinstance(value, dict) and isinstance(value.get("latest_guard"), dict):
        return dict(value["latest_guard"])
    if isinstance(value, dict):
        return value
    return {}


def render_text(status: dict[str, Any]) -> str:
    source = status["source"]
    handoff = status["handoff"]
    lines = [
        f"Ledger: {status['ledger_root']}",
        f"Source: {_dirty_label(source)} {source['short_head']} {source['branch']}",
        f"Handoff: {_dirty_label(handoff)} {handoff['short_head']} {handoff['branch']}",
    ]
    active = status.get("active_experiment")
    if active:
        lines.append(f"Active experiment: {active}")
        if status.get("active_manifest"):
            lines.append(f"Manifest: {status['active_manifest']}")
        live = status.get("active_live_status") or {}
        if live:
            lines.append(f"Live status: {live.get('status', 'unknown')}")
    else:
        lines.append("Active experiment: none")
    lines.append(f"Active runner processes: {len(status['processes'])}")
    lines.append(f"Active SWE containers: {len(status['containers'])}")
    qwen = status.get("qwen_baseline") or {}
    glm = status.get("glm_baseline") or {}
    lines.append(f"Qwen baseline: {format_baseline(qwen)}")
    lines.append(f"GLM baseline: {format_baseline(glm)}")
    rejected = _mechanisms_by_status(
        status.get("mechanisms", {}),
        {"rejected", "rejected_for_qwen"},
    )
    observe = _mechanisms_by_status(status.get("mechanisms", {}), {"observe"})
    if rejected:
        lines.append("Rejected: " + ", ".join(rejected[:8]))
    if observe:
        lines.append("Observe-only: " + ", ".join(observe[:8]))
    warnings = status.get("warnings") or []
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {item}" for item in warnings)
    lines.append("Next: create or run from manifest; do not infer config from chat.")
    return "\n".join(lines)


def _dirty_label(info: dict[str, Any]) -> str:
    if int(info.get("dirty_count") or 0) == 0:
        return "clean"
    return f"dirty {info['dirty_count']}"


def format_baseline(baseline: dict[str, Any]) -> str:
    if not baseline:
        return "not recorded"
    result = baseline.get("result")
    if result:
        return str(result)
    resolved = baseline.get("resolved")
    total = baseline.get("total")
    empty = baseline.get("empty")
    label = baseline.get("label") or baseline.get("exp_id") or "baseline"
    if resolved is not None and total is not None:
        suffix = f" empty={empty}" if empty is not None else ""
        return f"{label} = {resolved}/{total}{suffix}"
    return label


def _mechanisms_by_status(mechanisms: dict[str, Any], statuses: set[str]) -> list[str]:
    result = []
    for name, payload in mechanisms.items():
        if isinstance(payload, dict) and payload.get("status") in statuses:
            result.append(name)
    return sorted(result)


if __name__ == "__main__":
    raise SystemExit(main())
