#!/usr/bin/env python3
"""Register and query quarantined (contaminated) runs in the experiment ledger.

A contamination class tags artifact batches whose results are confounded by an
infra defect (e.g. a provider-compaction marker leak). Registration is
idempotent: names merge into ``contaminations.json`` at the ledger root,
matching ledger run dirs get a ``contamination.json`` stamp, and an event is
appended to ``experiments.jsonl``. Baseline tooling and ``exp_status`` read the
registry to warn when a quarantined artifact backs a baseline.

Usage:
  exp_quarantine.py register --contamination-class NAME --names-file F \
      --description TEXT [--evidence PATH] [--boundary-commit C ...]
  exp_quarantine.py check ARTIFACT [ARTIFACT ...]
  exp_quarantine.py list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from exp_common import (
    LedgerError,
    append_jsonl,
    artifact_basename,
    atomic_write_json,
    contamination_class_for,
    contaminations_path,
    ledger_lock,
    ledger_root_from_env,
    load_contaminations,
    now_iso,
    read_json,
)

CLASS_NAME_RE_HELP = "lowercase snake_case, e.g. tool_result_compaction_defect"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="register/merge a contamination class")
    register.add_argument(
        "--contamination-class",
        required=True,
        help=f"class name ({CLASS_NAME_RE_HELP})",
    )
    register.add_argument(
        "--names-file",
        required=True,
        type=Path,
        help="JSON file containing a list of artifact batch names",
    )
    register.add_argument("--description", required=True)
    register.add_argument(
        "--evidence",
        default="",
        help="path or URL of the audit/report that established the contamination",
    )
    register.add_argument(
        "--boundary-commit",
        action="append",
        default=[],
        help="fix-boundary commit (repeatable); runs at or before these are affected",
    )

    check = sub.add_parser("check", help="check artifact names/paths against the registry")
    check.add_argument("artifacts", nargs="+")

    sub.add_parser("list", help="summarize registered contamination classes")
    return parser


def _load_names(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read names file {path}: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise LedgerError(f"names file must be a JSON list of strings: {path}")
    # Normalize before filtering: a raw value like "/" or "///" is non-empty
    # pre-normalization but collapses to "" via artifact_basename, and an
    # empty name would substring-match (or exact-match) every run.
    names = sorted(
        {
            normalized
            for item in data
            if item.strip()
            for normalized in [artifact_basename(item)]
            if normalized
        }
    )
    if not names:
        raise LedgerError(f"names file is empty: {path}")
    return names


def _candidate_names_in_payload(payload: Any) -> set[str]:
    """Recursively collect basename-normalized string values from a JSON payload."""
    names: set[str] = set()
    if isinstance(payload, str):
        normalized = artifact_basename(payload)
        if normalized:
            names.add(normalized)
    elif isinstance(payload, dict):
        for value in payload.values():
            names.update(_candidate_names_in_payload(value))
    elif isinstance(payload, list):
        for item in payload:
            names.update(_candidate_names_in_payload(item))
    return names


def _stamp_run_dirs(root: Path, class_name: str, names: list[str]) -> list[str]:
    """Stamp ledger run dirs whose artifacts reference a quarantined batch name.

    Matching is by exact basename, consistent with ``contamination_class_for``.
    A prior substring-based check over the raw JSON text could both false-
    positive (a quarantined name that is a substring of an unrelated, longer
    name) and, worse, treat an empty name as a substring of everything.
    """
    stamped: list[str] = []
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return stamped
    name_set = set(names)
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        matched: set[str] = set()
        for source in ("artifacts.json", "manifest.json"):
            payload = read_json(run_dir / source)
            if not payload:
                continue
            matched.update(name_set & _candidate_names_in_payload(payload))
        if not matched:
            continue
        stamp_path = run_dir / "contamination.json"
        existing = read_json(stamp_path)
        classes = existing.get("classes") if isinstance(existing.get("classes"), dict) else {}
        previous = classes.get(class_name, {})
        previous_names = (
            set(previous.get("matched_artifact_names", []))
            if isinstance(previous, dict)
            else set()
        )
        classes[class_name] = {
            "matched_artifact_names": sorted(previous_names | matched),
            "stamped_at": (
                previous.get("stamped_at")
                if isinstance(previous, dict) and previous.get("stamped_at")
                else now_iso()
            ),
        }
        atomic_write_json(stamp_path, {"classes": classes})
        stamped.append(run_dir.name)
    return stamped


def cmd_register(args: argparse.Namespace) -> int:
    root = ledger_root_from_env()
    class_name = str(args.contamination_class).strip()
    if not class_name:
        raise LedgerError("--contamination-class must be non-empty")
    names = _load_names(args.names_file)
    with ledger_lock(root):
        data = load_contaminations(root)
        classes = data["classes"]
        entry = classes.get(class_name)
        if not isinstance(entry, dict):
            entry = {"registered_at": now_iso()}
        existing_names = set(entry.get("artifact_names", []))
        merged = sorted(existing_names | set(names))
        new_names = sorted(set(names) - existing_names)
        entry.update(
            {
                "description": str(args.description),
                "evidence": str(args.evidence),
                "boundary_commits": sorted({str(c) for c in args.boundary_commit}),
                "artifact_names": merged,
                "updated_at": now_iso(),
            }
        )
        classes[class_name] = entry
        data["updated_at"] = now_iso()
        atomic_write_json(contaminations_path(root), data)
        stamped = _stamp_run_dirs(root, class_name, merged)
        append_jsonl(
            root / "experiments.jsonl",
            {
                "event": "contamination_registered",
                "contamination_class": class_name,
                "artifact_names_total": len(merged),
                "artifact_names_new": len(new_names),
                "stamped_run_dirs": stamped,
                "evidence": str(args.evidence),
                "boundary_commits": sorted({str(c) for c in args.boundary_commit}),
                "time": now_iso(),
            },
        )
    print(
        f"registered {class_name}: {len(merged)} artifact names "
        f"({len(new_names)} new), stamped {len(stamped)} ledger run dirs"
    )
    for run_name in stamped:
        print(f"  stamped: runs/{run_name}/contamination.json")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = ledger_root_from_env()
    contaminations = load_contaminations(root)
    dirty = 0
    for artifact in args.artifacts:
        contamination_class = contamination_class_for(root, artifact, contaminations)
        if contamination_class:
            dirty += 1
            print(f"QUARANTINED\t{artifact_basename(artifact)}\t{contamination_class}")
        else:
            print(f"clean\t{artifact_basename(artifact)}")
    return 1 if dirty else 0


def cmd_list(_: argparse.Namespace) -> int:
    root = ledger_root_from_env()
    classes = load_contaminations(root).get("classes", {})
    if not classes:
        print("no contamination classes registered")
        return 0
    for name, payload in sorted(classes.items()):
        if not isinstance(payload, dict):
            continue
        count = len(payload.get("artifact_names", []))
        boundary = ",".join(payload.get("boundary_commits", [])) or "-"
        print(f"{name}\truns={count}\tboundary={boundary}")
        description = payload.get("description")
        if description:
            print(f"  {description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "register":
            return cmd_register(args)
        if args.command == "check":
            return cmd_check(args)
        return cmd_list(args)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
