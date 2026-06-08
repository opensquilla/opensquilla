"""Tests for the first-run `opensquilla init` wizard."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from opensquilla.cli.init_cmd import _default_model_for_provider, run_init


def test_init_uses_direct_deepseek_model_default() -> None:
    assert _default_model_for_provider("deepseek") == "deepseek-v4-flash"


def test_init_keeps_openrouter_model_default() -> None:
    assert _default_model_for_provider("openrouter") == "deepseek/deepseek-v4-pro"


def test_init_uses_MiniMax_M3_default_for_minimax_provider() -> None:
    assert _default_model_for_provider("minimax") == "minimax/MiniMax-M3"


def test_init_default_model_is_case_insensitive() -> None:
    # Wizard choices are emitted in lowercase, but the helper guards against
    # upper/Title-case input from --profile users and future programmatic callers.
    assert _default_model_for_provider("MiniMax") == "minimax/MiniMax-M3"
    assert _default_model_for_provider("MINIMAX") == "minimax/MiniMax-M3"


def test_init_wizard_writes_MiniMax_M3_when_user_picks_minimax(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`init` exposes `minimax` and seeds `model = "minimax/MiniMax-M3"`."""
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "default")
    # Clean any pre-existing profile env so load_env() (run via default_opensquilla_home)
    # doesn't carry over state from a parent test, and so default_opensquilla_home
    # resolves to $OPENSQUILLA_HOME/$OPENSQUILLA_PROFILE (not a leaked
    # OPENSQUILLA_STATE_DIR from the host test environment).
    for key in (
        "OPENSQUILLA_STATE_DIR",
        "OPENSQUILLA_CONFIG_PATH",
        "MINIMAX_API_KEY",
        "OPENSQUILLA_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    answers = iter(["minimax", "test-minimax-key"])
    default_model: list[str] = []

    def fake_select(_prompt: str, choices: list[str], default: str = "") -> object:
        try:
            return _FakeAsk(next(answers))
        except StopIteration:
            raise AssertionError("questionary.select invoked more than expected")

    def fake_password(_prompt: str) -> object:
        try:
            return _FakeAsk(next(answers))
        except StopIteration:
            raise AssertionError("questionary.password invoked more than expected")

    def fake_text(_prompt: str, default: str = "") -> object:
        default_model.append(default)
        # Simulate the user pressing Enter to accept the pre-filled default.
        return _FakeAsk(default)

    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.select", fake_select)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.password", fake_password)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.text", fake_text)

    run_init()

    # default_opensquilla_home() resolves to $OPENSQUILLA_HOME/$OPENSQUILLA_PROFILE,
    # so the wizard writes to <tmp_path>/default/.
    home = tmp_path / "default"
    env_path = home / ".env"
    config_path = home / "config.toml"
    assert env_path.exists()
    assert config_path.exists()

    env_text = env_path.read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY=test-minimax-key" in env_text

    config_text = config_path.read_text(encoding="utf-8")
    assert 'provider = "minimax"' in config_text
    assert 'model = "minimax/MiniMax-M3"' in config_text

    # The wizard must surface M3 as the *default* suggestion, not require the
    # user to type it.
    assert default_model == ["minimax/MiniMax-M3"]


def test_init_autostart_off_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without --autostart, run_init must not call the autostart dispatcher."""
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "default")
    for key in (
        "OPENSQUILLA_STATE_DIR",
        "OPENSQUILLA_CONFIG_PATH",
        "OPENROUTER_API_KEY",
        "MINIMAX_API_KEY",
        "OPENSQUILLA_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    answers = iter(["openrouter", "sk-test"])

    def fake_select(_prompt: str, choices: list[str], default: str = "") -> object:
        return _FakeAsk(next(answers))

    def fake_password(_prompt: str) -> object:
        return _FakeAsk(next(answers))

    def fake_text(_prompt: str, default: str = "") -> object:
        return _FakeAsk(default)

    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.select", fake_select)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.password", fake_password)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.text", fake_text)

    with mock.patch("opensquilla.cli.init_cmd.autostart") as autostart_mock:
        run_init()  # default: autostart_register=False

    autostart_mock.register_logon_task.assert_not_called()


def test_init_autostart_flag_invokes_dispatcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`run_init(autostart_register=True)` must dispatch to
    `autostart.register_logon_task` with the resolved profile home.
    """
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "coder")
    for key in (
        "OPENSQUILLA_STATE_DIR",
        "OPENSQUILLA_CONFIG_PATH",
        "OPENROUTER_API_KEY",
        "MINIMAX_API_KEY",
        "OPENSQUILLA_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    answers = iter(["openrouter", "sk-test"])

    def fake_select(_prompt: str, choices: list[str], default: str = "") -> object:
        return _FakeAsk(next(answers))

    def fake_password(_prompt: str) -> object:
        return _FakeAsk(next(answers))

    def fake_text(_prompt: str, default: str = "") -> object:
        return _FakeAsk(default)

    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.select", fake_select)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.password", fake_password)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.text", fake_text)

    with mock.patch("opensquilla.cli.init_cmd.autostart") as autostart_mock:
        autostart_mock.register_logon_task.return_value.summary.return_value = (
            "Windows autostart registered for profile 'coder'"
        )
        run_init(autostart_register=True)

    autostart_mock.register_logon_task.assert_called_once()
    kwargs = autostart_mock.register_logon_task.call_args.kwargs
    assert kwargs["profile"] == "coder"
    # Home is the per-profile directory under OPENSQUILLA_HOME.
    assert kwargs["home"] == tmp_path / "coder"


def test_init_autostart_flag_swallows_dispatcher_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failure inside the autostart dispatcher must not abort the wizard;
    the user is shown a warning and the env / config files are still on
    disk.
    """
    from opensquilla.cli import autostart

    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "default")
    for key in (
        "OPENSQUILLA_STATE_DIR",
        "OPENSQUILLA_CONFIG_PATH",
        "OPENROUTER_API_KEY",
        "MINIMAX_API_KEY",
        "OPENSQUILLA_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    answers = iter(["openrouter", "sk-test"])

    def fake_select(_prompt: str, choices: list[str], default: str = "") -> object:
        return _FakeAsk(next(answers))

    def fake_password(_prompt: str) -> object:
        return _FakeAsk(next(answers))

    def fake_text(_prompt: str, default: str = "") -> object:
        return _FakeAsk(default)

    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.select", fake_select)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.password", fake_password)
    monkeypatch.setattr("opensquilla.cli.init_cmd.questionary.text", fake_text)

    with mock.patch(
        "opensquilla.cli.init_cmd.autostart.register_logon_task",
        side_effect=autostart.AutostartError("simulated failure"),
    ):
        # Must not raise — wizard must finish writing env / config despite the
        # autostart failure.
        run_init(autostart_register=True)

    assert (tmp_path / "default" / ".env").exists()
    assert (tmp_path / "default" / "config.toml").exists()


class _FakeAsk:
    """Minimal stand-in for a questionary return value (truthy, equal to answer)."""

    def __init__(self, value: str) -> None:
        self._value = value

    def ask(self) -> str:
        return self._value
