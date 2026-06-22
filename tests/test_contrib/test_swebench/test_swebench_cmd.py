"""Unit tests for the `opensquilla swebench` CLI subcommand."""

import shutil
import sys

import pytest
from typer.testing import CliRunner

from opensquilla.cli.swebench_cmd import swebench_app

cli_runner = CliRunner()


@pytest.fixture
def docker_present(monkeypatch):
    """Stub `docker` as installed AND its daemon as reachable, so the preflight
    does not mask the assertion.

    The docker preflight runs first in solve/eval/pull and now checks both that
    the CLI is on PATH and that `docker info` succeeds; without stubbing both,
    the optional-dependency tests below would assert the docker hint on a
    Dockerless machine (codex review).
    """
    import subprocess

    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else real_which(name)
    )
    real_run = subprocess.run

    def fake_run(argv, *a, **k):
        if argv[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(argv, 0, "Server: ok", "")
        return real_run(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_missing_docker_guides_install_not_dead_end(monkeypatch):
    # When docker is absent, solve must tell the user how to install it (and
    # point at code-task), not fail cryptically or silently.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = cli_runner.invoke(swebench_app, ["solve", "django__django-16429"])
    assert result.exit_code == 2
    out = result.output.lower()
    assert "docker" in out
    assert "install" in out or "get-docker" in out or "get.docker" in out
    assert "code-task" in result.output


def test_docker_installed_but_daemon_down_guides_start(monkeypatch):
    # Docker CLI present but daemon unreachable (`docker info` fails) — the
    # preflight must say to START Docker, not pass and fail cryptically later.
    import subprocess

    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None
    )

    def fake_run(argv, *a, **k):
        if argv[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to the Docker daemon")
        raise AssertionError(f"unexpected run: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = cli_runner.invoke(swebench_app, ["solve", "django__django-16429"])
    assert result.exit_code == 2
    out = result.output.lower()
    assert "daemon" in out and "start docker" in out


def test_help_runs_without_optional_deps():
    result = cli_runner.invoke(swebench_app, ["--help"])
    assert result.exit_code == 0
    assert "solve" in result.output
    assert "eval" in result.output
    assert "pull" in result.output


def test_solve_help():
    result = cli_runner.invoke(swebench_app, ["solve", "--help"])
    assert result.exit_code == 0
    assert "--dataset" in result.output


def test_solve_without_datasets_gives_install_hint(monkeypatch, docker_present):
    # Simulate the missing optional dependency regardless of the test env.
    monkeypatch.setitem(sys.modules, "datasets", None)
    result = cli_runner.invoke(swebench_app, ["solve", "django__django-16429"])
    assert result.exit_code == 2
    assert "opensquilla[swebench]" in result.output


def test_eval_without_swebench_gives_install_hint(monkeypatch, docker_present):
    monkeypatch.setitem(sys.modules, "swebench", None)
    result = cli_runner.invoke(swebench_app, ["eval", "preds.jsonl"])
    assert result.exit_code == 2
    assert "opensquilla[swebench]" in result.output


def test_cli_main_does_not_import_harness():
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "import opensquilla.cli.main\n"
            "assert 'opensquilla.contrib.swebench' not in sys.modules, "
            "'CLI registration must stay lazy'\n",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
