from __future__ import annotations

import ctypes
import errno
import multiprocessing
import os
import shutil
import stat
import struct
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.recovery import (
    CrossDeviceMoveError,
    DestinationExistsError,
    ProfileLockBusyError,
    ProfileOperationLock,
    UnsafePathError,
    native_move_no_replace,
    profile_lock_path,
)
from opensquilla.recovery.atomic import (
    _linux_rename_no_replace,
    _macos_rename_no_replace,
    _windows_extended_path,
    _windows_move_no_replace,
)
from opensquilla.recovery.config_patch import ConfigSnapshot
from opensquilla.recovery.locking import (
    LegacyGatewayLock,
    acquire_legacy_gateway_locks,
    user_state_dir,
)


def _contend_for_lock(home: str, state_root: str, queue: multiprocessing.Queue) -> None:
    import os

    os.environ["OPENSQUILLA_USER_STATE_DIR"] = state_root
    os.environ["OPENSQUILLA_TEST_PROFILE_LOCK_ROOT"] = "1"
    try:
        with ProfileOperationLock(home):
            queue.put("acquired")
    except ProfileLockBusyError:
        queue.put("busy")


def test_user_state_override_is_ignored_without_the_explicit_test_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    override = tmp_path / "override"
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(override))
    monkeypatch.delenv("OPENSQUILLA_TEST_PROFILE_LOCK_ROOT", raising=False)

    assert user_state_dir() != override


def test_user_state_override_is_used_with_the_explicit_test_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    override = tmp_path / "override"
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(override))
    monkeypatch.setenv("OPENSQUILLA_TEST_PROFILE_LOCK_ROOT", "1")

    assert user_state_dir() == override


def _contend_for_gateway(state_dir: str, queue: multiprocessing.Queue) -> None:
    from opensquilla.gateway.pidlock import GatewayPidLock

    lock = GatewayPidLock(state_dir)
    try:
        lock.acquire()
    except SystemExit:
        queue.put("busy")
    else:
        queue.put("acquired")
        lock.release()


def test_profile_lock_is_same_process_reentrant_and_external(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "user-state"
    home = tmp_path / "profile"
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(state_root))

    with ProfileOperationLock(home):
        with ProfileOperationLock(home):
            assert profile_lock_path(home).is_file()

        context = multiprocessing.get_context("spawn" if sys.platform == "win32" else "fork")
        queue = context.Queue()
        process = context.Process(
            target=_contend_for_lock,
            args=(str(home), str(state_root), queue),
        )
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        assert queue.get(timeout=1) == "busy"

    with ProfileOperationLock(home):
        pass


def test_profile_lock_does_not_treat_another_thread_as_reentrant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(tmp_path / "user-state"))
    result: list[str] = []

    def contend() -> None:
        try:
            with ProfileOperationLock(home, timeout=0.05):
                result.append("acquired")
        except ProfileLockBusyError:
            result.append("busy")

    with ProfileOperationLock(home):
        thread = threading.Thread(target=contend)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert result == ["busy"]


def test_profile_lock_refuses_app_state_symlink_without_external_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_state = tmp_path / "user-state"
    external = tmp_path / "external"
    user_state.mkdir()
    external.mkdir()
    try:
        (user_state / "OpenSquilla").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(user_state))

    with pytest.raises(UnsafePathError):
        ProfileOperationLock(tmp_path / "profile").acquire()

    assert not (external / "profile-locks").exists()


def test_config_snapshot_rejects_windows_reparse_attribute_before_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text("synthetic = true\n", encoding="utf-8")
    original_lstat = Path.lstat
    original_open = os.open
    opened = False

    def fake_lstat(candidate: Path):
        value = original_lstat(candidate)
        if candidate != path:
            return value
        return SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_nlink=1,
            st_file_attributes=0x400,
            st_dev=value.st_dev,
            st_ino=value.st_ino,
            st_size=value.st_size,
            st_mtime_ns=value.st_mtime_ns,
        )

    def track_open(candidate, *args, **kwargs):
        nonlocal opened
        if Path(candidate) == path:
            opened = True
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(os, "open", track_open)

    with pytest.raises(UnsafePathError):
        ConfigSnapshot.capture(path)
    assert not opened


