"""Unit tests for the `opensquilla swebench` CLI subcommand."""

import sys

from typer.testing import CliRunner

from opensquilla.cli.swebench_cmd import swebench_app

cli_runner = CliRunner()


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


def test_solve_without_datasets_gives_install_hint(monkeypatch):
    # Simulate the missing optional dependency regardless of the test env.
    monkeypatch.setitem(sys.modules, "datasets", None)
    result = cli_runner.invoke(swebench_app, ["solve", "django__django-16429"])
    assert result.exit_code == 2
    assert "opensquilla[swebench]" in result.output


def test_eval_without_swebench_gives_install_hint(monkeypatch):
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
