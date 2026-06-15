"""Unit tests for opensquilla.contrib.codetask.verification."""

import json

from opensquilla.contrib.codetask import verification
from opensquilla.contrib.codetask.config import VERIFICATION_MANIFEST_NAME
from opensquilla.contrib.codetask.types import (
    AcceptanceCheck,
    RegressionResult,
    TaskState,
)


class TestManifestLoading:
    def test_missing_manifest(self, tmp_path):
        assert verification.load_manifest(tmp_path) is None

    def test_malformed_manifest(self, tmp_path):
        (tmp_path / VERIFICATION_MANIFEST_NAME).write_text("not json{")
        assert verification.load_manifest(tmp_path) is None

    def test_valid_manifest(self, tmp_path):
        (tmp_path / VERIFICATION_MANIFEST_NAME).write_text(json.dumps({"testable": True}))
        assert verification.load_manifest(tmp_path) == {"testable": True}


class TestStateDecision:
    def _green(self, before):
        return AcceptanceCheck(name="t", command="c", before=before, after="pass")

    def test_red_then_green_is_verified(self):
        state, _ = verification._decide_state([self._green("fail")], None, None)
        assert state == TaskState.VERIFIED

    def test_green_on_base_is_already_satisfied(self):
        state, _ = verification._decide_state([self._green("pass")], None, None)
        assert state == TaskState.ALREADY_SATISFIED

    def test_after_fail_is_failed(self):
        check = AcceptanceCheck(name="t", command="c", before="fail", after="fail")
        state, _ = verification._decide_state([check], None, None)
        assert state == TaskState.FAILED

    def test_regression_new_failures_is_failed(self):
        reg = RegressionResult(command="pytest", ran=True, new_failures=2)
        state, _ = verification._decide_state([self._green("fail")], reg, None)
        assert state == TaskState.FAILED

    def test_regression_clean_keeps_verified(self):
        reg = RegressionResult(command="pytest", ran=True, new_failures=0)
        state, _ = verification._decide_state([self._green("fail")], reg, None)
        assert state == TaskState.VERIFIED

    def test_unprovable_red_is_not_verified(self):
        # Green but red never established (no test_paths) must FAIL CLOSED,
        # never claim VERIFIED (codex review #2).
        state, detail = verification._decide_state([self._green(None)], None, "missing_test_paths")
        assert state == TaskState.INVALID_ACCEPTANCE_TEST
        assert "red state could not be proven" in detail

    def test_worktree_failure_is_environment_blocked(self):
        state, _ = verification._decide_state([self._green(None)], None, "worktree_failed")
        assert state == TaskState.ENVIRONMENT_BLOCKED


class TestParseHelpers:
    def test_parse_pytest_failures(self):
        assert verification._parse_failures("3 passed, 2 failed", 1) == 2

    def test_parse_failures_returncode_zero(self):
        assert verification._parse_failures("all good", 0) == 0

    def test_parse_failures_unparseable_nonzero(self):
        assert verification._parse_failures("boom", 1) is None

    def test_parse_passes(self):
        assert verification._parse_passes("10 passed, 0 failed") == 10

    def test_failing_names_set(self):
        out = "FAILED tests/test_a.py::test_x - boom\nFAILED tests/test_b.py::test_y"
        names = verification._failing_names(out)
        assert names == {"tests/test_a.py::test_x", "tests/test_b.py::test_y"}

    def test_failing_names_none_when_absent(self):
        assert verification._failing_names("3 passed") is None


class TestPathSafety:
    def test_rejects_absolute_and_parent_escape(self):
        safe = verification._safe_rel_paths(
            ["tests/ok.py", "/etc/passwd", "../../secret", "a/../b", ""]
        )
        assert safe == ["tests/ok.py"]


class TestRegressionFailClosed:
    def test_unparseable_nonzero_is_treated_as_regressed(self, monkeypatch):
        # npm/go-style failure with no parseable count must NOT report clean
        # (codex review #3).
        def fake_shell(command, *, cwd, timeout):
            return 1, "npm ERR! test failed"

        monkeypatch.setattr(verification, "_run_shell", fake_shell)
        # Force the base worktree to be unavailable so only the head run counts.
        monkeypatch.setattr(
            verification,
            "_BaseWorktree",
            _raise_worktree,
        )
        from pathlib import Path

        reg = verification._run_regression(
            "npm test", repo=Path("/x"), base_commit="abc", timeout=10
        )
        assert reg is not None
        assert reg.new_failures == 1

    def test_named_diff_does_not_mask_new_failure(self, monkeypatch):
        # base fails test_old; head fails test_new. Counts both = 1, but the
        # NEW failure must still be detected (codex review #4).
        calls = {"n": 0}

        def fake_shell(command, *, cwd, timeout):
            calls["n"] += 1
            if calls["n"] == 1:  # head
                return 1, "FAILED tests/t.py::test_new\n1 failed"
            return 1, "FAILED tests/t.py::test_old\n1 failed"  # base

        monkeypatch.setattr(verification, "_run_shell", fake_shell)

        class _OkWorktree:
            def __init__(self, *a):
                pass

            def __enter__(self):
                from pathlib import Path

                return Path("/base")

            def __exit__(self, *a):
                return None

        monkeypatch.setattr(verification, "_BaseWorktree", _OkWorktree)
        from pathlib import Path

        reg = verification._run_regression("pytest", repo=Path("/x"), base_commit="abc", timeout=10)
        assert reg.new_failures == 1


