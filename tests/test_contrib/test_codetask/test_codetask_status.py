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


def test_scaffold_build_app_copies_template_and_writes_status(tmp_path, monkeypatch):
    from opensquilla.contrib.codetask import build_verify

    monkeypatch.setenv("OPENSQUILLA_CODETASK_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(build_verify, "_resolve_cli", lambda name: name)
    monkeypatch.setattr(build_verify, "_build_env", lambda: {})
    phases = []
    commands = []

    def fake_run_step(run_id, phase, cmd, *, cwd, stdout_path, stderr_path, timeout, env):
        phases.append(phase)
        commands.append(cmd)
        if phase == "scaffold_running":
            app = cwd / "app"
            (app / "src").mkdir(parents=True)
            (app / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
            (app / "src" / "main.ts").write_text("export {}\n", encoding="utf-8")
        if phase == "scaffold_lockfile":
            (cwd / "package-lock.json").write_text("{}", encoding="utf-8")
        stdout_path.write_text("ok\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return True, "ok"

    monkeypatch.setattr(runner, "_run_logged_step", fake_run_step)
    repo = tmp_path / "repo"
    repo.mkdir()
    artifact_dir = config.run_dir("run-scaffold")
    artifact_dir.mkdir(parents=True)

    ok, detail = runner._scaffold_build_app("run-scaffold", repo, artifact_dir)

    assert ok is True, detail
    assert phases == ["scaffold_running", "scaffold_lockfile"]
    assert commands[0][-5:] == ["app", "--", "--template", "react-ts", "--skip"]
    assert (repo / "package.json").is_file()
    assert (repo / "src" / "main.ts").is_file()
    assert (repo / "package-lock.json").is_file()
    status = json.loads((artifact_dir / "status.json").read_text())
    assert status["phase"] == "scaffold_complete"


def test_scaffold_build_app_records_failure_status(tmp_path, monkeypatch):
    from opensquilla.contrib.codetask import build_verify

    monkeypatch.setenv("OPENSQUILLA_CODETASK_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(build_verify, "_resolve_cli", lambda name: name)
    monkeypatch.setattr(build_verify, "_build_env", lambda: {})

    def fake_run_step(run_id, phase, cmd, *, cwd, stdout_path, stderr_path, timeout, env):
        stderr_path.write_text("hung\n", encoding="utf-8")
        return False, "scaffold timeout"

    monkeypatch.setattr(runner, "_run_logged_step", fake_run_step)
    repo = tmp_path / "repo"
    repo.mkdir()
    artifact_dir = config.run_dir("run-scaffold-fail")
    artifact_dir.mkdir(parents=True)

    ok, detail = runner._scaffold_build_app("run-scaffold-fail", repo, artifact_dir)

    assert ok is False
    assert detail == "scaffold timeout"
    status = json.loads((artifact_dir / "status.json").read_text())
    assert status["phase"] == "scaffold_failed"
    assert status["error"] == "scaffold timeout"
