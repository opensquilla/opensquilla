"""Unit tests for opensquilla.contrib.codetask.verification."""

import json
import shutil
import subprocess
import sys

import pytest

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
        def fake_shell(command, *, cwd, timeout, repo=None):
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

        def fake_shell(command, *, cwd, timeout, repo=None):
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


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
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

    def test_sibling_path_not_corrupted(self, tmp_path):
        # /abs/repo must NOT rewrite a sibling like /abs/repo-fixture or
        # /abs/repo2 (codex review: raw substring replace would corrupt them).
        repo = tmp_path / "repo"
        wt = tmp_path / "wt"
        repo.mkdir()
        wt.mkdir()
        sibling = f"{repo}-fixture"
        sibling2 = f"{repo}2"
        cmd = f"cat {sibling}/data && ls {sibling2} && cd {repo} && pytest"
        out = verification._localize_command(cmd, repo, wt)
        # The sibling paths survive intact...
        assert sibling in out
        assert sibling2 in out
        # ...but the exact repo path (followed by a space) is rewritten.
        assert f"cd {wt} && pytest" in out

    def test_punctuation_siblings_not_corrupted(self, tmp_path):
        # Filename-legal chars beyond [A-Za-z0-9._-] (codex review #2): the
        # boundary must NOT fire on these, so the siblings stay intact.
        repo = tmp_path / "repo"
        wt = tmp_path / "wt"
        repo.mkdir()
        wt.mkdir()
        for ch in "+@=,~.":
            sibling = f"{repo}{ch}fixture"
            out = verification._localize_command(f"cat {sibling}/x", repo, wt)
            assert sibling in out, f"sibling with '{ch}' was corrupted: {out}"
            assert str(wt) not in out, f"'{ch}' wrongly treated as a boundary: {out}"

    def test_real_boundaries_rewrite(self, tmp_path):
        # The genuine path boundaries DO rewrite: '/', space, quote, colon, EOL.
        repo = tmp_path / "repo"
        wt = tmp_path / "wt"
        repo.mkdir()
        wt.mkdir()
        for tail in ["/src && x", " && x", '"', ":/other", ";", ")"]:
            out = verification._localize_command(f"cmd {repo}{tail}", repo, wt)
            assert str(repo) not in out, f"boundary '{tail}' failed to rewrite: {out}"
            assert str(wt) in out


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
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

    def fake_run_shell(command, *, cwd, timeout, repo=None):
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


def test_run_shell_resolves_python_from_repo_venv_in_foreign_cwd(tmp_path):
    """Even when cwd has NO venv (the base worktree), repo= makes bare
    python AND python3 resolve to the run repo's .venv interpreter."""
    from opensquilla.contrib.codetask import verification

    repo = tmp_path / "repo"
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake = venv_bin / "python"
    fake.write_text("#!/bin/sh\necho VENV_PY_OK\n")
    fake.chmod(0o755)
    foreign = tmp_path / "wt"  # like the base worktree: no .venv here
    foreign.mkdir()

    rc, out = verification._run_shell("python", cwd=foreign, timeout=30, repo=repo)
    assert rc == 0 and "VENV_PY_OK" in out, (rc, out)
    rc, out = verification._run_shell("python3", cwd=foreign, timeout=30, repo=repo)
    assert rc == 0 and "VENV_PY_OK" in out, (rc, out)  # python3 too (uv-venv safety)


