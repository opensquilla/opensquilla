#!/usr/bin/env python3
"""Evaluate deterministic meta-skill trigger matching from JSON fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.trigger_accuracy import TriggerCase, evaluate_trigger_cases


def load_cases(path: Path) -> list[TriggerCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("fixture file must contain a JSON array")
    cases: list[TriggerCase] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"fixture[{index}] must be an object")
        name = item.get("name")
        user_message = item.get("user_message")
        expected = item.get("expected_meta_skill")
        if not isinstance(name, str) or not name:
            raise ValueError(f"fixture[{index}].name must be a non-empty string")
        if not isinstance(user_message, str):
            raise ValueError(f"fixture[{index}].user_message must be a string")
        if expected is not None and not isinstance(expected, str):
            raise ValueError(
                f"fixture[{index}].expected_meta_skill must be string or null",
            )
        cases.append(TriggerCase(
            name=name,
            user_message=user_message,
            expected_meta_skill=expected,
        ))
    return cases


def _default_bundled_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "opensquilla" / "skills" / "bundled"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("--bundled-dir", type=Path, default=_default_bundled_dir())
    p.add_argument("--managed-dir", type=Path, default=None)
    p.add_argument("--workspace-dir", type=Path, default=None)
    p.add_argument("--snapshot", type=Path, default=None)
    p.add_argument("--fail-under", type=float, default=1.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = load_cases(args.fixtures)
    loader = SkillLoader(
        bundled_dir=args.bundled_dir,
        managed_dir=args.managed_dir,
        workspace_dir=args.workspace_dir,
        snapshot_path=args.snapshot,
    )
    loader.invalidate_cache()
    report = evaluate_trigger_cases(loader, cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if float(report["accuracy"]) >= args.fail_under else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
