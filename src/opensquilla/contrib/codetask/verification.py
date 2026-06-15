"""Runner-authoritative red→green→regression verification.

The agent writes a machine-readable manifest (verification.json) into the
scratch dir declaring its acceptance tests. The runner does NOT trust the
agent's self-report: it independently re-runs each acceptance command at the
task HEAD (green) and, in a throwaway ``git worktree`` at the base commit
with the agent's test files overlaid, at the base (red). This distinguishes
a genuine fix from a no-op, and surfaces the false-negative states the
design review (#6) called out.

Manifest schema (v1):
    {
      "testable": true,
      "acceptance_tests": [
        {"name": "...", "command": "pytest tests/test_x.py::test_y",
         "test_paths": ["tests/test_x.py"]}
      ],
      "regression_command": "pytest -q",   // optional
      "assumptions": ["..."],              // optional
      "not_testable_reason": ""            // required iff testable is false
    }
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from opensquilla.contrib.codetask.config import (
    DEFAULT_ACCEPTANCE_TIMEOUT,
    DEFAULT_REGRESSION_TIMEOUT,
)
from opensquilla.contrib.codetask.types import (
    AcceptanceCheck,
    RegressionResult,
    TaskState,
)

logger = logging.getLogger(__name__)

_PYTEST_SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors)")
# Failing node ids, e.g. "FAILED tests/test_x.py::test_y - AssertionError".
_PYTEST_FAILED_LINE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)


@dataclass
class VerificationOutcome:
    state: TaskState
    acceptance: list[AcceptanceCheck]
    regression: RegressionResult | None
    assumptions: list[str]
    detail: str = ""


def load_manifest(scratch_dir: Path) -> dict | None:
    """Load and shallow-validate the agent's verification.json. None if absent."""
    from opensquilla.contrib.codetask.config import VERIFICATION_MANIFEST_NAME

    path = scratch_dir / VERIFICATION_MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def verify(
    *,
    repo: Path,
    base_commit: str,
    scratch_dir: Path,
    acceptance_timeout: int = DEFAULT_ACCEPTANCE_TIMEOUT,
    regression_timeout: int = DEFAULT_REGRESSION_TIMEOUT,
) -> VerificationOutcome:
    """Run the full verification protocol and decide the task state."""
    manifest = load_manifest(scratch_dir)
    if manifest is None:
        return VerificationOutcome(
            state=TaskState.INVALID_ACCEPTANCE_TEST,
            acceptance=[],
            regression=None,
            assumptions=[],
            detail="agent did not emit a valid verification.json manifest",
        )

    assumptions = [str(a) for a in manifest.get("assumptions", []) if str(a).strip()]

    if manifest.get("testable") is False:
        reason = str(manifest.get("not_testable_reason", "")).strip()
        return VerificationOutcome(
            state=TaskState.NOT_TESTABLE,
            acceptance=[],
            regression=None,
            assumptions=assumptions,
            detail=reason or "agent reported the task is not automatically testable",
        )

    raw_tests = manifest.get("acceptance_tests") or []
    checks: list[AcceptanceCheck] = []
    for entry in raw_tests:
        if not isinstance(entry, dict):
            continue
        cmd = str(entry.get("command", "")).strip()
        if not cmd:
            continue
        checks.append(
            AcceptanceCheck(
                name=str(entry.get("name") or cmd)[:80],
                command=cmd,
                expected="pass",
            )
        )
    test_paths_by_index = [
        [str(p) for p in (e.get("test_paths") or [])] if isinstance(e, dict) else []
        for e in raw_tests
    ]

    if not checks:
        return VerificationOutcome(
            state=TaskState.INVALID_ACCEPTANCE_TEST,
            acceptance=[],
            regression=None,
            assumptions=assumptions,
            detail="manifest declared testable but listed no runnable acceptance tests",
        )

    # GREEN: run each acceptance command at the current (post-change) tree.
    for check in checks:
        rc, _ = _run_shell(check.command, cwd=repo, timeout=acceptance_timeout)
        check.after = "pass" if rc == 0 else "fail"

    # RED: re-run each acceptance command at base, with the agent's test files
    # overlaid, in a throwaway worktree. ``before`` is left None whenever we
    # could not establish the red state, and the reason is recorded so the
    # state machine can fail CLOSED rather than claim an unprovable VERIFIED.
    red_unprovable: str | None = None
    try:
        with _BaseWorktree(repo, base_commit) as wt:
            for check, paths in zip(checks, test_paths_by_index, strict=False):
                safe = _safe_rel_paths(paths)
                if not safe:
                    check.before = None  # no usable test paths -> cannot prove red
                    red_unprovable = red_unprovable or "missing_test_paths"
                    continue
                if not _overlay_paths(repo, wt, safe):
                    check.before = None
                    red_unprovable = red_unprovable or "missing_test_paths"
                    continue
                # Rewrite any hardcoded task-repo path so a ``cd /abs/repo`` in
                # the agent's command cannot teleport the red check back into
                # the already-fixed task repo.
                wt_command = _localize_command(check.command, repo, wt)
                rc, _ = _run_shell(wt_command, cwd=wt, timeout=acceptance_timeout)
                check.before = "fail" if rc != 0 else "pass"
    except _WorktreeError as exc:
        logger.warning("base worktree unavailable, red phase skipped: %s", exc)
        red_unprovable = "worktree_failed"

    regression = _run_regression(
        manifest.get("regression_command"),
        repo=repo,
        base_commit=base_commit,
        timeout=regression_timeout,
    )

    state, detail = _decide_state(checks, regression, red_unprovable)
    return VerificationOutcome(
        state=state,
        acceptance=checks,
        regression=regression,
        assumptions=assumptions,
        detail=detail,
    )