def test_run_shell_sets_uv_project_for_uv_repo(tmp_path):
    """For a uv project (has uv.lock), _run_shell exports UV_PROJECT=<repo> so
    `uv run` reuses the run repo's env even from the base worktree; non-uv repos
    get no UV_PROJECT."""
    from opensquilla.contrib.codetask import verification

    uv_repo = tmp_path / "uvrepo"
    uv_repo.mkdir()
    (uv_repo / "uv.lock").write_text("", encoding="utf-8")
    foreign = tmp_path / "wt"  # like the base worktree
    foreign.mkdir()

    rc, out = verification._run_shell(
        'echo "UVP=[$UV_PROJECT]"', cwd=foreign, timeout=30, repo=uv_repo
    )
    assert rc == 0 and f"UVP=[{uv_repo}]" in out, out

    plain = tmp_path / "plainrepo"
    plain.mkdir()  # no uv.lock
    rc, out = verification._run_shell(
        'echo "UVP=[$UV_PROJECT]"', cwd=foreign, timeout=30, repo=plain
    )
    assert rc == 0 and "UVP=[]" in out, out


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_uv_run_from_worktree_reuses_repo_venv(tmp_path):
    """End-to-end: with UV_PROJECT injected by _run_shell, `uv run` from a base
    worktree (which has NO .venv) reuses the RUN REPO's .venv -- deps are present
    and no separate wt/.venv is built. Skips offline (uv sync needs the cache)."""
    from opensquilla.contrib.codetask import verification

    def g(cmd, cwd):
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    proj = tmp_path / "proj"
    proj.mkdir()
    g(["git", "init", "-q"], proj)
    g(["git", "config", "user.email", "s@s"], proj)
    g(["git", "config", "user.name", "s"], proj)
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
        'dependencies = []\n[dependency-groups]\ndev = ["pytest>=8"]\n',
        encoding="utf-8",
    )
    (proj / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (proj / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    sync = g(["uv", "sync", "--all-groups"], proj)
    if sync.returncode != 0:
        pytest.skip(f"uv sync unavailable (offline?): {(sync.stderr or '')[-160:]}")
    g(["git", "add", "-A"], proj)
    g(["git", "commit", "-qm", "init"], proj)

    wt = tmp_path / "wt"
    g(["git", "worktree", "add", "-q", "--detach", str(wt)], proj)
    assert not (wt / ".venv").exists()

    rc, out = verification._run_shell(
        "uv run --locked python -c 'import sys, pytest; print(\"PREFIX=\" + sys.prefix)'",
        cwd=wt, timeout=180, repo=proj,
    )
    assert rc == 0, out
    assert f"PREFIX={proj}/.venv" in out, out  # reused the repo venv, not wt/.venv
    assert not (wt / ".venv").exists(), "uv built a separate worktree venv"


def test_tail_bounds_output():
    assert verification._tail("") == ""
    assert verification._tail("a\nb\nc") == "a\nb\nc"
    many = "\n".join(str(i) for i in range(100))
    out = verification._tail(many, max_lines=10)
    assert out.splitlines() == [str(i) for i in range(90, 100)]
    big = "x" * 9000
    assert len(verification._tail(big, max_chars=4000)) == 4000


# ─────────────── bash resolution (probe-past-fake-stub) ──────────────────
# Field report: on Windows a fake `bash.cmd` ahead of real Git Bash on PATH
# hijacks `shutil.which("bash")` and the verifier dies on the stub instead
# of falling through to the real shell. The class also covers WSL launchers
# that exist but exit non-zero when WSL is not configured. POSIX is bit-
# equivalent to the old shutil.which path (the bug is Windows-only), so the
# enumeration/probe tests below are skipped there.

import os  # noqa: E402
import sys  # noqa: E402  -- used by the busybox-mimic test below


@pytest.fixture(autouse=True)
def _reset_bash_cache_between_tests():
    verification._reset_bash_cache()
    yield
    verification._reset_bash_cache()


def _real_bash() -> str:
    real = shutil.which("bash")
    if real is None:
        pytest.skip("real bash not available")
    return real


@pytest.mark.skipif(os.name != "nt", reason="fake bash.cmd hijack is Windows-only")
def test_resolve_bash_skips_fake_cmd_stub(tmp_path, monkeypatch):
    """Mirror the field report: fake bash.cmd ahead of real bash on PATH.

    Without the probe, `shutil.which("bash")` returns the .cmd stub and the
    verifier crashes with exit 17 + "FAKE BASH STUB". `_resolve_bash` must
    fall past it to the real Git Bash entry further down PATH.
    """
    real = _real_bash()
    fake_dir = tmp_path / "fake-bin"
    fake_dir.mkdir()
    (fake_dir / "bash.cmd").write_text(
        "@echo FAKE BASH STUB\r\n@exit /b 17\r\n", encoding="ascii"
    )
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{os.path.dirname(real)}")
    monkeypatch.delenv("OPENSQUILLA_BASH", raising=False)

    resolved = verification._resolve_bash()

    assert resolved is not None
    assert os.path.normcase(resolved) != os.path.normcase(str(fake_dir / "bash.cmd"))
    # And it actually runs the verifier command:
    rc, out = verification._run_shell("echo real_bash_ran", cwd=tmp_path, timeout=10)
    assert rc == 0 and "real_bash_ran" in out, (rc, out)


@pytest.mark.skipif(os.name != "nt", reason="enumerate-and-probe is Windows-only")
def test_resolve_bash_skips_failing_probe(tmp_path, monkeypatch):
    """A bash whose -lc probe exits non-zero (e.g. an unconfigured WSL stub
    that prints an error and exits 1) must be skipped in favor of a later
    candidate that actually runs."""
    real = _real_bash()
    broken_dir = tmp_path / "broken-bin"
    broken_dir.mkdir()
    stub = broken_dir / "bash.cmd"
    stub.write_text("@echo broken-bash\r\n@exit /b 99\r\n", encoding="ascii")
    monkeypatch.setenv("PATH", f"{broken_dir}{os.pathsep}{os.path.dirname(real)}")
    monkeypatch.delenv("OPENSQUILLA_BASH", raising=False)

    resolved = verification._resolve_bash()
    assert resolved is not None
    assert os.path.normcase(resolved) != os.path.normcase(str(stub))


@pytest.mark.skipif(os.name != "nt", reason="busybox-vs-bash discrimination is Windows-only")
def test_resolve_bash_rejects_non_bash_with_clear_sentinel(tmp_path, monkeypatch):
    """The probe must reject a shell that runs ``-lc`` cleanly but isn't
    actually bash (e.g. busybox-w32's bash.exe), because verification
    commands lean on bash-only syntax (``[[ ]]``, arrays, ``BASH_SOURCE``).

    Discrimination test: this stub correctly handles a bare ``echo X`` script
    — so it would pass the naive ``echo SENTINEL`` probe — but fails the
    bash-specific ``$BASH_VERSION`` guard the way a real busybox would.
    Proves the strengthened probe is doing real work.
    """
    real = _real_bash()
    not_bash = tmp_path / "not-bash"
    not_bash.mkdir()
    mimic_py = not_bash / "busybox_mimic.py"
    mimic_py.write_text(
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "# Mimic only what is needed: a shell that handles `-lc \"echo X\"` but\n"
        "# does not set BASH_VERSION, so the probe's test-guard fails and the\n"
        "# && short-circuits -- same observable shape as busybox-w32 bash.\n"
        "if len(argv) >= 2 and argv[0] in ('-lc', '-c'):\n"
        "    script = argv[1].strip()\n"
        "    if script.startswith('echo '):\n"
        "        print(script[5:].strip().strip('\\\"').strip(\"'\"))\n"
        "        sys.exit(0)\n"
        "    sys.exit(1)\n"
        "sys.exit(2)\n",
        encoding="ascii",
    )
    stub = not_bash / "bash.cmd"
    stub.write_text(
        f'@"{sys.executable}" "{mimic_py}" %*\r\n', encoding="ascii"
    )
    monkeypatch.setenv("PATH", f"{not_bash}{os.pathsep}{os.path.dirname(real)}")
    monkeypatch.delenv("OPENSQUILLA_BASH", raising=False)

    # Sanity: the stub does pass the naive probe (proves the test is honest).
    import subprocess as _sp
    naive = _sp.run(
        [str(stub), "-lc", f"echo {verification._BASH_PROBE_SENTINEL}"],
        capture_output=True, text=True, timeout=10,
    )
    assert naive.returncode == 0
    assert verification._BASH_PROBE_SENTINEL in (naive.stdout or "")

    # And the strengthened probe rejects it, falling through to real bash.
    resolved = verification._resolve_bash()
    assert resolved is not None
    assert os.path.normcase(resolved) != os.path.normcase(str(stub))


@pytest.mark.skipif(os.name != "nt", reason="OPENSQUILLA_BASH override is Windows-only")
def test_resolve_bash_honors_env_override(tmp_path, monkeypatch):
    """OPENSQUILLA_BASH wins over PATH discovery — including over a real bash
    already on PATH — so operators can force a specific shell without
    rearranging PATH."""
    real = _real_bash()
    monkeypatch.setenv("OPENSQUILLA_BASH", real)
    # Remove all bash candidates from PATH so the only way to find it is via override.
    monkeypatch.setenv("PATH", str(tmp_path))

    assert verification._resolve_bash() == real


@pytest.mark.skipif(os.name != "nt", reason="enumerate-and-probe is Windows-only")
def test_resolve_bash_returns_none_when_no_working_bash(tmp_path, monkeypatch):
    """If no candidate probes successfully, return None and let `_run_shell`
    surface the actionable OSERROR hint (instead of running a broken stub)."""
    monkeypatch.setenv("PATH", str(tmp_path))  # empty dir, no bash
    monkeypatch.delenv("OPENSQUILLA_BASH", raising=False)
    # Also blank out the Git-Bash fallback locations our resolver checks.
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(env_var, str(tmp_path))

    assert verification._resolve_bash() is None
    rc, out = verification._run_shell("true", cwd=tmp_path, timeout=5)
    assert rc == -1 and "OSERROR" in out and "bash" in out, out


def test_resolve_bash_memoizes(tmp_path, monkeypatch):
    """Once resolved, repeated calls must return the cached path and skip
    re-probing — the gateway runs many _run_shell calls per task and probes
    cost ~50ms each on Windows."""
    real = _real_bash()
    if os.name == "nt":
        monkeypatch.setenv("OPENSQUILLA_BASH", real)
    # POSIX: cache short-circuits on shutil.which("bash") which is `real`.

    first = verification._resolve_bash()
    calls = {"n": 0}
    real_probe = verification._probe_bash

    def counting_probe(p):
        calls["n"] += 1
        return real_probe(p)

    monkeypatch.setattr(verification, "_probe_bash", counting_probe)
    second = verification._resolve_bash()

    assert first == second == real
    assert calls["n"] == 0, "cached resolution must not re-probe"
