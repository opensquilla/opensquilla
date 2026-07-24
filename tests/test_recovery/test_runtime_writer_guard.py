from __future__ import annotations

import json
import multiprocessing
import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner


def _hold_runtime_writer(
    home: str,
    user_state: str,
    profile_kind: str,
    ready: Any,
    release: Any,
) -> None:
    """Hold the same universal writer lease used by gateway/agent runtimes."""

    os.environ["OPENSQUILLA_STATE_DIR"] = home
    os.environ["OPENSQUILLA_USER_STATE_DIR"] = user_state
    os.environ["OPENSQUILLA_TEST_PROFILE_LOCK_ROOT"] = "1"
    if profile_kind:
        os.environ["OPENSQUILLA_PROFILE_KIND"] = profile_kind
        os.environ["OPENSQUILLA_DESKTOP"] = "1"
    else:
        os.environ.pop("OPENSQUILLA_PROFILE_KIND", None)
        os.environ.pop("OPENSQUILLA_DESKTOP", None)

    from opensquilla.recovery import guarded_desktop_profile

    try:
        with guarded_desktop_profile(Path(home)):
            ready.put("locked")
            if not release.wait(timeout=15):
                raise TimeoutError("test did not release the runtime writer")
    except BaseException as exc:
        ready.put(f"error:{type(exc).__name__}:{exc}")
        raise


def _profile(home: Path) -> None:
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "SOUL.md").write_text("synthetic runtime profile\n", encoding="utf-8")
    (home / "state").mkdir()
    (home / "config.toml").write_text(
        'state_dir = "state"\nworkspace_dir = "workspace"\n',
        encoding="utf-8",
    )


def _isolate_profile_locks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(tmp_path / "user-state"))
    monkeypatch.setenv("OPENSQUILLA_TEST_PROFILE_LOCK_ROOT", "1")


def test_unknown_desktop_layout_blocks_agent_before_profile_seed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile"
    unknown = home / "unknown-layout"
    unknown.mkdir(parents=True)
    identity = unknown / "USER.md"
    identity.write_text("synthetic preserved identity\n", encoding="utf-8")
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(tmp_path / "user-state"))
    monkeypatch.setenv("OPENSQUILLA_TEST_PROFILE_LOCK_ROOT", "1")
    monkeypatch.setenv("OPENSQUILLA_PROFILE_KIND", "desktop-primary")
    monkeypatch.setenv("OPENSQUILLA_DESKTOP", "1")

    from opensquilla.cli import main as cli_main
    from opensquilla.recovery import RecoveryRequiredError

    agent_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli_main,
        "run_agent_command",
        lambda **kwargs: agent_calls.append(dict(kwargs)),
    )

    result = CliRunner().invoke(
        cli_main.app,
        ["agent", "--message", "must not reach a provider", "--json"],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, RecoveryRequiredError)
    assert result.exception.report.stable_code == "unknown_layout"
    assert agent_calls == []
    assert identity.read_text(encoding="utf-8") == "synthetic preserved identity\n"
    assert not (home / "workspace").exists()
    assert not (home / "state").exists()


