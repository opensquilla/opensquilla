"""Run-directory status heartbeat: progress visible WITHOUT the source repo."""

from __future__ import annotations

import json

from opensquilla.contrib.codetask import config, runner


def test_write_status_writes_run_dir_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_CODETASK_RUNS_DIR", str(tmp_path / "runs"))
    runner._write_status("run-x", "agent_running", repo="/tmp/foo")

    status = config.run_dir("run-x") / "status.json"
    assert status.is_file()
    d = json.loads(status.read_text())
    assert d["run_id"] == "run-x"
    assert d["phase"] == "agent_running"
    assert d["repo"] == "/tmp/foo"
    assert "updated" in d


def test_write_status_overwrites_with_latest_phase(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_CODETASK_RUNS_DIR", str(tmp_path / "runs"))
    runner._write_status("run-y", "preparing")
    runner._write_status("run-y", "verifying")

    d = json.loads((config.run_dir("run-y") / "status.json").read_text())
    assert d["phase"] == "verifying"  # latest wins


def test_write_status_never_raises_on_bad_dir(tmp_path, monkeypatch):
    # Point the runs root at a file so mkdir fails — must be swallowed.
    bad = tmp_path / "afile"
    bad.write_text("x")
    monkeypatch.setenv("OPENSQUILLA_CODETASK_RUNS_DIR", str(bad))
    runner._write_status("run-z", "preparing")  # should not raise
