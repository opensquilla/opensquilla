"""Regression tests: ``run_sandboxed`` must always reap its child.

The original ``run_sandboxed`` only wrapped ``proc.communicate`` for
``subprocess.TimeoutExpired``. Any other exception (decode error in
``_decode_stream``, pipe ``OSError``, ``KeyboardInterrupt`` after
``Popen``) left a running child with open stdout/stderr pipes — the
process would linger until ``Popen.__del__`` ran, and the OS would
file ``ResourceWarning`` for the unreaped pipes.

The fix wraps the post-``Popen`` block in a ``try/finally`` that
calls ``proc.kill()`` + ``proc.wait()`` on the exception path and
explicitly closes the open pipes on every path.
"""

from __future__ import annotations

import subprocess

import pytest

from opensquilla.safety import sandbox as sandbox_mod
from opensquilla.safety.sandbox import (
    REASON_WALL_LIMIT,
    SandboxLimits,
    run_sandboxed,
)


class _FakeProcess:
    """Minimal stand-in for ``subprocess.Popen`` that records lifecycle calls.

    The test installs this in place of ``subprocess.Popen`` for the
    duration of ``run_sandboxed`` so we can observe kill / wait / close
    behaviour without spawning a real subprocess.
    """

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.args = args
        self.kwargs = kwargs
        self.killed = False
        self.waited = False
        self.communicate_calls = 0
        self.stdout_closed = False
        self.stderr_closed = False
        self.stdin_closed = False
        self.returncode = 0

        # ``Popen`` exposes stdout/stderr/stdin as streams; we model
        # them as objects with a close() so the finally block can
        # exercise them.
        self.stdout = _FakeStream(self, "stdout")
        self.stderr = _FakeStream(self, "stderr")
        self.stdin = None  # stdin=None in tests unless explicitly set

    def communicate(self, input=None, timeout=None):  # type: ignore[no-untyped-def]
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            # First call: raise a non-timeout exception so we exercise
            # the outer except-BaseException branch.
            raise RuntimeError("simulated pipe failure")
        return (b"", b"")

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None):  # type: ignore[no-untyped-def]
        self.waited = True
        return self.returncode


class _FakeStream:
    def __init__(self, proc: _FakeProcess, name: str) -> None:
        self._proc = proc
        self._name = name

    def close(self) -> None:
        setattr(self._proc, f"{self._name}_closed", True)


def _install_fake_popen(monkeypatch: pytest.MonkeyPatch) -> _FakeProcess:
    """Replace ``subprocess.Popen`` inside ``safety.sandbox`` with a spy.

    Returns the single ``_FakeProcess`` instance the spy hands out, so
    tests can assert on its lifecycle state.
    """

    captured: dict[str, _FakeProcess] = {}

    def fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        proc = _FakeProcess(*args, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(sandbox_mod.subprocess, "Popen", fake_popen)
    return captured.setdefault("proc", _FakeProcess())


@pytest.mark.skipif(
    not sandbox_mod.HAS_RESOURCE, reason="resource module unavailable on this platform"
)
def test_run_sandboxed_kills_child_on_non_timeout_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-timeout exception during communicate must kill + wait the child."""

    proc = _install_fake_popen(monkeypatch)

    with pytest.raises(RuntimeError, match="simulated pipe failure"):
        run_sandboxed(["/bin/echo", "hi"], SandboxLimits(wall_seconds=10))

    # The child must be killed and reaped so it does not linger.
    assert proc.killed is True
    assert proc.waited is True
    # The pipes must be closed even on the exception path.
    assert proc.stdout_closed is True
    assert proc.stderr_closed is True


@pytest.mark.skipif(
    not sandbox_mod.HAS_RESOURCE, reason="resource module unavailable on this platform"
)
def test_run_sandboxed_timeout_branch_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TimeoutExpired path must still reap the child + close pipes."""

    class _TimeoutProcess(_FakeProcess):
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            self.first = True

        def communicate(self, input=None, timeout=None):  # type: ignore[no-untyped-def]
            if self.first:
                self.first = False
                raise subprocess.TimeoutExpired(cmd=["/bin/sleep"], timeout=10)
            return (b"", b"")

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9  # SIGKILL

    captured: dict[str, _FakeProcess] = {}

    def fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        proc = _TimeoutProcess(*args, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(sandbox_mod.subprocess, "Popen", fake_popen)
    proc = captured["proc"]

    result = run_sandboxed(["/bin/sleep", "999"], SandboxLimits(wall_seconds=1))

    assert result.reason == REASON_WALL_LIMIT
    assert proc.killed is True
    assert proc.waited is True
    # Pipes closed by the finally block.
    assert proc.stdout_closed is True
    assert proc.stderr_closed is True


@pytest.mark.skipif(
    not sandbox_mod.HAS_RESOURCE, reason="resource module unavailable on this platform"
)
def test_run_sandboxed_timeout_branch_reaps_when_recollect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the post-kill ``communicate()`` call also raises, the child
    must still be reaped so the timeout branch upholds the "always
    reap" guarantee."""

    class _RecollectFailsProcess(_FakeProcess):
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            self.first = True

        def communicate(self, input=None, timeout=None):  # type: ignore[no-untyped-def]
            if self.first:
                self.first = False
                raise subprocess.TimeoutExpired(cmd=["/bin/sleep"], timeout=10)
            # Second call (post-kill) must also raise — that's the
            # path that previously left the child un-reaped.
            raise RuntimeError("simulated post-kill read failure")

        def kill(self) -> None:
            self.killed = True
            # ``returncode`` stays ``None`` so the new fallback
            # ``wait()`` branch is exercised.

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            self.waited = True
            self.returncode = -9
            return self.returncode

    captured: dict[str, _FakeProcess] = {}

    def fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        proc = _RecollectFailsProcess(*args, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(sandbox_mod.subprocess, "Popen", fake_popen)
    proc = captured["proc"]

    result = run_sandboxed(["/bin/sleep", "999"], SandboxLimits(wall_seconds=1))

    assert result.reason == REASON_WALL_LIMIT
    assert proc.killed is True, "child must be killed on timeout"
    assert proc.waited is True, (
        "child must be waited on even when post-kill communicate() raises"
    )
    assert proc.stdout_closed is True
    assert proc.stderr_closed is True


@pytest.mark.skipif(
    not sandbox_mod.HAS_RESOURCE, reason="resource module unavailable on this platform"
)
def test_run_sandboxed_success_path_closes_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On success, the finally block still closes the pipes that
    ``communicate`` did not close (it closes them in CPython but the
    explicit close is harmless and prevents ResourceWarning)."""

    class _HappyProcess(_FakeProcess):
        def communicate(self, input=None, timeout=None):  # type: ignore[no-untyped-def]
            self.communicate_calls += 1
            return (b"ok\n", b"")

    captured: dict[str, _FakeProcess] = {}

    def fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        proc = _HappyProcess(*args, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(sandbox_mod.subprocess, "Popen", fake_popen)
    proc = captured["proc"]

    result = run_sandboxed(["/bin/echo", "hi"], SandboxLimits(wall_seconds=5))

    assert result.reason == sandbox_mod.REASON_OK
    assert result.stdout == "ok\n"
    # Popen lifecycle clean: not killed (clean exit), pipes closed.
    assert proc.killed is False
    assert proc.stdout_closed is True
    assert proc.stderr_closed is True
