"""Tests for opensquilla profiles <subcommand> and the persist_profile
helper that backs it.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from opensquilla.cli import autostart
from opensquilla.cli.init_cmd import persist_profile
from opensquilla.cli.main import app
from opensquilla.cli.profiles_cmd import (
    ProfileTarget,
    _discover_profiles,
    profiles_app,
)

runner = CliRunner()


# --- persist_profile (refactored helper) -------------------------------------


def test_persist_profile_writes_env_and_config_with_api_key(
    tmp_path: Path,
) -> None:
    home = tmp_path / "coder"
    persist_profile(
        home,
        provider="openrouter",
        api_key="sk-or-v1-abc",
    )
    env_text = (home / ".env").read_text(encoding="utf-8")
    cfg = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert "OPENROUTER_API_KEY=sk-or-v1-abc" in env_text
    assert cfg["llm"]["provider"] == "openrouter"
    assert cfg["llm"]["model"] == "deepseek/deepseek-v4-pro"
    # state_dir is platform-dependent (Path uses os.sep); use os.sep
    # rather than a hard-coded slash so the test passes on Windows and
    # POSIX runners alike.
    assert cfg["state_dir"].endswith(f"coder{os.sep}state")
    assert (home / "state").is_dir()


def test_persist_profile_with_api_key_env_writes_no_value(tmp_path: Path) -> None:
    """`api_key_env` is the env-var name the gateway reads at runtime;
    nothing should be written into .env so the operator can keep the
    key out of the dotfiles.
    """
    home = tmp_path / "coder"
    persist_profile(
        home,
        provider="minimax",
        api_key_env="MINIMAX_API_KEY",
    )
    env_text = (home / ".env").read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY" not in env_text  # var name not the value
    cfg = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert cfg["llm"]["provider"] == "minimax"
    assert cfg["llm"]["model"] == "minimax/MiniMax-M3"


def test_persist_profile_rejects_both_or_neither_key(tmp_path: Path) -> None:
    home = tmp_path / "coder"
    with pytest.raises(ValueError, match="either api_key or api_key_env"):
        persist_profile(home, provider="openrouter", api_key="k", api_key_env="ENV")
    with pytest.raises(ValueError, match="either api_key or api_key_env"):
        persist_profile(home, provider="openrouter")


def test_persist_profile_preserves_unrelated_env_keys(tmp_path: Path) -> None:
    home = tmp_path / "coder"
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text(
        "OPENSQUILLA_LOG_LEVEL=info\nOPENROUTER_API_KEY=old\n",
        encoding="utf-8",
    )
    persist_profile(home, provider="openrouter", api_key="new")
    env_text = (home / ".env").read_text(encoding="utf-8")
    assert "OPENSQUILLA_LOG_LEVEL=info" in env_text
    assert "OPENROUTER_API_KEY=new" in env_text
    # The pre-existing entry for OPENROUTER_API_KEY must be replaced,
    # not duplicated. Use a regex-free substring check that works
    # regardless of how many times the value appears.
    assert env_text.count("OPENROUTER_API_KEY=") == 1
    assert "OPENROUTER_API_KEY=old" not in env_text


# --- _discover_profiles -------------------------------------------------------


def test_discover_profiles_returns_initialised_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))

    (tmp_path / "coder").mkdir()
    (tmp_path / "coder" / ".env").write_text("OPENROUTER_API_KEY=x\n")
    (tmp_path / "coder" / "config.toml").write_text(
        '[llm]\nprovider = "openrouter"\nmodel = "x"\n',
        encoding="utf-8",
    )
    (tmp_path / "default").mkdir()

    targets = _discover_profiles(tmp_path)
    by_name = {t.name: t for t in targets}
    assert by_name["coder"].initialised is True
    assert by_name["default"].initialised is False
    # No other sibling directories on the tmp_path should be picked up
    # — the discover function only enumerates profile-name-valid
    # subdirectories, so any non-profile directory the test happens
    # to create is filtered out.
    assert set(by_name) == {"coder", "default"}


# --- profiles_app integration via CliRunner ----------------------------------


def test_profiles_list_renders_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    (tmp_path / "coder").mkdir()
    (tmp_path / "default").mkdir()

    result = runner.invoke(app, ["profiles", "list"])
    assert result.exit_code == 0
    out = result.stdout
    assert "coder" in out
    assert "default" in out
    assert "uninitialised" in out  # neither profile has .env + config.toml


def test_profiles_init_all_requires_either_api_key_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    (tmp_path / "coder").mkdir()

    result = runner.invoke(
        app,
        [
            "profiles",
            "init-all",
            "--provider",
            "openrouter",
            "--profiles-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "Provide exactly one of --api-key or --api-key-env" in result.stdout


def test_profiles_init_all_writes_each_uninitialised_profile_and_skips_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    (tmp_path / "coder").mkdir()
    (tmp_path / "default").mkdir()
    # Pre-existing profile (already initialised) — must be left alone.
    pre = tmp_path / "pre"
    pre.mkdir()
    (pre / ".env").write_text("OPENROUTER_API_KEY=old\n", encoding="utf-8")
    (pre / "config.toml").write_text(
        '[llm]\nprovider = "openrouter"\nmodel = "old"\n',
        encoding="utf-8",
    )

    with mock.patch("opensquilla.cli.profiles_cmd.autostart") as autostart_mock:
        autostart_mock.register_logon_task.return_value.summary.return_value = (
            "Windows autostart registered for profile"
        )
        result = runner.invoke(
            app,
            [
                "profiles",
                "init-all",
                "--provider",
                "openrouter",
                "--api-key",
                "sk-or-v1-batch",
                "--no-autostart",
                "--profiles-root",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "coder" in out
    assert "default" in out

    coder_env = (tmp_path / "coder" / ".env").read_text(encoding="utf-8")
    default_env = (tmp_path / "default" / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-or-v1-batch" in coder_env
    assert "OPENROUTER_API_KEY=sk-or-v1-batch" in default_env

    pre_env = (pre / ".env").read_text(encoding="utf-8")
    pre_cfg = (pre / "config.toml").read_text(encoding="utf-8")
    assert pre_env == "OPENROUTER_API_KEY=old\n"
    assert "old" in pre_cfg

    # autostart_register is False on this invocation, so the dispatcher
    # must not be called.
    autostart_mock.register_logon_task.assert_not_called()


def test_profiles_init_all_invokes_autostart_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    (tmp_path / "coder").mkdir()
    (tmp_path / "default").mkdir()

    with mock.patch("opensquilla.cli.profiles_cmd.autostart") as autostart_mock:
        autostart_mock.register_logon_task.return_value.summary.return_value = (
            "registered"
        )
        result = runner.invoke(
            app,
            [
                "profiles",
                "init-all",
                "--provider",
                "openrouter",
                "--api-key-env",
                "OPENROUTER_API_KEY",
                "--profiles-root",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.stdout
    # Two profiles, two calls (one per profile).
    assert autostart_mock.register_logon_task.call_count == 2
    names = sorted(
        call.kwargs["profile"]
        for call in autostart_mock.register_logon_task.call_args_list
    )
    assert names == ["coder", "default"]


def test_profiles_init_all_continues_when_autostart_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure inside the autostart dispatcher for one profile must
    not stop the loop: the remaining profile is still initialised.
    """
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    (tmp_path / "coder").mkdir()
    (tmp_path / "default").mkdir()

    def side_effect(*, profile, home):
        if profile == "coder":
            raise autostart.AutostartError("simulated failure on coder")
        return mock.Mock(summary=lambda: f"registered {profile}")

    with mock.patch(
        "opensquilla.cli.profiles_cmd.autostart.register_logon_task",
        side_effect=side_effect,
    ):
        result = runner.invoke(
            app,
            [
                "profiles",
                "init-all",
                "--provider",
                "openrouter",
                "--api-key",
                "sk-or-v1-fallthrough",
                "--profiles-root",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.stdout
    # Both profiles still got .env + config.toml even though coder's
    # autostart call raised.
    assert (tmp_path / "coder" / ".env").exists()
    assert (tmp_path / "default" / ".env").exists()
    assert "autostart skipped" in result.stdout