def test_native_move_never_replaces_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "value.txt").write_text("source", encoding="utf-8")
    (destination / "value.txt").write_text("destination", encoding="utf-8")

    with pytest.raises(DestinationExistsError):
        native_move_no_replace(source, destination)

    assert (source / "value.txt").read_text(encoding="utf-8") == "source"
    assert (destination / "value.txt").read_text(encoding="utf-8") == "destination"


def test_native_move_moves_a_regular_tree_between_real_parents(tmp_path: Path) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    destination = destination_parent / "destination"
    source.mkdir()
    (source / "value.txt").write_text("preserved", encoding="utf-8")

    native_move_no_replace(source, destination)

    assert not source.exists()
    assert (destination / "value.txt").read_text(encoding="utf-8") == "preserved"


@pytest.mark.skipif(sys.platform != "win32", reason="requires two native Windows volumes")
def test_windows_native_move_refuses_real_cross_volume_move() -> None:
    volume_a_value = os.environ.get("OPENSQUILLA_WINDOWS_TEST_VOLUME_A")
    volume_b_value = os.environ.get("OPENSQUILLA_WINDOWS_TEST_VOLUME_B")
    if not volume_a_value or not volume_b_value:
        running_in_ci = os.environ.get("CI", "").strip().lower() not in {
            "",
            "0",
            "false",
        }
        if running_in_ci:
            pytest.fail("Windows CI must provide both synthetic test volume roots")
        pytest.skip("requires the two synthetic Windows test volume roots")

    volume_a = Path(volume_a_value)
    volume_b = Path(volume_b_value)
    assert volume_a.stat().st_dev != volume_b.stat().st_dev
    token = uuid.uuid4().hex
    source_parent = volume_a / f"opensquilla-cross-volume-source-{token}"
    destination_parent = volume_b / f"opensquilla-cross-volume-destination-{token}"

    try:
        source_parent.mkdir(exist_ok=False)
        destination_parent.mkdir(exist_ok=False)
        assert source_parent.stat().st_dev != destination_parent.stat().st_dev

        source = source_parent / "source"
        destination = destination_parent / "destination"
        payload = source / "payload.bin"
        source.mkdir()
        payload.write_bytes(b"synthetic-cross-volume-payload")

        with pytest.raises(CrossDeviceMoveError):
            native_move_no_replace(source, destination)

        assert payload.read_bytes() == b"synthetic-cross-volume-payload"
        assert not destination.exists()
    finally:
        for owned_root in (source_parent, destination_parent):
            if owned_root.exists():
                shutil.rmtree(owned_root)


def test_linux_cross_filesystem_no_replace_fails_without_copy_delete_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    destination = destination_parent / "destination"
    source.mkdir()
    (source / "value.txt").write_text("preserved", encoding="utf-8")

    class FakeRenameAt2:
        argtypes = None
        restype = None

        def __call__(self, *_args: object) -> int:
            return -1

    monkeypatch.setattr(
        ctypes,
        "CDLL",
        lambda *_args, **_kwargs: SimpleNamespace(renameat2=FakeRenameAt2()),
    )
    monkeypatch.setattr(ctypes, "get_errno", lambda: errno.EXDEV)

    with pytest.raises(CrossDeviceMoveError):
        _linux_rename_no_replace(source, destination)

    assert source.is_dir()
    assert (source / "value.txt").read_text(encoding="utf-8") == "preserved"
    assert not destination.exists()


def test_native_move_refuses_symlink_in_source_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (source / "link").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(UnsafePathError):
        native_move_no_replace(source, destination)

    assert source.is_dir()
    assert not destination.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows long paths")
