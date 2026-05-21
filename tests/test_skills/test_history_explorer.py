"""Tests for the history-explorer bundled skill's scripts/explore.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SKILL_DIR = REPO / "src" / "opensquilla" / "skills" / "bundled" / "history-explorer"
EXPLORE = _SKILL_DIR / "scripts" / "explore.py"


def _make_log_line(skills: list[str], turn_id: str = "t1") -> str:
    from datetime import UTC, datetime
    return json.dumps({
        "turn_id": turn_id, "session_key": "s1", "prompt_hash": "a" * 16,
        "system_prompt_hash": "b" * 16, "tool_list_hash": "c" * 16,
        "tool_choice": "auto", "tokens_input": 1, "tokens_output": 2,
        "model": "x", "provider": "y", "latency_ms": 3,
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "schema_version": 10,
        "skills_invoked": skills,
    })


def _run_explore(log_dir: Path, query: str, **kwargs) -> dict:
    args = [sys.executable, str(EXPLORE), "--log-dir", str(log_dir), "--query", query]
    for k, v in kwargs.items():
        args.extend([f"--{k.replace('_', '-')}", str(v)])
    proc = subprocess.run(args, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def test_co_occurrence_top_k(tmp_path: Path) -> None:
    log = tmp_path / "decisions-20260520.jsonl"
    log.write_text("\n".join([
        _make_log_line(["pdf-toolkit", "summarize", "memory"], "t1"),
        _make_log_line(["pdf-toolkit", "summarize", "memory"], "t2"),
        _make_log_line(["weather", "summarize"], "t3"),
    ]) + "\n", encoding="utf-8")
    out = _run_explore(tmp_path, "process PDFs", window_days=30, top_k=10)
    assert "co_occurrences" in out
    top = out["co_occurrences"][0]
    assert top["skills"] == ["pdf-toolkit", "summarize", "memory"]
    assert top["freq"] == 2


def test_empty_log_returns_placeholder(tmp_path: Path) -> None:
    out = _run_explore(tmp_path, "anything", window_days=30)
    assert out.get("co_occurrences", []) == []
    assert "no history" in out["placeholder"].lower()


def _make_log_line_with_ts(skills: list[str], ts: str, turn_id: str = "t_ts") -> str:
    """Like _make_log_line but with an explicit timestamp string."""
    return json.dumps({
        "turn_id": turn_id, "session_key": "s1", "prompt_hash": "a" * 16,
        "system_prompt_hash": "b" * 16, "tool_list_hash": "c" * 16,
        "tool_choice": "auto", "tokens_input": 1, "tokens_output": 2,
        "model": "x", "provider": "y", "latency_ms": 3,
        "ts": ts, "schema_version": 10,
        "skills_invoked": skills,
    })


def test_window_excludes_old_entries(tmp_path: Path) -> None:
    """An entry older than window_days is not counted."""
    old = tmp_path / "decisions-20240101.jsonl"
    old.write_text(
        _make_log_line_with_ts(["a", "b"], "2024-01-01T00:00:00Z", "old") + "\n",
        encoding="utf-8",
    )
    out = _run_explore(tmp_path, "anything", window_days=30)
    assert out["co_occurrences"] == []


def test_meta_usage_counts_meta_skill_invocations(tmp_path: Path) -> None:
    log = tmp_path / "decisions-20260520.jsonl"
    log.write_text("\n".join([
        _make_log_line(["meta-pdf-intelligence", "pdf-toolkit"], "t1"),
        _make_log_line(["meta-pdf-intelligence"], "t2"),
        _make_log_line(["meta-travel-planner", "weather"], "t3"),
    ]) + "\n", encoding="utf-8")
    out = _run_explore(tmp_path, "anything", window_days=30)
    usage = {row["meta_skill_id"]: row["invocation_count"] for row in out["meta_usage"]}
    assert usage["meta-pdf-intelligence"] == 2
    assert usage["meta-travel-planner"] == 1


def test_router_fixtures_surfaces_fixture_files(tmp_path: Path) -> None:
    """Just verify the keys exist and the script doesn't crash."""
    out = _run_explore(tmp_path, "anything")
    assert isinstance(out["router_fixtures"], list)


def test_meta_usage_filters_by_kind_not_prefix(tmp_path: Path) -> None:
    """N12: aggregate_meta_usage must NOT count kind=skill bundles whose name
    happens to start with 'meta-' (e.g. meta-skill-linter, meta-skill-proposals,
    meta-skill-smoke-test). Only kind=meta skills should appear in the output.

    This test calls aggregate_meta_usage directly (in-process) with an explicit
    meta_names set so the test is hermetic — it does not depend on the live
    bundled catalog, making it fast and fork-safe.
    """
    import importlib.util
    import json as _json
    from datetime import UTC, datetime

    # Import explore.py directly via importlib (it is a script, not a package module).
    spec_obj = importlib.util.spec_from_file_location(
        "explore",
        str(
            Path(__file__).resolve().parents[2]
            / "src" / "opensquilla" / "skills" / "bundled"
            / "history-explorer" / "scripts" / "explore.py"
        ),
    )
    assert spec_obj is not None
    explore_mod = importlib.util.module_from_spec(spec_obj)
    assert spec_obj.loader is not None
    spec_obj.loader.exec_module(explore_mod)  # type: ignore[union-attr]

    log = tmp_path / "decisions-20260520.jsonl"
    now_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _line(skills: list[str], tid: str) -> str:
        return _json.dumps({
            "turn_id": tid, "session_key": "s1",
            "prompt_hash": "a" * 16, "system_prompt_hash": "b" * 16,
            "tool_list_hash": "c" * 16, "tool_choice": "auto",
            "tokens_input": 1, "tokens_output": 2,
            "model": "x", "provider": "y", "latency_ms": 3,
            "ts": now_ts, "schema_version": 10,
            "skills_invoked": skills,
        })

    log.write_text(
        "\n".join([
            _line(["meta-pdf-intelligence"], "t1"),   # kind: meta — count
            _line(["meta-skill-linter"], "t2"),        # kind: skill — do NOT count
            _line(["meta-travel-planner"], "t3"),      # kind: meta — count
            _line(["meta-skill-proposals"], "t4"),     # kind: skill — do NOT count
        ]) + "\n",
        encoding="utf-8",
    )

    # Use explicit meta_names set (the two real kind=meta entries above).
    meta_names: set[str] = {"meta-pdf-intelligence", "meta-travel-planner"}
    rows = explore_mod.aggregate_meta_usage(tmp_path, 30, meta_names)
    usage = {row["meta_skill_id"]: row["invocation_count"] for row in rows}

    assert "meta-pdf-intelligence" in usage, "kind=meta entry must be counted"
    assert "meta-travel-planner" in usage, "kind=meta entry must be counted"
    assert "meta-skill-linter" not in usage, (
        "N12: meta-skill-linter is kind=skill, must not appear in meta_usage"
    )
    assert "meta-skill-proposals" not in usage, (
        "N12: meta-skill-proposals is kind=skill, must not appear in meta_usage"
    )
