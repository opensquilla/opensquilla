"""Tests for the first-run `opensquilla init` wizard."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest import mock

import pytest

from opensquilla.cli.init_cmd import (
    _default_model_for_provider,
    _env_key_name_for_provider,
    persist_profile,
    run_init,
)
from opensquilla.provider.registry import UnknownProviderError, get_provider_spec


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
    assert (tmp_path / "default" / "config.toml").is_file()


# ---------------------------------------------------------------------------
# `persist_profile` regression suite for issue #215 / init-all audit.
#
# Before the fix, `persist_profile` only wrote `provider` + `model` to
# config.toml and derived the env-var name from
# `f"{provider.upper()}_API_KEY"`. The fleet init command therefore
# landed profiles with `api_key_env = ""` and no `base_url`, and the
# wrong env-var name for the four MiniMax variants. The following
# tests lock the corrected behaviour.
# ---------------------------------------------------------------------------


def test_persist_profile_writes_all_four_llm_fields(tmp_path: Path) -> None:
    """Every provider that requires a key + base URL must have both persisted.

    The runtime adapter reads `api_key_env` and `base_url` from
    config.toml at provider_ready time; leaving them blank was
    silent because `provider_ready` does not require the env-var
    to be present. The audit in #215 caught this in the field.
    """
    persist_profile(
        tmp_path,
        provider="minimax_openai",
        api_key="sk-test",
    )
    cfg = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    llm = cfg["llm"]
    # Authoritative lookups — never hard-code the env-var name in
    # this test, so a future spec change still passes.
    spec = get_provider_spec("minimax_openai")
    assert llm["provider"] == "minimax_openai"
    assert llm["model"] == "MiniMax-M3"
    assert llm["api_key_env"] == spec.env_key
    assert llm["base_url"] == "https://api.minimaxi.com/v1"


def test_persist_profile_uses_canonical_env_key_not_caller_label(tmp_path: Path) -> None:
    """A `api_key_env` label passed by the caller is a label, not a contract.

    The caller is just telling us how they want to *pass* the key
    in (env-var name, paste, or stdin). The persisted env-var name
    in config.toml must always come from the spec, otherwise a
    fleet init that used the wrong label would silently persist
    the wrong lookup name and the gateway would never find the key.
    """
    persist_profile(
        tmp_path,
        provider="minimax_cn",
        api_key_env="SOME_WRONG_LABEL",
    )
    cfg = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    spec = get_provider_spec("minimax_cn")
    # Caller's label is dropped; spec's canonical name is used.
    assert cfg["llm"]["api_key_env"] == spec.env_key
    assert cfg["llm"]["base_url"] == "https://api.minimaxi.com/anthropic"


def test_persist_profile_writes_key_to_dotenv_under_spec_env_key(tmp_path: Path) -> None:
    """`.env` file must use the spec's env-var name, not the caller's label."""
    persist_profile(
        tmp_path,
        provider="minimax_cn",
        api_key="sk-actual-token",
    )
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    spec = get_provider_spec("minimax_cn")
    assert f"{spec.env_key}=sk-actual-token" in env


def test_persist_profile_does_not_write_env_for_local_provider(tmp_path: Path) -> None:
    """Ollama-style providers have no env_key; do not invent a fake one.

    `requires_api_key()` is False for ollama, so we should not write
    `api_key_env` to config.toml. base_url still goes in.
    """
    persist_profile(
        tmp_path,
        provider="ollama",
        model="qwen2.5-coder:7b",
    )
    cfg = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    spec = get_provider_spec("ollama")
    assert cfg["llm"]["provider"] == "ollama"
    # ollama has no env_key, so the field is omitted from config.toml.
    assert cfg["llm"].get("api_key_env", "") == spec.env_key  # empty
    assert cfg["llm"]["base_url"] == spec.default_base_url


def test_persist_profile_rejects_unknown_provider(tmp_path: Path) -> None:
    """Unknown provider id must raise, not silently write a bad config."""
    with pytest.raises(UnknownProviderError):
        persist_profile(
            tmp_path,
            provider="totally-made-up-provider",
            api_key="x",
        )


def test_env_key_name_for_provider_uses_spec() -> None:
    """`_env_key_name_for_provider` must consult the registry, not guess."""
    for pid in ("minimax", "minimax_openai", "minimax_cn", "minimax_global",
                "openrouter", "openai", "anthropic", "ollama"):
        spec = get_provider_spec(pid)
        assert _env_key_name_for_provider(pid) == spec.env_key
    assert _env_key_name_for_provider("custom") == "OPENSQUILLA_LLM_API_KEY"


class _FakeAsk:
    """Minimal stand-in for a questionary return value (truthy, equal to answer)."""

    def __init__(self, value: str) -> None:
        self._value = value

    def ask(self) -> str:
        return self._value