def test_windows_native_move_handles_real_path_longer_than_260_characters(
    tmp_path: Path,
) -> None:
    long_root = tmp_path
    for index in range(6):
        long_root /= f"segment-{index}-" + ("x" * 42)
    source_parent = long_root / "source-parent"
    destination_parent = long_root / "destination-parent"
    source_parent.mkdir(parents=True)
    destination_parent.mkdir(parents=True)
    source = source_parent / "candidate-profile"
    destination = destination_parent / "published-profile"
    source.mkdir()
    (source / "value.txt").write_text("long-path-preserved", encoding="utf-8")
    assert len(str(source)) > 260
    assert len(str(destination)) > 260

    native_move_no_replace(source, destination)

    assert not source.exists()
    assert (destination / "value.txt").read_text(encoding="utf-8") == (
        "long-path-preserved"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="requires a real Windows junction")
def test_windows_native_move_rejects_real_junction_in_source_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    destination = tmp_path / "destination"
    source.mkdir()
    outside.mkdir()
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(source / "junction"), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert os.path.isjunction(source / "junction")

    with pytest.raises(UnsafePathError):
        native_move_no_replace(source, destination)

    assert source.is_dir()
    assert outside.is_dir()
    assert not destination.exists()


def test_macos_no_replace_binds_source_and_destination_parent_handles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    destination = destination_parent / "destination"
    source.mkdir()
    calls: list[tuple[int, bytes, int, bytes, int]] = []

    class FakeRenameAt:
        argtypes = None
        restype = None

        def __call__(self, source_fd, source_name, destination_fd, destination_name, flags):
            calls.append(
                (source_fd, source_name, destination_fd, destination_name, flags)
            )
            return 0

    monkeypatch.setattr(
        "opensquilla.recovery.atomic.ctypes.CDLL",
        lambda *_args, **_kwargs: SimpleNamespace(renameatx_np=FakeRenameAt()),
    )

    _macos_rename_no_replace(source, destination)

    assert len(calls) == 1
    source_fd, source_name, destination_fd, destination_name, flags = calls[0]
    assert source_fd >= 0
    assert destination_fd >= 0
    assert source_name == b"source"
    assert destination_name == b"destination"
    assert flags == 0x00000004


def test_macos_no_replace_stops_if_open_parent_identity_changed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    source.mkdir()
    destination = destination_parent / "destination"
    called = False
    original_fstat = os.fstat

    class FakeRenameAt:
        argtypes = None
        restype = None

        def __call__(self, *_args):
            nonlocal called
            called = True
            return 0

    def changed_fstat(fd: int):
        value = original_fstat(fd)
        return SimpleNamespace(
            st_mode=value.st_mode,
            st_dev=value.st_dev,
            st_ino=value.st_ino + 1,
        )

    monkeypatch.setattr(
        "opensquilla.recovery.atomic.ctypes.CDLL",
        lambda *_args, **_kwargs: SimpleNamespace(renameatx_np=FakeRenameAt()),
    )
    monkeypatch.setattr("opensquilla.recovery.atomic.os.fstat", changed_fstat)

    with pytest.raises(UnsafePathError, match="identity changed"):
        _macos_rename_no_replace(source, destination)
    assert not called


