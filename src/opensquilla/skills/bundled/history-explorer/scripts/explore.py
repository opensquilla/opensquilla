#!/usr/bin/env python3
"""History explorer: aggregate DecisionEntry.skills_invoked.

Produces co-occurrence data, meta-skill usage stats, and router fixtures;
emits JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Derive the opensquilla package root from this file's location.
# Path layout from explore.py:
#   .../opensquilla/skills/bundled/history-explorer/scripts/explore.py
# parents: [0]=scripts  [1]=history-explorer  [2]=bundled
#          [3]=skills    [4]=opensquilla
# Works for both source-tree checkouts and wheel installs (site-packages).
_OPENSQUILLA_ROOT = Path(__file__).resolve().parents[4]
_BUNDLED = _OPENSQUILLA_ROOT / "skills" / "bundled"


def _parse_log_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _within_window(ts_str: str, cutoff: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    return ts >= cutoff


def aggregate_co_occurrences(log_dir: Path, window_days: int, top_k: int) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    counter: Counter[tuple[str, ...]] = Counter()
    if not log_dir.is_dir():
        return []
    for log_path in sorted(log_dir.glob("decisions-*.jsonl")):
        for raw in log_path.read_text(encoding="utf-8").splitlines():
            payload = _parse_log_line(raw)
            if not payload:
                continue
            if not _within_window(payload.get("ts", ""), cutoff):
                continue
            skills = payload.get("skills_invoked") or []
            if not isinstance(skills, list) or len(skills) < 2:
                continue
            counter[tuple(skills)] += 1
    return [{"skills": list(combo), "freq": freq} for combo, freq in counter.most_common(top_k)]


def aggregate_meta_usage(
    log_dir: Path,
    window_days: int,
    meta_names: set[str] | None = None,
) -> list[dict]:
    """Count how often each kind=meta skill was invoked.

    Args:
        log_dir: decision-log directory containing decisions-*.jsonl files.
        window_days: time window for inclusion.
        meta_names: set of skill names where kind == "meta". When None,
            falls back to the name-prefix heuristic (skill.startswith("meta-")).
            The heuristic is less accurate because helper bundles like
            meta-skill-linter / meta-skill-proposals / meta-skill-smoke-test
            are kind=skill but share the prefix (N12 fix).
    """
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    counter: Counter[str] = Counter()
    if not log_dir.is_dir():
        return []
    for log_path in sorted(log_dir.glob("decisions-*.jsonl")):
        for raw in log_path.read_text(encoding="utf-8").splitlines():
            payload = _parse_log_line(raw)
            if not payload or not _within_window(payload.get("ts", ""), cutoff):
                continue
            for skill in payload.get("skills_invoked") or []:
                if not isinstance(skill, str):
                    continue
                # Prefer the real catalog set; fall back to prefix heuristic.
                if meta_names is not None:
                    if skill in meta_names:
                        counter[skill] += 1
                elif skill.startswith("meta-"):
                    counter[skill] += 1
    return [{"meta_skill_id": name, "invocation_count": ct} for name, ct in counter.most_common()]


def _load_meta_names() -> set[str]:
    """Load the set of skill names where kind == 'meta' from the bundled catalog.

    Returns an empty set on any failure (wheel install without test fixtures,
    import errors, etc.) so the caller falls back to the prefix heuristic.
    """
    import tempfile

    try:
        # ensure opensquilla is importable (needed when explore.py is run as a
        # subprocess; the parent of _OPENSQUILLA_ROOT is src/ in a source
        # checkout or site-packages/ in a wheel install — both already on path).
        if str(_OPENSQUILLA_ROOT.parent) not in sys.path:
            sys.path.insert(0, str(_OPENSQUILLA_ROOT.parent))
        from opensquilla.skills.loader import SkillLoader

        with tempfile.TemporaryDirectory() as tmp:
            loader = SkillLoader(
                bundled_dir=_BUNDLED,
                snapshot_path=Path(tmp) / "snap.json",
            )
            loader.invalidate_cache()
            return {spec.name for spec in loader.load_all() if spec.kind == "meta"}
    except Exception:
        return set()


def aggregate_router_fixtures(repo_root: Path | None = None) -> list[dict]:
    """Surface the D.2 router-fixture corpus."""
    if repo_root is None:
        # Derive the opensquilla package root from this file's location.
        # Path layout from explore.py:
        #   .../opensquilla/skills/bundled/history-explorer/scripts/explore.py
        # parents: [0]=scripts  [1]=history-explorer  [2]=bundled
        #          [3]=skills    [4]=opensquilla
        # Works for both source-tree checkouts and wheel installs.
        # In a source checkout: opensquilla_root.parent = src/, repo = src/../
        # In a wheel install: test fixtures are absent; the is_dir() guard
        # below returns [] gracefully.
        _opensquilla_root = Path(__file__).resolve().parents[4]
        repo_root = _opensquilla_root.parent.parent
    fixtures_dir = repo_root / "tests" / "test_skills" / "router_fixtures"
    fixtures: list[dict] = []
    if not fixtures_dir.is_dir():
        return fixtures
    for fixture_file in fixtures_dir.glob("*.py"):
        if fixture_file.name.startswith("_"):
            continue
        text = fixture_file.read_text(encoding="utf-8")
        if "expected_choice" not in text:
            continue
        fixtures.append({"fixture_file": fixture_file.name, "note": "see fixture file for details"})
    return fixtures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument("--query", required=True)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--include", default="co_occurrences,meta_usage,router_fixtures")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)

    include = set(args.include.split(","))
    result: dict = {"query": args.query}

    if "co_occurrences" in include:
        result["co_occurrences"] = aggregate_co_occurrences(
            args.log_dir, args.window_days, args.top_k
        )
    if "meta_usage" in include:
        meta_names = _load_meta_names()
        result["meta_usage"] = aggregate_meta_usage(
            args.log_dir, args.window_days, meta_names if meta_names else None
        )
    if "router_fixtures" in include:
        result["router_fixtures"] = aggregate_router_fixtures()

    if not result.get("co_occurrences") and not result.get("meta_usage"):
        result["placeholder"] = "no history available; downstream should rely on user intent only"

    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