def _decide_state(
    checks: list[AcceptanceCheck],
    regression: RegressionResult | None,
    red_unprovable: str | None,
) -> tuple[TaskState, str]:
    """Decide the task state, failing CLOSED when proof is incomplete."""
    all_green = all(c.after == "pass" for c in checks)
    if not all_green:
        return TaskState.FAILED, "an acceptance test did not pass after the change"

    regressed = bool(regression and regression.ran and (regression.new_failures or 0) > 0)
    if regressed:
        return TaskState.FAILED, "the change introduced new regression failures"

    # All acceptance green. We may only claim VERIFIED if every check was
    # independently proven red on the base commit.
    befores = [c.before for c in checks]
    if all(b == "fail" for b in befores):
        return TaskState.VERIFIED, ""
    if all(b == "pass" for b in befores):
        return TaskState.ALREADY_SATISFIED, "expected behavior already held on the base commit"

    # Green but red not (fully) established -> cannot prove the change matters.
    if red_unprovable == "worktree_failed":
        return (
            TaskState.ENVIRONMENT_BLOCKED,
            "acceptance passed but the base worktree could not be built to prove the red state",
        )
    return (
        TaskState.INVALID_ACCEPTANCE_TEST,
        "acceptance passed but its red state could not be proven (declare test_paths so the "
        "runner can re-create the failing state on the original code)",
    )


def _run_regression(
    command,
    *,
    repo: Path,
    base_commit: str,
    timeout: int,
) -> RegressionResult | None:
    if not command or not str(command).strip():
        return None
    cmd = str(command).strip()
    result = RegressionResult(command=cmd, ran=True)

    head_rc, head_out = _run_shell(cmd, cwd=repo, timeout=timeout)
    head_fail = _parse_failures(head_out, head_rc)
    head_names = _failing_names(head_out)
    result.passed = _parse_passes(head_out)
    result.failed = head_fail
    result.raw_tail = "\n".join(head_out.splitlines()[-15:])

    # Differential: run the same command at base to avoid penalizing
    # pre-existing failures.
    base_rc: int | None = None
    base_fail: int | None = None
    base_names: set[str] | None = None
    try:
        with _BaseWorktree(repo, base_commit) as wt:
            base_rc, base_out = _run_shell(
                _localize_command(cmd, repo, wt), cwd=wt, timeout=timeout
            )
            base_fail = _parse_failures(base_out, base_rc)
            base_names = _failing_names(base_out)
    except _WorktreeError:
        pass

    # Prefer a set difference of named failures (a new failure cannot be
    # masked by a fixed pre-existing one — codex review #4).
    if head_names is not None and base_names is not None:
        result.new_failures = len(head_names - base_names)
    elif base_fail is not None and head_fail is not None:
        result.new_failures = max(0, head_fail - base_fail)
    elif head_fail is not None:
        # No usable baseline: any head failure counts as new (conservative).
        result.new_failures = head_fail
    elif head_rc != 0:
        # Nonzero exit we could not parse: fail CLOSED, treat as regressed
        # (codex review #3 — do NOT silently report clean).
        result.new_failures = 1
    else:
        result.new_failures = 0
    return result


# ---------------------------------------------------------------------------
# Shell + git worktree helpers
# ---------------------------------------------------------------------------
class _WorktreeError(RuntimeError):
    pass


