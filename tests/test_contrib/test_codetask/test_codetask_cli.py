"""Unit tests for the `opensquilla code-task` CLI subcommand."""

import subprocess
import sys

from typer.testing import CliRunner

from opensquilla.cli.codetask_cmd import codetask_app

runner = CliRunner()


def test_help_runs():
    result = runner.invoke(codetask_app, ["--help"])
    assert result.exit_code == 0
    assert "solve" in result.output


def test_solve_help_lists_inputs():
    result = runner.invoke(codetask_app, ["solve", "--help"])
    assert result.exit_code == 0
    for opt in ("--repo", "--issue", "--task", "--task-file"):
        assert opt in result.output


def test_solve_requires_one_task_input():
    # repo given, but no task input → exit 2.
    result = runner.invoke(codetask_app, ["solve", "--repo", "/tmp/x", "--yes"])
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_solve_requires_repo_unless_scratch():
    result = runner.invoke(codetask_app, ["solve", "--task", "do it", "--yes"])
    assert result.exit_code == 2
    assert "--repo" in result.output


def test_solve_rejects_two_task_inputs():
    result = runner.invoke(
        codetask_app,
        ["solve", "--repo", "/tmp/x", "--issue", "1", "--task", "y", "--yes"],
    )
    assert result.exit_code == 2


def test_solve_rejects_unknown_verification_mode():
    result = runner.invoke(
        codetask_app,
        [
            "solve",
            "--repo",
            "/tmp/x",
            "--task",
            "do it",
            "--verification-mode",
            "unknown",
            "--yes",
        ],
    )
    assert result.exit_code == 2
    assert "Unknown --verification-mode" in result.output


def test_scratch_rejects_repo():
    result = runner.invoke(
        codetask_app,
        [
            "solve",
            "--repo",
            "/tmp/x",
            "--task",
            "do it",
            "--verification-mode",
            "scratch",
            "--yes",
        ],
    )
    assert result.exit_code == 2
    assert "Do not pass --repo" in result.output


def test_scratch_rejects_issue():
    result = runner.invoke(
        codetask_app,
        ["solve", "--issue", "1", "--verification-mode", "scratch", "--yes"],
    )
    assert result.exit_code == 2
    assert "not --issue" in result.output


def test_json_without_yes_is_refused():
    # --json is non-interactive; the trusted-host gate must not be skipped
    # silently (codex review #5). It must require an explicit --yes.
    result = runner.invoke(codetask_app, ["solve", "--repo", "/tmp/x", "--task", "do it", "--json"])
    assert result.exit_code == 2
    assert "--yes" in result.output


def test_json_stdout_is_clean_with_marker_on_stderr(monkeypatch):
    # --json must keep stdout pure JSON; the run-dir startup marker goes to
    # stderr so a consumer reading stdout alone still gets parseable JSON.
    import json as _json

    import opensquilla.contrib.codetask.runner as ct_runner
    from opensquilla.contrib.codetask.types import TaskResult, TaskState

    fake = TaskResult(
        task_slug="x",
        run_id="codetask-task-fake",
        state=TaskState.VERIFIED,
        repo="/tmp/x",
        base_ref="main",
        branch="task/x",
        source="inline",
        artifact_dir="/tmp/x",
    )
    fake.verified = True
    monkeypatch.setattr(ct_runner, "solve", lambda **kw: fake)

    result = runner.invoke(
        codetask_app,
        ["solve", "--repo", "/tmp/x", "--task", "do it", "--json", "--yes"],
    )
    assert result.exit_code == 0, result.output
    # stdout parses as JSON on its own — the marker did not leak into it.
    parsed = _json.loads(result.stdout)
    assert parsed["state"] == "verified"
    assert "[code-task]" not in result.stdout
    # the run-dir announcement is on stderr.
    assert "[code-task] run started" in result.stderr


# ─── (c) Non-TTY stdin must refuse the confirm prompt ─────────────────────
# Field report: agent launches code-task via background_process, which opens
# stdin as a PIPE but never writes to it. When --yes is silently dropped
# (e.g. by cmd.exe quoting on Windows), typer.confirm() blocks on
# click.input() reading from that PIPE forever — observed: 90 minutes of
# silent hang until background_process timeout. The fix: detect non-TTY
# stdin and exit 2 with a clear hint, so the agent sees the failure
# immediately and can recover (or surface it to the user).


def test_non_tty_stdin_refuses_confirm(monkeypatch):
    """No --yes + stdin is not a TTY → exit 2 with a 'stdin is not a terminal'
    hint, NOT a hung confirm prompt. Simulates the background_process /
    cron / CI case."""
    monkeypatch.setattr(
        sys, "stdin", _NonTty()
    )  # isatty() -> False
    result = runner.invoke(
        codetask_app,
        ["solve", "--repo", "/tmp/x", "--task", "do it"],
    )
    assert result.exit_code == 2, result.output
    assert "--yes" in result.output
    assert "stdin is not a terminal" in result.output


def test_non_tty_stdin_with_yes_proceeds(monkeypatch):
    """The non-TTY gate is bypassed when --yes is explicit — same as the
    interactive flow. Sanity-check that the gate isn't over-broad."""
    import opensquilla.contrib.codetask.runner as ct_runner
    from opensquilla.contrib.codetask.types import TaskResult, TaskState

    fake = TaskResult(
        task_slug="x", run_id="codetask-task-fake", state=TaskState.VERIFIED,
        repo="/tmp/x", base_ref="main", branch="task/x", source="inline",
        artifact_dir="/tmp/x",
    )
    fake.verified = True
    monkeypatch.setattr(ct_runner, "solve", lambda **kw: fake)
    monkeypatch.setattr(sys, "stdin", _NonTty())

    result = runner.invoke(
        codetask_app,
        ["solve", "--repo", "/tmp/x", "--task", "do it", "--yes"],
    )
    assert result.exit_code == 0, result.output


def test_stdin_without_isatty_attr_treated_as_non_tty(monkeypatch):
    """Defensive: when sys.stdin is monkey-patched to a stand-in that has
    no isatty attribute at all (StringIO/BytesIO in tests), the gate must
    still treat it as non-TTY rather than crashing with AttributeError."""

    class _NoIsattyAttr:
        pass  # explicitly no isatty method

    monkeypatch.setattr(sys, "stdin", _NoIsattyAttr())
    result = runner.invoke(
        codetask_app,
        ["solve", "--repo", "/tmp/x", "--task", "do it"],
    )
    assert result.exit_code == 2, result.output
    assert "stdin is not a terminal" in result.output


class _NonTty:
    """Minimal stdin stand-in: isatty() -> False, nothing else."""

    def isatty(self) -> bool:
        return False


def test_cli_main_does_not_import_codetask():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "import opensquilla.cli.main\n"
            "assert 'opensquilla.contrib.codetask' not in sys.modules, "
            "'CLI registration must stay lazy'\n",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
