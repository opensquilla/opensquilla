"""Regression tests for the orphan-lock-recovery path in
``opensquilla.gateway.pidlock.GatewayPidLock.acquire``.

A gateway daemon that dies without running its atexit / signal
cleanup (kill -9, OOM kill, host power loss) leaves behind
``gateway.pid.lock`` with no companion ``gateway.pid``. Before
this fix, a fresh ``gateway start`` would hit the "lock fails
(race)" branch on the leftover lock, wait the full readiness
timeout, and report a misleading "another gateway is already
running" error even though no process is bound to the port.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from opensquilla.gateway.pidlock import (
    GatewayPidLock,
    _file_age_seconds,
    _read_pid_from_path,
)


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- _read_pid_from_path ----------------------------------------------------


def test_read_pid_from_path_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert _read_pid_from_path(tmp_path / "missing.pid") is None


def test_read_pid_from_path_returns_none_for_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "gateway.pid"
    p.write_text("{not valid json", encoding="utf-8")
    assert _read_pid_from_path(p) is None


def test_read_pid_from_path_returns_none_when_pid_field_missing(
    tmp_path: Path,
) -> None:
    p = tmp_path / "gateway.pid"
    p.write_text(json.dumps({"start_ts": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    assert _read_pid_from_path(p) is None


def test_read_pid_from_path_returns_int_for_valid_payload(tmp_path: Path) -> None:
    p = tmp_path / "gateway.pid"
    p.write_text(json.dumps({"pid": 12345, "start_ts": "2026-01-01"}), encoding="utf-8")
    assert _read_pid_from_path(p) == 12345


# --- _file_age_seconds -------------------------------------------------------


def test_file_age_seconds_is_zero_for_missing_file(tmp_path: Path) -> None:
    assert _file_age_seconds(tmp_path / "nope") == 0.0


def test_file_age_seconds_is_positive_for_existing_file(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_text("x", encoding="utf-8")
    # mtime resolution is platform-dependent; assert strictly >= 0
    # and that the value is a float — the test machine might be
    # fast enough that mtime == now().
    age = _file_age_seconds(p)
    assert age >= 0.0
    assert isinstance(age, float)


# --- GatewayPidLock.acquire — orphan-lock recovery ---------------------------


def test_acquire_recovers_when_only_lock_file_remains(
    state_dir: Path,
) -> None:
    """The real-world bug: gateway.pid missing, gateway.pid.lock
    present (a previous daemon died ungracefully). acquire() must
    log it, remove the orphan lock, and succeed.
    """
    lock = state_dir / "gateway.pid.lock"
    lock.write_bytes(b"orphan")
    # gateway.pid is intentionally absent.

    gp = GatewayPidLock(state_dir)
    with mock.patch.object(sys, "exit") as exit_mock:  # belt + braces
        gp.acquire()
        exit_mock.assert_not_called()

    # The new instance has taken over: pid file is freshly written,
    # the lock file still exists (we are now holding the OS lock on
    # it), and release() tears both down cleanly.
    assert (state_dir / "gateway.pid").is_file()
    assert lock.is_file()
    info = json.loads((state_dir / "gateway.pid").read_text(encoding="utf-8"))
    assert "pid" in info and "start_ts" in info
    gp.release()
    assert not (state_dir / "gateway.pid").exists()
    assert not lock.exists()


def test_acquire_does_not_remove_live_pid_lock(
    state_dir: Path,
) -> None:
    """When the pid file points at a live process, acquire() must
    refuse to start, *not* silently remove the lock. (The previous
    daemon is still healthy; we do not want to evict it.)
    """
    pid = state_dir / "gateway.pid"
    pid.write_text(
        json.dumps({"pid": 999_999_999, "start_ts": "2026-01-01"}),
        encoding="utf-8",
    )
    (state_dir / "gateway.pid.lock").write_bytes(b"live")

    # Pretend PID 999_999_999 is alive so the lock refuses to give
    # up its slot.
    with mock.patch(
        "opensquilla.gateway.pidlock._is_alive", return_value=True
    ):
        gp = GatewayPidLock(state_dir)
        with mock.patch.object(sys, "exit") as exit_mock:
            gp.acquire()
            exit_mock.assert_called_once_with(1)
        # Both files untouched.
        assert pid.is_file()
        assert (state_dir / "gateway.pid.lock").is_file()


def test_acquire_still_recovers_stale_pid_with_live_lock(
    state_dir: Path,
) -> None:
    """If gateway.pid says PID 42 but PID 42 is dead, the original
    path (stale_overwritten + unlink pid file) is the right one and
    must still win. The new orphan-lock branch only fires when the
    pid file itself is missing.
    """
    (state_dir / "gateway.pid").write_text(
        json.dumps({"pid": 42, "start_ts": "2026-01-01"}), encoding="utf-8"
    )
    (state_dir / "gateway.pid.lock").write_bytes(b"stale")

    with mock.patch(
        "opensquilla.gateway.pidlock._is_alive", return_value=False
    ):
        gp = GatewayPidLock(state_dir)
        with mock.patch.object(sys, "exit") as exit_mock:
            gp.acquire()
            exit_mock.assert_not_called()
    # pid file replaced with the new instance's payload.
    info = json.loads((state_dir / "gateway.pid").read_text(encoding="utf-8"))
    assert info["pid"] != 42
    gp.release()
