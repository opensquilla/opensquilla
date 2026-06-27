"""From-scratch app build (--verification-mode build, no --repo) scaffolds a
durable workspace repo so a follow-up edit can later --repo at it."""

import subprocess

from opensquilla.contrib.codetask import config, workspace


def test_build_workspace_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_CODETASK_WORKSPACE_DIR", str(tmp_path / "ws"))
    assert config.build_workspace_dir() == tmp_path / "ws"


def test_ensure_build_workspace_creates_durable_git_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_CODETASK_WORKSPACE_DIR", str(tmp_path))
    dest = workspace.ensure_build_workspace("my-app")
    assert dest == tmp_path / "my-app"
    assert (dest / ".git").is_dir()
    # An initial (empty) commit exists so a clone has a base commit to diff from.
    log = subprocess.run(
        ["git", "-C", str(dest), "log", "--oneline"], capture_output=True, text=True
    )
    assert log.returncode == 0 and log.stdout.strip()


def test_ensure_build_workspace_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_CODETASK_WORKSPACE_DIR", str(tmp_path))
    first = workspace.ensure_build_workspace("app")
    second = workspace.ensure_build_workspace("app")
    assert first == second
    assert (first / ".git").is_dir()