def test_legacy_gateway_lock_rejects_broken_state_symlink(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    home.mkdir()
    try:
        (home / "state").symlink_to(tmp_path / "missing-state", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(UnsafePathError):
        LegacyGatewayLock(home).acquire()


def test_legacy_gateway_lock_does_not_follow_implicit_canonical_state_symlink(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    external = tmp_path / "external-state"
    home.mkdir()
    external.mkdir()
    try:
        (home / "state").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(UnsafePathError):
        LegacyGatewayLock(home).acquire()
    assert not (external / "gateway.pid.lock").exists()


def test_legacy_gateway_lock_creates_and_keeps_absent_lock_in_existing_state(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    state = home / "state"
    state.mkdir(parents=True)
    lock_path = state / "gateway.pid.lock"
    assert not lock_path.exists()

    with LegacyGatewayLock(home):
        assert lock_path.is_file()
        context = multiprocessing.get_context("spawn" if sys.platform == "win32" else "fork")
        queue = context.Queue()
        process = context.Process(
            target=_contend_for_gateway,
            args=(str(state), queue),
        )
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        assert queue.get(timeout=1) == "busy"

    # Persistent identity prevents a successor from locking an unlinked inode
    # while a third process creates a new lock path.
    assert lock_path.is_file()


def test_legacy_gateway_lock_does_not_treat_another_thread_as_reentrant(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    (home / "state").mkdir(parents=True)
    result: list[str] = []

    def contend() -> None:
        from opensquilla.recovery.errors import LegacyGatewayRunningError

        try:
            with LegacyGatewayLock(home, timeout=0.05):
                result.append("acquired")
        except LegacyGatewayRunningError:
            result.append("busy")

    with LegacyGatewayLock(home):
        thread = threading.Thread(target=contend)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert result == ["busy"]


def test_legacy_gateway_lock_never_creates_a_missing_state_directory(tmp_path: Path) -> None:
    home = tmp_path / "profile"
    home.mkdir()

    with LegacyGatewayLock(home):
        pass

    assert not (home / "state").exists()


def test_legacy_gateway_lock_covers_external_effective_state(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    external_state = tmp_path / "external-state"
    home.mkdir()
    external_state.mkdir()
    (home / "config.toml").write_text(
        f'state_dir = "{external_state}"\n',
        encoding="utf-8",
    )

    with LegacyGatewayLock(home):
        assert (external_state / "gateway.pid.lock").is_file()
        context = multiprocessing.get_context("spawn" if sys.platform == "win32" else "fork")
        queue = context.Queue()
        process = context.Process(
            target=_contend_for_gateway,
            args=(str(external_state), queue),
        )
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        assert queue.get(timeout=1) == "busy"


def test_multi_root_legacy_acquisition_is_sorted_and_releases_partial_claims(
    tmp_path: Path,
) -> None:
    from opensquilla.gateway.pidlock import GatewayPidLock
    from opensquilla.recovery.errors import LegacyGatewayRunningError

    home = tmp_path / "profile"
    canonical_state = home / "state"
    external_state = tmp_path / "external-state"
    canonical_state.mkdir(parents=True)
    external_state.mkdir()
    (home / "config.toml").write_text(
        f'state_dir = "{external_state}"\n',
        encoding="utf-8",
    )
    probe = LegacyGatewayLock(home)
    assert list(probe.state_roots) == sorted(
        probe.state_roots,
        key=lambda path: os.path.normcase(os.path.normpath(str(path.resolve()))),
    )

    blocking_gateway = GatewayPidLock(probe.state_roots[-1])
    blocking_gateway.acquire()
    try:
        with pytest.raises(LegacyGatewayRunningError):
            probe.acquire()
    finally:
        blocking_gateway.release()

    # Failure on the later root must have released the earlier root.
    successor = GatewayPidLock(probe.state_roots[0])
    successor.acquire()
    successor.release()


def test_import_source_lock_probe_does_not_create_source_authority_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "state").mkdir(parents=True)
    (target / "state").mkdir(parents=True)

    with acquire_legacy_gateway_locks(
        source,
        target,
        read_only_homes=(source,),
    ):
        assert not (source / "state" / "gateway.pid.lock").exists()
        assert (target / "state" / "gateway.pid.lock").is_file()


def test_import_existing_source_lock_probe_preserves_bytes_and_mode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_state = source / "state"
    (source_state).mkdir(parents=True)
    (target / "state").mkdir(parents=True)
    source_lock = source_state / "gateway.pid.lock"
    source_lock.write_bytes(b"synthetic-existing-lock\n")
    os.chmod(source_lock, 0o644)
    bytes_before = source_lock.read_bytes()
    mode_before = stat.S_IMODE(source_lock.stat().st_mode)

    with acquire_legacy_gateway_locks(
        source,
        target,
        read_only_homes=(source,),
    ):
        assert source_lock.read_bytes() == bytes_before
        assert stat.S_IMODE(source_lock.stat().st_mode) == mode_before

    assert source_lock.read_bytes() == bytes_before
    assert stat.S_IMODE(source_lock.stat().st_mode) == mode_before


def test_windows_legacy_lock_handle_allows_share_delete_for_profile_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opensquilla.recovery.locking as locking_module

    create_calls: list[tuple[object, ...]] = []
    converted: list[tuple[int, int]] = []

    class FakeCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args: object) -> int:
            create_calls.append(args)
            return 101

    kernel32 = SimpleNamespace(
        CreateFileW=FakeCreateFile(),
        CloseHandle=lambda _handle: 1,
    )
    monkeypatch.setattr(
        locking_module.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: kernel32,
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(
            open_osfhandle=lambda handle, flags: converted.append((handle, flags)) or 77,
        ),
    )

    fd = locking_module._windows_open_legacy_lock_file(
        Path("C:/synthetic/state/gateway.pid.lock"),
        create_if_missing=True,
    )

    assert fd == 77
    assert len(create_calls) == 1
    _path, _access, share_mode, _security, creation, open_flags, _template = create_calls[0]
    assert share_mode == 0x00000001 | 0x00000002 | 0x00000004
    assert creation == 4  # OPEN_ALWAYS
    assert int(open_flags) & 0x00200000  # FILE_FLAG_OPEN_REPARSE_POINT
    assert converted and converted[0][0] == 101


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows share-delete semantics")
def test_windows_real_legacy_lock_survives_profile_move_and_rebind(tmp_path: Path) -> None:
    import opensquilla.recovery.locking as locking_module

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "state").mkdir(parents=True)

    with LegacyGatewayLock(source):
        native_move_no_replace(source, destination)
        locking_module.rebind_legacy_gateway_lock(
            source / "state",
            destination / "state",
        )
        with LegacyGatewayLock(destination):
            context = multiprocessing.get_context("spawn")
            queue = context.Queue()
            process = context.Process(
                target=_contend_for_gateway,
                args=(str(destination / "state"), queue),
            )
            process.start()
            process.join(timeout=15)
            assert process.exitcode == 0
            assert queue.get(timeout=2) == "busy"


def test_moved_legacy_lock_can_be_rebound_without_dropping_exclusion(
    tmp_path: Path,
) -> None:
    import opensquilla.recovery.locking as locking_module

    staging = tmp_path / "staging"
    target = tmp_path / "target"
    (staging / "state").mkdir(parents=True)

    with LegacyGatewayLock(staging):
        staging.rename(target)
        locking_module.rebind_legacy_gateway_lock(
            staging / "state",
            target / "state",
        )
        with LegacyGatewayLock(target):
            context = multiprocessing.get_context(
                "spawn" if sys.platform == "win32" else "fork"
            )
            queue = context.Queue()
            process = context.Process(
                target=_contend_for_gateway,
                args=(str(target / "state"), queue),
            )
            process.start()
            process.join(timeout=10)
            assert process.exitcode == 0
            assert queue.get(timeout=1) == "busy"


def test_moved_legacy_lock_rebind_rejects_tampered_destination_state(
    tmp_path: Path,
) -> None:
    import opensquilla.recovery.locking as locking_module

    staging = tmp_path / "staging"
    target = tmp_path / "target"
    (staging / "state").mkdir(parents=True)

    with LegacyGatewayLock(staging):
        staging.rename(target)
        original_state = target / "state"
        parked_state = target / "parked-state"
        original_state.rename(parked_state)
        original_state.mkdir()
        (parked_state / "gateway.pid.lock").rename(
            original_state / "gateway.pid.lock"
        )
        registry_before = dict(locking_module._PROCESS_LEGACY_LOCKS)

        with pytest.raises(UnsafePathError, match="directory identity"):
            locking_module.rebind_legacy_gateway_lock(
                staging / "state",
                target / "state",
            )
        assert locking_module._PROCESS_LEGACY_LOCKS == registry_before


def test_rebound_target_keeps_displaced_backup_lock_registered_until_release(
    tmp_path: Path,
) -> None:
    import opensquilla.recovery.locking as locking_module

    staging = tmp_path / "staging"
    target = tmp_path / "target"
    backup = tmp_path / "backup"
    (staging / "state").mkdir(parents=True)
    (target / "state").mkdir(parents=True)
    target_key = locking_module._normalized_path(target / "state" / "gateway.pid.lock")

    with LegacyGatewayLock(target):
        displaced = locking_module._PROCESS_LEGACY_LOCKS[target_key]
        with LegacyGatewayLock(staging):
            target.rename(backup)
            staging.rename(target)
            locking_module.rebind_legacy_gateway_lock(
                staging / "state",
                target / "state",
            )

            assert displaced in locking_module._PROCESS_LEGACY_LOCKS.values()


def test_windows_nt_create_relative_binds_child_name_to_parent_handle() -> None:
    import opensquilla.recovery.locking as locking_module

    calls: list[tuple[object, ...]] = []

    class FakeNtCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args: object) -> int:
            calls.append(args)
            handle_out = args[0]
            handle_out._obj.value = 202  # type: ignore[attr-defined]
            return 0

    handle = locking_module._windows_nt_create_relative(
        FakeNtCreateFile(),
        parent_handle=101,
        name="profile-locks",
        desired_access=0x1234,
        file_attributes=0x10,
        share_access=0x03,
        create_disposition=3,
        create_options=0x00200021,
    )

    assert handle == 202
    assert len(calls) == 1
    (
        _handle_out,
        desired_access,
        object_attributes_pointer,
        _io_status,
        _allocation_size,
        file_attributes,
        share_access,
        create_disposition,
        create_options,
        _ea_buffer,
        _ea_length,
    ) = calls[0]
    object_attributes = object_attributes_pointer._obj  # type: ignore[attr-defined]
    unicode_name = object_attributes.object_name.contents
    assert object_attributes.root_directory == 101
    assert ctypes.wstring_at(unicode_name.buffer, unicode_name.length // 2) == "profile-locks"
    assert desired_access == 0x1234
    assert file_attributes == 0x10
    assert share_access == 0x03
    assert create_disposition == 3
    assert int(create_options) & 0x00200000  # FILE_OPEN_REPARSE_POINT


def test_windows_profile_lock_native_chain_pins_every_app_owned_component(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import opensquilla.recovery.locking as locking_module

    root = tmp_path / "user-state"
    path = root / "OpenSquilla" / "profile-locks" / "synthetic.lock"
    paths_by_handle: dict[int, Path] = {}
    create_calls: list[tuple[object, ...]] = []
    relative_calls: list[tuple[int, str, int, int]] = []
    closed: list[int] = []

    class FakeCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args: object) -> int:
            create_calls.append(args)
            paths_by_handle[10] = root
            return 10

    class FakeNtCreateFile:
        argtypes = None
        restype = None

        def __call__(self, *args: object) -> int:
            handle_out = args[0]
            object_attributes = args[2]._obj  # type: ignore[attr-defined]
            unicode_name = object_attributes.object_name.contents
            name = ctypes.wstring_at(unicode_name.buffer, unicode_name.length // 2)
            parent_handle = int(object_attributes.root_directory)
            share_access = int(args[6])
            create_options = int(args[8])
            candidate = paths_by_handle[parent_handle] / name
            if create_options & 0x00000001:  # FILE_DIRECTORY_FILE
                candidate.mkdir()
            else:
                candidate.touch()
            handle = 10 + len(paths_by_handle)
            paths_by_handle[handle] = candidate
            handle_out._obj.value = handle  # type: ignore[attr-defined]
            relative_calls.append((parent_handle, name, share_access, create_options))
            return 0

    class FakeGetInformation:
        argtypes = None
        restype = None

        def __call__(self, handle: int, info_class: int, output: object, _size: int) -> int:
            value = paths_by_handle[int(handle)].lstat()
            if info_class == 9:
                info = ctypes.cast(
                    output,
                    ctypes.POINTER(locking_module._WindowsFileAttributeTagInfo),
                ).contents
                info.file_attributes = 0x10 if stat.S_ISDIR(value.st_mode) else 0x80
                return 1
            assert info_class == 18
            info = ctypes.cast(
                output,
                ctypes.POINTER(locking_module._WindowsFileIdInfo),
            ).contents
            info.volume_serial_number = value.st_dev
            identifier = int(value.st_ino).to_bytes(16, "little")
            for index, byte in enumerate(identifier):
                info.file_id.identifier[index] = byte
            return 1

    class FakeCloseHandle:
        argtypes = None
        restype = None

        def __call__(self, handle: int) -> int:
            closed.append(int(handle))
            return 1

    create_file = FakeCreateFile()
    get_information = FakeGetInformation()
    close_handle = FakeCloseHandle()
    nt_create_file = FakeNtCreateFile()
    kernel32 = SimpleNamespace(
        CreateFileW=create_file,
        GetFileInformationByHandleEx=get_information,
        CloseHandle=close_handle,
    )
    ntdll = SimpleNamespace(NtCreateFile=nt_create_file)
    monkeypatch.setattr(
        locking_module.ctypes,
        "WinDLL",
        lambda name, **_kwargs: kernel32 if name == "kernel32" else ntdll,
        raising=False,
    )
    converted: list[tuple[int, int]] = []

    def open_osfhandle(handle: int, flags: int) -> int:
        converted.append((handle, flags))
        return os.open(paths_by_handle[handle], os.O_RDWR)

    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(open_osfhandle=open_osfhandle),
    )

    fd = locking_module._windows_open_profile_lock_file(path, root)
    try:
        assert os.read(fd, 1) == b"\0"
    finally:
        os.close(fd)

    assert len(create_calls) == 1
    assert create_calls[0][2] == 0x00000001 | 0x00000002
    assert int(create_calls[0][5]) & 0x00200000
    assert [(parent, name) for parent, name, _share, _options in relative_calls] == [
        (10, "OpenSquilla"),
        (11, "profile-locks"),
        (12, "synthetic.lock"),
    ]
    assert all(share == 0x00000001 | 0x00000002 for _, _, share, _ in relative_calls)
    assert all(options & 0x00200000 for _, _, _, options in relative_calls)
    assert converted and converted[0][0] == 13
    assert closed == [12, 11, 10]


def test_windows_profile_lock_preparation_uses_native_handle_relative_opener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import opensquilla.recovery.locking as locking_module

    root = tmp_path / "user-state"
    path = root / "OpenSquilla" / "profile-locks" / "synthetic.lock"
    backing = tmp_path / "backing.lock"
    backing.write_bytes(b"\0")
    backing_fd = os.open(backing, os.O_RDWR)
    calls: list[tuple[Path, Path]] = []

    def native_open(candidate: Path, candidate_root: Path) -> int:
        calls.append((candidate, candidate_root))
        return backing_fd

    monkeypatch.setattr(
        locking_module,
        "_windows_open_profile_lock_file",
        native_open,
        raising=False,
    )

    def reject_path_open(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("Windows profile lock leaf must not be opened by pathname")

    monkeypatch.setattr(locking_module.os, "open", reject_path_open)

    fd = locking_module._prepare_windows_lock_file(path, root)
    try:
        assert fd == backing_fd
        assert calls == [(path, root)]
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows handles")
def test_windows_profile_lock_real_native_chain_and_contention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_state = tmp_path / "user-state"
    home = tmp_path / "profile"
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(user_state))

    with ProfileOperationLock(home):
        lock_path = profile_lock_path(home)
        assert lock_path.is_file()
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        process = context.Process(
            target=_contend_for_lock,
            args=(str(home), str(user_state), queue),
        )
        process.start()
        process.join(timeout=15)
        assert process.exitcode == 0
        assert queue.get(timeout=2) == "busy"


def test_import_source_does_not_inherit_target_process_state_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    external_target_state = tmp_path / "active-target-state"
    (source / "state").mkdir(parents=True)
    target.mkdir()
    external_target_state.mkdir()
    monkeypatch.setenv(
        "OPENSQUILLA_GATEWAY_STATE_DIR",
        str(external_target_state),
    )

    with acquire_legacy_gateway_locks(
        source,
        target,
        read_only_homes=(source,),
    ):
        assert not (source / "state" / "gateway.pid.lock").exists()
        assert (external_target_state / "gateway.pid.lock").is_file()


def test_windows_native_move_uses_extended_length_paths() -> None:
    deep = "C:\\Users\\synthetic\\" + "nested\\" * 50 + "workspace"
    converted = _windows_extended_path(deep)
    assert converted.startswith("\\\\?\\C:\\")
    assert len(converted) > 260
    assert _windows_extended_path(r"\\server\share\workspace").startswith(
        "\\\\?\\UNC\\server\\share\\"
    )


def test_windows_no_replace_pins_source_parent_source_and_destination_parent_handles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination_parent = tmp_path / "destination-parent"
    source.mkdir()
    destination_parent.mkdir()
    destination = destination_parent / "destination"
    source_parent_stat = source.parent.lstat()
    source_stat = source.lstat()
    destination_parent_stat = destination_parent.lstat()
    created: list[tuple[str, int]] = []
    closed: list[int] = []
    rename_calls: list[tuple[int, int, int, int, int]] = []
    mutation_events: list[str] = []

    class FakeCall:
        argtypes = None
        restype = None

        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def create_file(path, _access, share_mode, *_args):
        created.append((path, int(share_mode)))
        return (101, 202, 303)[len(created) - 1]

    def get_information(handle, info_class, buffer, _size):
        if info_class == 9:  # FileAttributeTagInfo
            ctypes.memmove(buffer, struct.pack("<II", 0x10, 0), 8)
        elif info_class == 18:  # FileIdInfo
            value = {
                101: source_parent_stat,
                202: source_stat,
                303: destination_parent_stat,
            }[handle]
            payload = struct.pack("<Q", value.st_dev) + int(value.st_ino).to_bytes(
                16, "little"
            )
            ctypes.memmove(buffer, payload, len(payload))
        else:  # pragma: no cover - contract assertion
            raise AssertionError(f"unexpected info class {info_class}")
        return 1

    class RenameHeader(ctypes.Structure):
        _fields_ = [
            ("flags", ctypes.c_uint32),
            ("root_directory", ctypes.c_void_p),
            ("file_name_length", ctypes.c_uint32),
        ]

    def set_information(handle, info_class, buffer, size):
        mutation_events.append("rename")
        header = ctypes.cast(buffer, ctypes.POINTER(RenameHeader)).contents
        rename_calls.append(
            (
                handle,
                info_class,
                int(header.flags),
                int(header.root_directory),
                int(header.file_name_length),
            )
        )
        assert size >= ctypes.sizeof(RenameHeader)
        return 1

    kernel32 = SimpleNamespace(
        CreateFileW=FakeCall(create_file),
        GetFileInformationByHandleEx=FakeCall(get_information),
        SetFileInformationByHandle=FakeCall(set_information),
        CloseHandle=FakeCall(lambda handle: closed.append(handle) or 1),
    )
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: kernel32,
        raising=False,
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)

    _windows_move_no_replace(
        source,
        destination,
        _before_mutation=lambda: mutation_events.append("failpoint"),
    )

    assert created == [
        (_windows_extended_path(source.parent), 0x00000001 | 0x00000002),
        (_windows_extended_path(source), 0x00000001 | 0x00000002),
        (_windows_extended_path(destination_parent), 0x00000001 | 0x00000002),
    ]
    assert rename_calls == [
        (202, 3, 0, 303, len(destination.name.encode("utf-16-le")))
    ]
    assert mutation_events == ["failpoint", "rename"]
    assert closed == [303, 202, 101]


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows sharing semantics")
def test_windows_no_replace_pins_both_parents_during_real_mutation_window(
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "source-parent"
    destination_parent = tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    source.mkdir()
    (source / "value.txt").write_text("preserved\n", encoding="utf-8")
    destination = destination_parent / "destination"
    renamed_source_parent = tmp_path / "renamed-source-parent"
    renamed_destination_parent = tmp_path / "renamed-destination-parent"
    blocked: list[Path] = []

    def contend_for_both_parents() -> None:
        for current, renamed in (
            (source_parent, renamed_source_parent),
            (destination_parent, renamed_destination_parent),
        ):
            try:
                current.rename(renamed)
            except OSError:
                blocked.append(current)

    _windows_move_no_replace(
        source,
        destination,
        _before_mutation=contend_for_both_parents,
    )

    assert blocked == [source_parent, destination_parent]
    assert source_parent.is_dir()
    assert destination_parent.is_dir()
    assert not renamed_source_parent.exists()
    assert not renamed_destination_parent.exists()
    assert not source.exists()
    assert (destination / "value.txt").read_text(encoding="utf-8") == "preserved\n"
