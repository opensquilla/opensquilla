"""Tests for GatewayPidLock PID file placement (AC-C1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.gateway.pidlock import GatewayPidLock


def test_pid_file_in_state_dir_not_parent(tmp_path: Path) -> None:
    """AC-C1-1/AC-C1-2: PID file must land in state_dir, not state_dir.parent."""
    state_dir = tmp_path / "state"
    lock = GatewayPidLock(state_dir)
    lock.acquire()
    try:
        # PID file must be inside state_dir
        assert (state_dir / "gateway.pid").exists(), (
            f"gateway.pid not found in {state_dir}"
        )
        # PID file must NOT be in the parent directory
        assert not (tmp_path / "gateway.pid").exists(), (
            f"gateway.pid incorrectly written to parent {tmp_path}"
        )
    finally:
        lock.release()


def test_pid_lock_rejects_second_acquisition_while_first_is_held(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    first = GatewayPidLock(state_dir)
    first.acquire()
    try:
        second = GatewayPidLock(state_dir)
        with pytest.raises(SystemExit) as exc_info:
            second.acquire()

        assert exc_info.value.code == 1
    finally:
        first.release()


def test_pid_lock_release_is_idempotent(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    lock = GatewayPidLock(state_dir)
    lock.acquire()

    lock.release()
    lock.release()

    assert not (state_dir / "gateway.pid").exists()
    assert not (state_dir / "gateway.pid.lock").exists()