@pytest.mark.parametrize(
    "profile_kind",
    ["desktop-primary", ""],
    ids=["desktop-primary", "ordinary-cli"],
)
def test_runtime_writer_lock_keeps_read_only_cli_available_and_rejects_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile_kind: str,
) -> None:
    """A live writer excludes writers, never read-only gateway clients."""

    home = tmp_path / "profile"
    user_state = tmp_path / "user-state"
    _profile(home)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.setenv("OPENSQUILLA_USER_STATE_DIR", str(user_state))
    monkeypatch.setenv("OPENSQUILLA_TEST_PROFILE_LOCK_ROOT", "1")
    if profile_kind:
        monkeypatch.setenv("OPENSQUILLA_PROFILE_KIND", profile_kind)
        monkeypatch.setenv("OPENSQUILLA_DESKTOP", "1")
    else:
        monkeypatch.delenv("OPENSQUILLA_PROFILE_KIND", raising=False)
        monkeypatch.delenv("OPENSQUILLA_DESKTOP", raising=False)

    context = multiprocessing.get_context("spawn" if sys.platform == "win32" else "fork")
    ready = context.Queue()
    release = context.Event()
    writer = context.Process(
        target=_hold_runtime_writer,
        args=(str(home), str(user_state), profile_kind, ready, release),
    )
    writer.start()
    assert ready.get(timeout=10) == "locked"

    try:
        from opensquilla.cli import gateway_cmd, models_cmd
        from opensquilla.cli import main as cli_main
        from opensquilla.recovery import ProfileLockBusyError

        status_calls: list[dict[str, object]] = []

        def fake_status_gateway(**kwargs: object) -> None:
            status_calls.append(dict(kwargs))
            typer.echo(json.dumps({"status": "synthetic-running"}))

        model_calls: list[dict[str, object]] = []

        def fake_run_gateway_sync(_callback: object, **kwargs: object) -> dict[str, object]:
            model_calls.append(dict(kwargs))
            return {
                "models": [
                    {
                        "id": "synthetic/model",
                        "provider": "synthetic",
                        "capabilities": ["text"],
                    }
                ],
                "errors": [],
            }

        agent_calls: list[dict[str, object]] = []

        def fake_run_agent_command(**kwargs: object) -> None:
            agent_calls.append(dict(kwargs))

        monkeypatch.setattr(gateway_cmd, "status_gateway", fake_status_gateway)
        monkeypatch.setattr(models_cmd, "run_gateway_sync", fake_run_gateway_sync)
        monkeypatch.setattr(cli_main, "run_agent_command", fake_run_agent_command)
        runner = CliRunner()

        status = runner.invoke(cli_main.app, ["gateway", "status", "--json"])
        assert status.exit_code == 0, status.stdout
        assert json.loads(status.stdout) == {"status": "synthetic-running"}
        assert len(status_calls) == 1

        models = runner.invoke(cli_main.app, ["models", "list", "--json"])
        assert models.exit_code == 0, models.stdout
        assert json.loads(models.stdout) == [
            {
                "id": "synthetic/model",
                "provider": "synthetic",
                "capabilities": ["text"],
            }
        ]
        assert len(model_calls) == 1

        competing_agent = runner.invoke(
            cli_main.app,
            ["agent", "--message", "must not reach a provider", "--json"],
        )
        assert competing_agent.exit_code == 1
        assert isinstance(competing_agent.exception, ProfileLockBusyError)
        assert agent_calls == []
    finally:
        release.set()
        writer.join(timeout=10)
        if writer.is_alive():
            writer.terminate()
            writer.join(timeout=5)

    assert writer.exitcode == 0


def test_different_state_dirs_acquire_independent_profile_locks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two profile locks with different OPENSQUILLA_STATE_DIR do not conflict."""

    from opensquilla.recovery import guarded_desktop_profile
    from opensquilla.recovery.locking import profile_lock_key, profile_lock_path

    _isolate_profile_locks(monkeypatch, tmp_path)
    profile_a = tmp_path / "profile-a"
    profile_b = tmp_path / "profile-b"
    profile_a.mkdir()
    profile_b.mkdir()

    assert profile_lock_key(profile_a) != profile_lock_key(profile_b)

    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(profile_a))
    with guarded_desktop_profile():
        monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(profile_b))
        with guarded_desktop_profile():
            pass

    assert profile_lock_path(profile_a).is_file()
    assert profile_lock_path(profile_b).is_file()
    assert profile_lock_path(profile_a) != profile_lock_path(profile_b)


def test_empty_state_dir_falls_back_to_default_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty OPENSQUILLA_STATE_DIR produces default config without error."""

    from opensquilla.gateway.config import GatewayConfig

    _isolate_profile_locks(monkeypatch, tmp_path)
    empty_profile = tmp_path / "empty"
    empty_profile.mkdir()
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(empty_profile))

    cfg = GatewayConfig.load()

    assert cfg.state_dir == str(empty_profile / "state")
    assert not (empty_profile / "config.toml").exists()


def test_same_state_dir_blocks_second_profile_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Same OPENSQUILLA_STATE_DIR blocks a second writer on another thread."""

    from opensquilla.recovery import ProfileLockBusyError, guarded_desktop_profile

    _isolate_profile_locks(monkeypatch, tmp_path)
    profile = tmp_path / "shared"
    profile.mkdir()
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(profile))
    errors: list[BaseException] = []

    def try_second_lock() -> None:
        try:
            with guarded_desktop_profile():
                pass
        except BaseException as exc:
            errors.append(exc)

    with guarded_desktop_profile():
        second = threading.Thread(target=try_second_lock)
        second.start()
        second.join(timeout=5)

    assert not second.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ProfileLockBusyError)