def _raise_worktree(*a):
    class _W:
        def __enter__(self):
            raise verification._WorktreeError("unavailable")

        def __exit__(self, *a):
            return None

    return _W()


class TestVerifyEndToEnd:
    def test_no_manifest_is_invalid(self, tmp_path):
        out = verification.verify(repo=tmp_path, base_commit="x", scratch_dir=tmp_path)
        assert out.state == TaskState.INVALID_ACCEPTANCE_TEST

    def test_not_testable(self, tmp_path):
        (tmp_path / VERIFICATION_MANIFEST_NAME).write_text(
            json.dumps({"testable": False, "not_testable_reason": "docs only"})
        )
        out = verification.verify(repo=tmp_path, base_commit="x", scratch_dir=tmp_path)
        assert out.state == TaskState.NOT_TESTABLE
        assert "docs only" in out.detail

    def test_testable_but_no_tests_is_invalid(self, tmp_path):
        (tmp_path / VERIFICATION_MANIFEST_NAME).write_text(
            json.dumps({"testable": True, "acceptance_tests": []})
        )
        out = verification.verify(repo=tmp_path, base_commit="x", scratch_dir=tmp_path)
        assert out.state == TaskState.INVALID_ACCEPTANCE_TEST


class TestLocalizeCommand:
    """Guard the absolute-cd contamination fix (flask src-layout case)."""

    def test_rewrites_absolute_cd_to_worktree(self, tmp_path):
        repo = tmp_path / "run" / "repo"
        wt = tmp_path / "base-worktree"
        repo.mkdir(parents=True)
        wt.mkdir()
        # The exact shape the flask agent emitted: cd into the task repo, then
        # PYTHONPATH=src pytest. The absolute cd must be redirected to the wt.
        cmd = f"cd {repo} && PYTHONPATH=src python3 -m pytest tests/test_x.py::t -v"
        out = verification._localize_command(cmd, repo, wt)
        assert str(repo) not in out
        assert f"cd {wt} &&" in out
        # The relative PYTHONPATH/test path is untouched (resolves against wt).
        assert "PYTHONPATH=src python3 -m pytest tests/test_x.py::t" in out

    def test_rewrites_absolute_subpath_before_repo(self, tmp_path):
        # PYTHONPATH pointing at an absolute repo subdir must also be redirected.
        repo = tmp_path / "repo"
        wt = tmp_path / "wt"
        repo.mkdir()
        wt.mkdir()
        cmd = f"PYTHONPATH={repo}/src python -m pytest {repo}/tests/t.py"
        out = verification._localize_command(cmd, repo, wt)
        assert str(repo) not in out
        assert f"PYTHONPATH={wt}/src" in out
        assert f"{wt}/tests/t.py" in out

    def test_relative_command_unchanged(self, tmp_path):
        repo = tmp_path / "repo"
        wt = tmp_path / "wt"
        repo.mkdir()
        wt.mkdir()
        cmd = "PYTHONPATH=src python -m pytest tests/test_x.py"
        assert verification._localize_command(cmd, repo, wt) == cmd


def test_red_phase_uses_localized_command(monkeypatch, tmp_path):
    """End-to-end: the red-phase run must receive the worktree-localized command.

    Reproduces the flask bug: agent's acceptance command hardcodes `cd <repo>`;
    without localization the red run executes against the fixed task repo.
    """

    repo = tmp_path / "repo"
    repo.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / VERIFICATION_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "testable": True,
                "acceptance_tests": [
                    {
                        "name": "t",
                        "command": f"cd {repo} && python -m pytest tests/t.py",
                        "test_paths": ["tests/t.py"],
                    }
                ],
            }
        )
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "t.py").write_text("def test_ok():\n    assert True\n")

    seen = {"green": None, "red": None}
    calls = {"n": 0}

    def fake_run_shell(command, *, cwd, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            seen["green"] = (command, str(cwd))
        else:
            seen["red"] = (command, str(cwd))
        return 0, ""

    class _OkWorktree:
        def __init__(self, repo, base):
            self.repo = repo

        def __enter__(self):
            wt = tmp_path / "base-wt"
            wt.mkdir(exist_ok=True)
            return wt

        def __exit__(self, *a):
            return None

    monkeypatch.setattr(verification, "_run_shell", fake_run_shell)
    monkeypatch.setattr(verification, "_BaseWorktree", _OkWorktree)
    monkeypatch.setattr(verification, "_overlay_paths", lambda r, w, p: True)

    verification.verify(repo=repo, base_commit="abc", scratch_dir=scratch)

    # GREEN ran in the task repo with the original (absolute-cd) command.
    assert str(repo) in seen["green"][0]
    # RED ran with the localized command: the absolute repo path is gone,
    # redirected to the worktree, so it can no longer teleport into the fix.
    assert str(repo) not in seen["red"][0]
    assert str(tmp_path / "base-wt") in seen["red"][0]
