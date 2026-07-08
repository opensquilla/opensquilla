#!/usr/bin/env python3
"""Finalize an OpenSquilla experiment from handoff artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from exp_common import (
    LedgerError,
    append_jsonl,
    atomic_write_json,
    atomic_write_text,
    collect_eval_metrics,
    contamination_class_for,
    exp_dir,
    ledger_lock,
    ledger_root_from_env,
    now_iso,
    parse_key_value_file,
    read_first_existing_report,
    read_json,
    read_json_strict,
    run_dir_contamination_classes,
    sha256_file,
    validate_exp_id,
)

DECISIONS = {"adopted", "rejected", "observe", "inconclusive", "invalid", "stopped"}
NO_VALID_EVAL_DECISIONS = {"invalid", "stopped"}
AGENT_ENV_DELIVERY_VARS = frozenset(
    {
        "OPENSQUILLA_DASHSCOPE_THINKING_BUDGET",
        "OPENSQUILLA_FINAL_DIFF_CONTRACT_MODE",
        "OPENSQUILLA_FINALIZE_EVIDENCE_GATE",
        "OPENSQUILLA_PATCH_EVIDENCE_PROTOCOL",
        "OPENSQUILLA_PROVIDER_COMPACTION_TINY_GUARD_CHARS",
        "OPENSQUILLA_PROVIDER_COMPACTION_PROTECT_RECENT_ASSISTANT",
        "OPENSQUILLA_PROVIDER_CONTEXT_BLOCK_FEEDBACK",
        "OPENSQUILLA_IDENTICAL_REQUEST_LOOP_BREAK",
        "OPENSQUILLA_PLACEHOLDER_ESCALATION_THRESHOLD",
        "OPENSQUILLA_DEADLINE_WRAPUP_MARGIN_SECONDS",
        "OPENSQUILLA_TOOL_REPEAT_NUDGE_THRESHOLD",
        "OPENSQUILLA_TOOL_REPEAT_NUDGE_TOOLS",
        "OPENSQUILLA_PROVIDER_HISTORY_DEDUP",
        "OPENSQUILLA_PROVIDER_HISTORY_DEDUP_MIN_REPEATS",
    }
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp-id", required=True)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--decision", required=True, choices=sorted(DECISIONS))
    parser.add_argument("--decision-reason", required=True)
    parser.add_argument("--mechanism", default="")
    parser.add_argument("--baseline-model", choices=["qwen", "glm"], default="")
    parser.add_argument("--overwrite-decision", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        finalize(args)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def finalize(args: argparse.Namespace) -> None:
    exp_id = validate_exp_id(args.exp_id)
    ledger_root = ledger_root_from_env()
    run_dir = exp_dir(ledger_root, exp_id)
    manifest = read_json_strict(run_dir / "manifest.json", label="experiment manifest")
    if (run_dir / "decision.md").exists() and not args.overwrite_decision:
        raise LedgerError("decision already exists; pass --overwrite-decision to replace")
    if not args.batch_dir.is_dir():
        raise LedgerError(f"batch dir does not exist: {args.batch_dir}")

    artifacts = collect_artifacts(args.batch_dir)
    validate_batch_matches_manifest(manifest, artifacts)
    artifacts["env_delivery"] = collect_env_delivery(manifest, artifacts)
    metrics = collect_metrics(artifacts)
    eval_valid = (
        metrics["eval_report_count"] > 0
        and not metrics["nonzero_eval_exit_codes"]
        and not metrics["nonzero_infer_exit_codes"]
        and not metrics["nonzero_other_exit_codes"]
    )
    if not eval_valid and args.decision not in NO_VALID_EVAL_DECISIONS:
        raise LedgerError(
            "missing/nonzero infer or eval results can only be finalized as invalid or stopped"
        )
    env_delivery_errors = artifacts.get("env_delivery", {}).get("errors", [])
    if env_delivery_errors and args.decision not in NO_VALID_EVAL_DECISIONS:
        raise LedgerError(
            "manifest-pinned runtime env was not delivered to agent instances: "
            + "; ".join(str(error) for error in env_delivery_errors)
        )
    if args.decision == "adopted" and args.baseline_model:
        contamination_classes = _batch_contamination_classes(ledger_root, exp_id, artifacts)
        if contamination_classes:
            raise LedgerError(
                "cannot adopt as baseline: batch is quarantined ("
                + ", ".join(contamination_classes)
                + "); re-baseline on clean runs"
            )

    finished_at = now_iso()
    decision_payload = {
        "exp_id": exp_id,
        "decision": args.decision,
        "reason": args.decision_reason,
        "mechanism": args.mechanism,
        "baseline_model": args.baseline_model,
        "decided_at": finished_at,
    }
    with ledger_lock(ledger_root):
        atomic_write_json(run_dir / "artifacts.json", artifacts)
        atomic_write_json(run_dir / "metrics.json", metrics)
        atomic_write_text(run_dir / "analysis.md", render_analysis(manifest, artifacts, metrics))
        atomic_write_text(run_dir / "decision.md", render_decision(decision_payload, metrics))
        update_current(ledger_root, exp_id, args.decision, metrics, finished_at)
        if args.decision == "adopted" and args.baseline_model:
            update_baseline(
                ledger_root,
                args.baseline_model,
                exp_id,
                manifest,
                metrics,
                args.decision_reason,
            )
        if args.mechanism:
            update_mechanism(
                ledger_root,
                args.mechanism,
                args.decision,
                exp_id,
                args.decision_reason,
            )
        append_jsonl(
            ledger_root / "experiments.jsonl",
            {
                "time": finished_at,
                "exp_id": exp_id,
                "event": "finalized",
                "decision": args.decision,
                "resolved": metrics["resolved_instances"],
                "total": metrics["total_instances"],
                "empty": metrics["empty_patch_instances"],
                "batch_dir": str(args.batch_dir),
            },
        )
    print(json.dumps({"exp_id": exp_id, "decision": args.decision, "metrics": metrics}, indent=2))


def _batch_contamination_classes(
    ledger_root: Path, exp_id: str, artifacts: dict[str, Any]
) -> list[str]:
    """Return contamination classes covering this batch, by name or by stamped run dir."""
    classes = set(run_dir_contamination_classes(ledger_root, exp_id))
    batch_dir = str(artifacts.get("batch_dir") or "").strip()
    if batch_dir:
        batch_class = contamination_class_for(ledger_root, batch_dir)
        if batch_class:
            classes.add(batch_class)
    return sorted(classes)


def collect_artifacts(batch_dir: Path) -> dict[str, Any]:
    manifest_txt = batch_dir / "manifest.txt"
    batch_manifest = parse_key_value_file(manifest_txt)
    report_paths: list[str] = []
    for path_file in sorted(batch_dir.glob("*-eval.report_paths.txt")):
        report_paths.extend(read_first_existing_report(path_file))
    exit_codes = {}
    for exit_file in sorted(batch_dir.glob("*.exit_code")):
        text = exit_file.read_text(encoding="utf-8", errors="replace").strip()
        try:
            value: int | str = int(text)
        except ValueError:
            value = text
        exit_codes[exit_file.name] = value
    return {
        "batch_dir": str(batch_dir),
        "batch_manifest_path": str(manifest_txt) if manifest_txt.exists() else "",
        "batch_manifest": batch_manifest,
        "eval_report_paths": sorted(set(report_paths)),
        "exit_codes": exit_codes,
        "supervisor_log": str(batch_dir / "supervisor.log")
        if (batch_dir / "supervisor.log").exists()
        else "",
    }


def collect_env_delivery(
    manifest: dict[str, Any],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    expected = _manifest_agent_env_expectations(manifest)
    delivery: dict[str, Any] = {
        "expected": expected,
        "checked_instance_count": 0,
        "run_dirs": [],
        "per_var": {
            name: {
                "expected": value,
                "matched": 0,
                "missing": 0,
                "mismatch": 0,
            }
            for name, value in expected.items()
        },
        "errors": [],
    }
    if not expected:
        return delivery

    run_dirs = _agent_run_dirs(artifacts)
    delivery["run_dirs"] = [str(path) for path in run_dirs]
    if not run_dirs:
        delivery["errors"].append(
            "no agent run dirs resolved from batch manifest; env delivery could not be "
            "verified for expected vars: " + ", ".join(sorted(expected))
        )
        return delivery

    metadata_paths: list[Path] = []
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            delivery["errors"].append(f"run artifact dir not found: {run_dir}")
            continue
        metadata_paths.extend(sorted(run_dir.glob("*/metadata.json")))
    if not metadata_paths:
        delivery["errors"].append("no instance metadata found for env delivery check")
        return delivery

    for metadata_path in metadata_paths:
        delivery["checked_instance_count"] += 1
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            delivery["errors"].append(f"metadata is not valid JSON: {metadata_path}")
            continue
        forwarded_env = (
            ((payload.get("agent") or {}).get("controls") or {}).get(
                "progress_watchdog_env"
            )
            or {}
        )
        if not isinstance(forwarded_env, dict):
            delivery["errors"].append(
                f"progress_watchdog_env is not an object: {metadata_path}"
            )
            forwarded_env = {}
        for name, expected_value in expected.items():
            stats = delivery["per_var"][name]
            if name not in forwarded_env:
                stats["missing"] += 1
            elif str(forwarded_env.get(name)) != expected_value:
                stats["mismatch"] += 1
            else:
                stats["matched"] += 1

    for name, stats in delivery["per_var"].items():
        missing = int(stats["missing"])
        mismatch = int(stats["mismatch"])
        if missing or mismatch:
            delivery["errors"].append(
                f"{name} expected {stats['expected']!r}: "
                f"{missing} missing, {mismatch} mismatched across "
                f"{delivery['checked_instance_count']} metadata files"
            )
    return delivery


def _manifest_agent_env_expectations(manifest: dict[str, Any]) -> dict[str, str]:
    env = manifest.get("config", {}).get("env", {})
    if not isinstance(env, dict):
        return {}
    expected: dict[str, str] = {}
    for name, payload in env.items():
        if name not in AGENT_ENV_DELIVERY_VARS:
            continue
        if not isinstance(payload, dict) or payload.get("redacted"):
            continue
        value = payload.get("value")
        if value is not None:
            expected[name] = str(value)
    return expected


def _agent_run_dirs(artifacts: dict[str, Any]) -> list[Path]:
    batch_dir_text = str(artifacts.get("batch_dir") or "").strip()
    if not batch_dir_text:
        return []
    batch_dir = Path(batch_dir_text)
    batch_manifest = artifacts.get("batch_manifest") or {}
    run_mode = str(batch_manifest.get("run_mode") or "")
    keys: list[tuple[str, str]] = []
    if run_mode != "glm_only":
        keys.extend(
            [
                ("qwen_ml_run_id", "ml_ids"),
                ("qwen_verified_run_id", "verified_ids"),
            ]
        )
    if run_mode != "qwen_only":
        keys.extend(
            [
                ("glm_ml_run_id", "ml_ids"),
                ("glm_verified_run_id", "verified_ids"),
            ]
        )
    roots: list[Path] = []
    for key, ids_key in keys:
        if not str(batch_manifest.get(ids_key) or "").strip():
            continue
        run_id = str(batch_manifest.get(key) or "")
        if run_id:
            roots.append(batch_dir.parent / run_id)
    return roots


def validate_batch_matches_manifest(manifest: dict[str, Any], artifacts: dict[str, Any]) -> None:
    batch_manifest = artifacts.get("batch_manifest", {})
    if not batch_manifest:
        raise LedgerError("batch manifest.txt is missing or empty")

    errors: list[str] = []
    _expect_equal(
        errors,
        "opensquilla_source_head",
        batch_manifest.get("opensquilla_source_head"),
        manifest.get("source", {}).get("head"),
    )
    _expect_equal(
        errors,
        "handoff_head",
        batch_manifest.get("handoff_head"),
        manifest.get("handoff", {}).get("head"),
    )
    _expect_equal(
        errors,
        "condition_label",
        batch_manifest.get("condition_label"),
        manifest.get("config", {}).get("condition_label"),
    )
    _expect_equal(
        errors,
        "run_mode",
        batch_manifest.get("run_mode"),
        manifest.get("execution", {}).get("run_mode"),
    )
    for key in ("qwen_workers", "glm_workers", "eval_workers"):
        _expect_equal(
            errors,
            key,
            batch_manifest.get(key),
            str(manifest.get("execution", {}).get(key, "")),
        )

    run_mode = str(manifest.get("execution", {}).get("run_mode", ""))
    if run_mode != "glm_only":
        _expect_equal(
            errors,
            "qwen_config_sha256",
            batch_manifest.get("qwen_config_sha256"),
            manifest.get("config", {}).get("qwen_config", {}).get("sha256"),
        )
    if run_mode != "qwen_only":
        _expect_equal(
            errors,
            "glm_config_sha256",
            batch_manifest.get("glm_config_sha256"),
            manifest.get("config", {}).get("glm_config", {}).get("sha256"),
        )

    _expect_one_of(
        errors,
        "ml_instance_file",
        batch_manifest.get("ml_instance_file"),
        _path_candidates(manifest.get("slice", {}).get("ml", {})),
    )
    _expect_one_of(
        errors,
        "verified_instance_file",
        batch_manifest.get("verified_instance_file"),
        _path_candidates(manifest.get("slice", {}).get("verified", {})),
    )

    _verify_slice_content(
        errors,
        "ml_instance_file",
        batch_manifest.get("ml_instance_file"),
        manifest.get("slice", {}).get("ml", {}),
    )
    _verify_slice_content(
        errors,
        "verified_instance_file",
        batch_manifest.get("verified_instance_file"),
        manifest.get("slice", {}).get("verified", {}),
    )
    _verify_batch_selected_id_count(
        errors,
        "ml_ids",
        batch_manifest.get("ml_ids"),
        manifest.get("slice", {}).get("ml", {}),
    )
    _verify_batch_selected_id_count(
        errors,
        "verified_ids",
        batch_manifest.get("verified_ids"),
        manifest.get("slice", {}).get("verified", {}),
    )

    _verify_runner_sha(errors, batch_manifest, manifest)

    if errors:
        raise LedgerError("batch does not match experiment manifest: " + "; ".join(errors))


def _expect_equal(errors: list[str], label: str, actual: str | None, expected: Any) -> None:
    expected_text = "" if expected is None else str(expected)
    actual_text = "" if actual is None else str(actual)
    if not actual_text:
        errors.append(f"{label} missing")
    elif actual_text != expected_text:
        errors.append(f"{label}={actual_text!r} expected {expected_text!r}")


def _expect_one_of(
    errors: list[str],
    label: str,
    actual: str | None,
    expected_values: set[str],
) -> None:
    actual_text = "" if actual is None else str(actual)
    if not actual_text:
        errors.append(f"{label} missing")
    elif actual_text not in expected_values:
        expected = ", ".join(sorted(expected_values))
        errors.append(f"{label}={actual_text!r} expected one of [{expected}]")


def _path_candidates(payload: dict[str, Any]) -> set[str]:
    return {str(payload.get(key)) for key in ("source", "snapshot") if payload.get(key)}


def _verify_slice_content(
    errors: list[str],
    label: str,
    actual_path: str | None,
    slice_payload: dict[str, Any],
) -> None:
    """Confirm the batch's instance file matches the manifest by content, not just path.

    The batch manifest.txt records only the instance-file path; a path match alone does
    not prove the file's contents (or slice size) are the ones the manifest pinned.
    """
    path_text = "" if actual_path is None else str(actual_path)
    if not path_text:
        return  # missing path already reported by _expect_one_of
    path = Path(path_text)
    if not path.is_file():
        errors.append(f"{label} not readable for content check: {path}")
        return
    expected_sha = str(slice_payload.get("sha256") or "")
    if expected_sha and sha256_file(path) != expected_sha:
        errors.append(f"{label} sha256 changed since manifest creation")
    expected_count = slice_payload.get("count")
    if isinstance(expected_count, int):
        if expected_count == 0:
            return
        actual_count = _count_instances(path)
        if actual_count != expected_count:
            errors.append(
                f"{label} instance count {actual_count} != manifest {expected_count}"
            )


def _count_instances(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line.strip())


def _verify_batch_selected_id_count(
    errors: list[str],
    label: str,
    actual_ids: str | None,
    slice_payload: dict[str, Any],
) -> None:
    expected_count = slice_payload.get("count")
    if not isinstance(expected_count, int):
        return
    actual = 0 if actual_ids is None else len(str(actual_ids).split())
    if actual != expected_count:
        errors.append(f"{label} selected count {actual} != manifest {expected_count}")


def _verify_runner_sha(
    errors: list[str],
    batch_manifest: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    """Opportunistically confirm the batch was produced by the manifest-pinned runner.

    The handoff runner does not emit a runner sha into manifest.txt today, so this is a
    no-op unless a ``runner_sha256``/``handoff_runner_sha256`` field is present. Runner
    integrity at launch time is enforced separately in exp_run.py.
    """
    expected = str(manifest.get("config", {}).get("runner", {}).get("sha256") or "")
    if not expected:
        return
    actual = (
        batch_manifest.get("runner_sha256")
        or batch_manifest.get("handoff_runner_sha256")
        or ""
    )
    actual_text = str(actual)
    if actual_text and actual_text != expected:
        errors.append("runner_sha256 does not match manifest runner")


def collect_metrics(artifacts: dict[str, Any]) -> dict[str, Any]:
    eval_metrics = collect_eval_metrics(artifacts.get("eval_report_paths", []))
    exit_codes = artifacts.get("exit_codes", {})
    nonzero = {name: value for name, value in exit_codes.items() if value != 0}
    nonzero_eval = {
        name: value for name, value in nonzero.items() if name.endswith("-eval.exit_code")
    }
    nonzero_infer = {
        name: value for name, value in nonzero.items() if name.endswith(".infer.exit_code")
    }
    # Any other nonzero exit file (nonstandard/unexpected name) must still gate validity;
    # silently ignoring it could let a broken run be finalized as adopted/rejected.
    nonzero_other = {
        name: value
        for name, value in nonzero.items()
        if name not in nonzero_eval and name not in nonzero_infer
    }
    total = int(eval_metrics.get("total_instances") or 0)
    resolved = int(eval_metrics.get("resolved_instances") or 0)
    empty = int(eval_metrics.get("empty_patch_instances") or 0)
    return {
        **eval_metrics,
        "eval_report_count": int(eval_metrics.get("report_count") or 0),
        "env_delivery_error_count": len(
            artifacts.get("env_delivery", {}).get("errors", [])
        ),
        "resolved_rate": (resolved / total) if total else None,
        "empty_rate": (empty / total) if total else None,
        "nonzero_eval_exit_codes": nonzero_eval,
        "nonzero_infer_exit_codes": nonzero_infer,
        "nonzero_other_exit_codes": nonzero_other,
    }


def render_analysis(
    manifest: dict[str, Any],
    artifacts: dict[str, Any],
    metrics: dict[str, Any],
) -> str:
    resolved = f"{metrics.get('resolved_instances', 0)}/{metrics.get('total_instances', 0)}"
    env_delivery = artifacts.get("env_delivery") or {}
    env_lines: list[str] = []
    if env_delivery.get("expected"):
        env_lines = [
            "- Runtime env delivery checked: "
            f"{env_delivery.get('checked_instance_count', 0)} metadata files",
            f"- Runtime env delivery errors: {len(env_delivery.get('errors', []))}",
        ]
        for error in env_delivery.get("errors", []):
            env_lines.append(f"  - {error}")
    return "\n".join(
        [
            f"# SWE Experiment Analysis: {manifest.get('exp_id')}",
            "",
            f"- Question: {manifest.get('question', '')}",
            f"- Batch: `{artifacts.get('batch_dir', '')}`",
            f"- Source HEAD: `{manifest.get('source', {}).get('head', '')}`",
            f"- Handoff HEAD: `{manifest.get('handoff', {}).get('head', '')}`",
            f"- Eval reports: {metrics.get('eval_report_count', 0)}",
            f"- Resolved: {resolved}",
            f"- Empty patches: {metrics.get('empty_patch_instances', 0)}",
            f"- Errors: {metrics.get('error_instances', 0)}",
            *env_lines,
            "",
            "This report is generated from the manifest and batch artifacts; "
            "raw traces remain in place.",
            "",
        ]
    )


def render_decision(decision: dict[str, Any], metrics: dict[str, Any]) -> str:
    resolved = f"{metrics.get('resolved_instances', 0)}/{metrics.get('total_instances', 0)}"
    return "\n".join(
        [
            f"# Decision: {decision['decision']}",
            "",
            f"- Experiment: `{decision['exp_id']}`",
            f"- Reason: {decision['reason']}",
            f"- Resolved: {resolved}",
            f"- Empty patches: {metrics.get('empty_patch_instances', 0)}",
            f"- Decided at: {decision['decided_at']}",
            "",
        ]
    )


def update_current(
    ledger_root: Path,
    exp_id: str,
    decision: str,
    metrics: dict[str, Any],
    updated_at: str,
) -> None:
    current = read_json(ledger_root / "current.json")
    if current.get("active_experiment") == exp_id:
        current["active_experiment"] = None
    current.update(
        {
            "updated_at": updated_at,
            "last_experiment": exp_id,
            "last_decision": decision,
            "last_result": {
                "resolved": metrics.get("resolved_instances", 0),
                "total": metrics.get("total_instances", 0),
                "empty": metrics.get("empty_patch_instances", 0),
            },
        }
    )
    atomic_write_json(ledger_root / "current.json", current)


def update_baseline(
    ledger_root: Path,
    model: str,
    exp_id: str,
    manifest: dict[str, Any],
    metrics: dict[str, Any],
    reason: str,
) -> None:
    baselines = read_json(ledger_root / "baselines.json")
    baselines[model] = {
        "current_best": {
            "exp_id": exp_id,
            "label": manifest.get("config", {}).get("condition_label", exp_id),
            "source_head": manifest.get("source", {}).get("head", ""),
            "resolved": metrics.get("resolved_instances", 0),
            "total": metrics.get("total_instances", 0),
            "empty": metrics.get("empty_patch_instances", 0),
            "reason": reason,
        }
    }
    atomic_write_json(ledger_root / "baselines.json", baselines)


def update_mechanism(
    ledger_root: Path,
    mechanism: str,
    decision: str,
    exp_id: str,
    reason: str,
) -> None:
    mechanisms = read_json(ledger_root / "mechanisms.json")
    mechanisms[mechanism] = {
        "status": decision,
        "exp_id": exp_id,
        "reason": reason,
        "updated_at": now_iso(),
    }
    atomic_write_json(ledger_root / "mechanisms.json", mechanisms)


if __name__ == "__main__":
    raise SystemExit(main())