def _localize_command(command: str, repo: Path, target: Path) -> str:
    """Redirect any absolute reference to the task repo onto ``target``.

    The agent writes acceptance/regression commands while standing inside the
    task repo, so they frequently hardcode its absolute path (e.g.
    ``cd /abs/repo && PYTHONPATH=src pytest ...``). When the runner re-runs
    such a command in the base worktree to establish the red state, that
    absolute ``cd`` would teleport execution back into the agent-fixed task
    repo and silently contaminate the check (the test passes against the fix,
    so the runner wrongly concludes the behavior was already satisfied).

    Rewriting the task-repo path to the worktree path keeps the command inside
    the intended tree regardless of how the agent wrote it. Longest match
    first so ``/abs/repo/src`` is rewritten before ``/abs/repo``.

    The repo path is only rewritten at a real path boundary (end-of-string or
    a non-filename character such as ``/`` or a space), so a legitimate SIBLING
    path like ``/abs/repo-fixture`` is never corrupted (raw substring
    replacement would wrongly rewrite its ``/abs/repo`` prefix).
    """
    candidates = sorted({str(repo), str(repo.resolve())}, key=len, reverse=True)
    out = command
    for src in candidates:
        # Negative lookahead: the path must NOT be followed by a filename
        # continuation char, so ``-fixture`` / ``2`` / ``.bak`` siblings stay.
        pattern = re.escape(src) + r"(?![A-Za-z0-9._-])"
        out = re.sub(pattern, lambda _m: str(target), out)
    return out


def _run_shell(command: str, *, cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except OSError as exc:
        return -1, f"OSERROR: {exc}"


class _BaseWorktree:
    """Context manager: a detached worktree at base_commit, auto-removed."""

    def __init__(self, repo: Path, base_commit: str):
        self.repo = repo
        self.base_commit = base_commit
        self._dir: Path | None = None

    def __enter__(self) -> Path:
        import shutil

        tmp = Path(tempfile.mkdtemp(prefix="codetask-base-"))
        try:
            r = subprocess.run(
                ["git", "worktree", "add", "--detach", str(tmp), self.base_commit],
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise _WorktreeError(str(exc)) from exc
        if r.returncode != 0:
            # Do not leak the mkdtemp dir when the worktree was never added
            # (codex review #9).
            shutil.rmtree(tmp, ignore_errors=True)
            raise _WorktreeError((r.stderr or "").strip()[-200:])
        self._dir = tmp
        return tmp

    def __exit__(self, *exc) -> None:
        if self._dir is not None:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(self._dir)],
                cwd=str(self.repo),
                capture_output=True,
                timeout=60,
            )


def _safe_rel_paths(paths: list[str]) -> list[str]:
    """Keep only repo-relative paths (reject absolute and parent-escaping).

    Agent-declared test_paths are untrusted input; an absolute path or one
    containing ``..`` could read/overlay files outside the repo (codex
    review #7).
    """
    safe: list[str] = []
    for rel in paths:
        p = str(rel).strip()
        if not p:
            continue
        if PurePosixPath(p).is_absolute() or p.startswith("/") or "\\" in p:
            continue
        if any(part == ".." for part in PurePosixPath(p).parts):
            continue
        safe.append(p)
    return safe


def _overlay_paths(repo: Path, worktree: Path, paths: list[str]) -> bool:
    """Copy the given files from the task tree into the base worktree.

    Used so a NEW acceptance test (which does not exist at base) can be run
    against base source. Paths are assumed pre-validated by
    :func:`_safe_rel_paths`. Returns False if any path is missing or a copy
    fails (so the caller leaves ``before`` unproven rather than crashing).
    """
    import shutil

    for rel in paths:
        src = (repo / rel).resolve()
        try:
            src.relative_to(repo.resolve())
        except ValueError:
            return False  # symlink/escape outside the repo
        if not src.is_file():
            return False
        dest = worktree / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        except OSError:
            return False
    return True


def _failing_names(output: str) -> set[str] | None:
    """Extract failing test node ids from pytest-style output.

    Returns None when no ``FAILED <nodeid>`` lines are present (so the caller
    falls back to counts). Enables a set difference that a count cannot do.
    """
    names = set(_PYTEST_FAILED_LINE.findall(output))
    return names or None


def _parse_failures(output: str, returncode: int) -> int | None:
    counts = {kind: int(n) for n, kind in _PYTEST_SUMMARY.findall(output)}
    if counts:
        return counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    if returncode == 0:
        return 0
    return None  # nonzero but unparseable: unknown count


def _parse_passes(output: str) -> int | None:
    counts = {kind: int(n) for n, kind in _PYTEST_SUMMARY.findall(output)}
    return counts.get("passed") if counts else None
