"""Tests for non-interactive onboarding flow halves."""

from __future__ import annotations

import types
from pathlib import Path


def test_wait_for_setup_start_flushes_visible_prompt_before_accepting_enter(monkeypatch):
    from opensquilla.onboarding import flow

    events: list[str] = []

    class _Console:
        class _File:
            def flush(self):
                events.append("flush")

        file = _File()

        def print(self, message: str):
            assert "Press Enter to start setup" in message
            events.append("print")

    monkeypatch.setattr(flow, "console", _Console())
    monkeypatch.setattr(flow, "_flush_stdin_typeahead", lambda: events.append("clear"))
    monkeypatch.setattr("builtins.input", lambda: events.append("input"))

    flow._wait_for_setup_start()

    assert events == ["print", "flush", "clear", "input"]


def test_flush_stdin_typeahead_uses_msvcrt_on_windows(monkeypatch):
    from opensquilla.onboarding import flow

    drained: list[str] = []
    fake_msvcrt = types.SimpleNamespace(
        kbhit=lambda: len(drained) < 2,
        getwch=lambda: drained.append("key"),
    )

    monkeypatch.setattr(flow.os, "name", "nt")
    monkeypatch.setitem(__import__("sys").modules, "msvcrt", fake_msvcrt)

    flow._flush_stdin_typeahead()

    assert drained == ["key", "key"]


def test_flush_stdin_typeahead_uses_termios_on_unix_tty(monkeypatch):
    from opensquilla.onboarding import flow

    calls: list[object] = []
    fake_stdin = types.SimpleNamespace(isatty=lambda: True)
    fake_termios = types.SimpleNamespace(
        TCIFLUSH=123,
        tcflush=lambda stream, selector: calls.extend([stream, selector]),
    )

    monkeypatch.setattr(flow.os, "name", "posix")
    monkeypatch.setattr(flow.sys, "stdin", fake_stdin)
    monkeypatch.setitem(__import__("sys").modules, "termios", fake_termios)

    flow._flush_stdin_typeahead()

    assert calls == [fake_stdin, 123]


def test_interactive_provider_choice_offers_only_verified_supported_providers():
    from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_choice

    captured: dict[str, list[str]] = {}

    class _Question:
        def ask(self) -> str:
            return "openrouter (OpenRouter)"

    class _Questionary:
        def select(self, _message: str, *, choices: list[str], default: str) -> _Question:
            captured["choices"] = choices
            captured["default"] = default
            return _Question()

    _ask_provider_choice(_Questionary(), OnboardOptions())

    assert captured["choices"][0] == "openrouter (OpenRouter)"
    assert captured["default"] == "openrouter (OpenRouter)"
    offered = {choice.split(" ")[0] for choice in captured["choices"]}
    assert offered == {
        "openrouter",
        "openai",
        "anthropic",
        "ollama",
        "deepseek",
        "gemini",
        "dashscope",
        "moonshot",
        "zhipu",
        "qianfan",
        "volcengine",
    }


def test_interactive_router_supported_provider_does_not_prompt_for_model():
    from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_fields
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    class _Questionary:
        def text(self, message: str, **_kwargs):
            if message == "Model id":
                raise AssertionError("router-supported providers should not prompt for model")
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(api_key_env="OPENROUTER_API_KEY"),
    )

    assert answers["model"] == ""
    assert answers["api_key_env"] == "OPENROUTER_API_KEY"


def test_interactive_provider_fields_default_to_pasted_api_key(monkeypatch):
    from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_fields
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            assert message == "LLM API key source"
            assert kwargs.get("choices") == [
                "Paste API key now",
                "Use environment variable OPENROUTER_API_KEY",
            ]
            assert kwargs.get("default") == "Paste API key now"
            return _Answer("Paste API key now")

        def text(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            assert message == "API key"
            return _Answer("sk-live")

        def confirm(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected confirm prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(),
    )

    assert answers["model"] == ""
    assert answers["api_key"] == "sk-live"
    assert answers["api_key_env"] == ""


def test_interactive_provider_fields_explains_detected_env_key(monkeypatch):
    from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_fields
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            assert message == "LLM API key source"
            assert kwargs.get("choices") == [
                "Paste API key now",
                "Use environment variable OPENROUTER_API_KEY (detected)",
            ]
            assert kwargs.get("default") == "Paste API key now"
            return _Answer("Use environment variable OPENROUTER_API_KEY (detected)")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(),
    )

    assert answers["api_key"] == ""
    assert answers["api_key_env"] == "OPENROUTER_API_KEY"


def test_interactive_provider_fields_requires_pasted_api_key(monkeypatch):
    from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_fields
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            assert message == "LLM API key source"
            assert kwargs.get("default") == "Paste API key now"
            return _Answer("Paste API key now")

        def password(self, message: str, **kwargs):
            assert message == "API key"
            validate = kwargs.get("validate")
            assert validate is not None
            assert validate("") is not True
            assert validate("sk-live") is True
            return _Answer("sk-live")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(),
    )

    assert answers["api_key"] == "sk-live"
    assert answers["api_key_env"] == ""


def test_interactive_provider_fields_rejects_terminal_paste_escape(monkeypatch):
    from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_fields
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            assert message == "LLM API key source"
            assert kwargs.get("default") == "Paste API key now"
            return _Answer("Paste API key now")

        def password(self, message: str, **kwargs):
            assert message == "API key"
            validate = kwargs.get("validate")
            assert validate is not None
            assert validate("[2;2~") is not True
            assert validate("\x1b[200~sk-live\x1b[201~") is not True
            assert validate("sk-live-with-[2;2~-literal-suffix") is True
            assert validate("sk-live") is True
            return _Answer("sk-live")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(),
    )

    assert answers["api_key"] == "sk-live"


def test_interactive_onboard_prompts_router_defaults_before_persist(tmp_path, monkeypatch):
    import sys
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: calls.append("start gate"))

    calls: list[str] = []

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "LLM provider":
                return _Answer("openrouter (OpenRouter)")
            if message == "LLM API key source":
                assert kwargs.get("default") == "Paste API key now"
                return _Answer("Use environment variable OPENROUTER_API_KEY")
            if message == "Router mode":
                assert kwargs.get("choices") == ["SquillaRouter", "Disabled"]
                assert kwargs.get("default") == "SquillaRouter"
                return _Answer("SquillaRouter")
            if message == "Default text model":
                assert kwargs.get("choices") == [
                    "Fast/simple (t0)",
                    "Balanced default (t1)",
                    "Stronger reasoning (t2)",
                    "Max quality (t3)",
                ]
                assert kwargs.get("default") == "Balanced default (t1)"
                return _Answer("Stronger reasoning (t2)")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            calls.append(message)
            if message == "Edit router tier models now?":
                return _Answer(False)
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
                "Enable image generation now?",
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert calls[0] == "start gate"
    assert calls[1] == "LLM provider"
    assert calls.index("Router mode") < calls.index("Configure a messaging channel now?")
    data = target.read_text()
    assert 'api_key = ""' in data
    assert 'api_key_env = "OPENROUTER_API_KEY"' in data
    assert 'default_tier = "t2"' in data
    assert 'model = "z-ai/glm-5.1"' in data


def test_interactive_onboard_can_enable_image_generation(tmp_path, monkeypatch):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-image-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)

    calls: list[str] = []

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "LLM provider":
                return _Answer("openrouter (OpenRouter)")
            if message == "LLM API key source":
                assert kwargs.get("default") == "Paste API key now"
                return _Answer("Paste API key now")
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer(kwargs.get("default"))
            if message == "Image generation provider":
                assert kwargs.get("default") == "openrouter (OpenRouter Images)"
                return _Answer("openrouter (OpenRouter Images)")
            if message == "Image API key source":
                assert "Use environment variable OPENROUTER_API_KEY" in kwargs.get("choices", [])
                assert "Reuse matching LLM provider key" in kwargs.get("choices", [])
                assert kwargs.get("default") == "Reuse matching LLM provider key"
                return _Answer("Reuse matching LLM provider key")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            calls.append(message)
            if message == "Primary image model":
                return _Answer(kwargs.get("default"))
            if message == "Image base URL":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            if message == "API key":
                return _Answer("sk-llm")
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            calls.append(message)
            if message == "Edit router tier models now?":
                return _Answer(False)
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
            }:
                return _Answer(False)
            if message == "Enable image generation now?":
                return _Answer(True)
            if message == "Image generation enabled?":
                return _Answer(True)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert calls.index("Enable image generation now?") > calls.index("Configure web search now?")
    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is True
    assert (
        data["image_generation"]["primary"]
        == "openrouter/google/gemini-3.1-flash-image-preview"
    )


def test_interactive_configure_image_generation_persists(tmp_path, monkeypatch):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-image-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    calls: list[str] = []

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "Image generation provider":
                return _Answer("openai (OpenAI Images)")
            if message == "Image API key source":
                return _Answer("Use environment variable OPENAI_API_KEY")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            calls.append(message)
            if message == "Primary image model":
                return _Answer(kwargs.get("default"))
            if message == "Image base URL":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **kwargs):
            calls.append(message)
            if message == "Image generation enabled?":
                assert kwargs.get("default") is True
                return _Answer(True)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_configure("image-generation")

    assert calls == [
        "Image generation provider",
        "Primary image model",
        "Image API key source",
        "Image base URL",
        "Image generation enabled?",
    ]
    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is True
    assert data["image_generation"]["primary"] == "openai/gpt-image-1"


def test_router_tier_overrides_edit_only_selected_tiers():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.flow import _router_tier_overrides

    calls: list[str] = []
    selections = iter(["Stronger reasoning (t2)", "Done"])

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            calls.append(message)
            assert message == "Tier to edit"
            assert kwargs.get("choices") == [
                "Done",
                "Fast/simple (t0)",
                "Balanced default (t1)",
                "Stronger reasoning (t2)",
                "Max quality (t3)",
                "Image model",
            ]
            return _Answer(next(selections))

        def text(self, message: str, **kwargs):
            calls.append(message)
            if message == "t2 provider":
                assert kwargs.get("default") == "openrouter"
                return _Answer("openrouter")
            if message == "t2 model":
                assert kwargs.get("default") == "z-ai/glm-5.1"
                return _Answer("custom/reasoner")
            raise AssertionError(f"unexpected text prompt: {message}")

    overrides = _router_tier_overrides(_Questionary(), GatewayConfig())

    assert calls == ["Tier to edit", "t2 provider", "t2 model", "Tier to edit"]
    assert overrides == {"t2": {"provider": "openrouter", "model": "custom/reasoner"}}


def test_interactive_feishu_websocket_prompts_only_core_fields(
    tmp_path, monkeypatch, capsys
):
    import sys
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow.importlib.util, "find_spec", lambda name: None)

    calls: list[str] = []

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "Channel type":
                return _Answer("feishu")
            if message == "Connection mode":
                return _Answer(kwargs.get("default") or "websocket")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            calls.append(message)
            if message == "Channel name":
                assert kwargs.get("default") == "feishu"
                return _Answer("feishu")
            if message == "App id":
                return _Answer("cli_test")
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            calls.append(message)
            if message == "App secret":
                return _Answer("secret")
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_channel_add(None)

    out = capsys.readouterr().out
    normalized_out = " ".join(out.split())
    assert "Feishu websocket mode requires the optional feishu extra" in out
    assert "Portable zip:" in out
    assert "latest recommended portable package" in out
    assert "pwsh -ExecutionPolicy Bypass -File install.ps1 -Extras feishu" in normalized_out
    assert "OPENSQUILLA_INSTALL_EXTRAS=feishu bash install.sh" in normalized_out
    assert "uv sync --extra recommended --extra feishu" in normalized_out
    assert "Restarting alone will not install Python packages." in out
    assert calls == ["Channel type", "Channel name", "App id", "App secret", "Connection mode"]
    data = target.read_text()
    assert 'type = "feishu"' in data
    assert 'app_id = "cli_test"' in data
    assert 'connection_mode = "websocket"' in data


def test_channel_saved_output_separates_configured_from_connected(capsys):
    from opensquilla.onboarding.flow import _print_channel_saved

    _print_channel_saved("feishu")

    out = capsys.readouterr().out
    assert "configured, not connected yet" in out
    assert "Restart the gateway process" in out
    assert "opensquilla channels status feishu --json" in out


def test_readme_distinguishes_recommended_profile_from_channel_extras() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert (
        "| New user | [Preview release package](#preview-release-package) | Recommended |"
    ) in readme
    assert (
        "| Command-line user | [Install from source](#install-from-source) | Available now |"
    ) in readme
    assert "| Developer | [Develop from source](#develop-from-source) | Available now |" in readme
    assert "Use this path if you want to try OpenSquilla as a local app" in readme
    assert "The recommended portable zip includes Feishu websocket support by default." in readme
    assert "`recommended` is the\nnormal runtime profile" in readme
    assert "Messaging channel adapters are opt-in extras." in readme
    assert "Feishu is shown only\nas an example channel adapter" in readme
    assert "powershell -ExecutionPolicy Bypass -File .\\install.ps1 -Extras feishu" in readme
    assert "OPENSQUILLA_INSTALL_EXTRAS=feishu bash install.sh" in readme
    assert "Install extras into the same environment you run:" in readme
    assert "uv sync --extra recommended --extra feishu" in readme
    assert "where.exe opensquilla" in readme


def test_search_provider_key_defaults_to_pasted_key_with_brave_hint(monkeypatch):
    from opensquilla.onboarding.flow import _ask_search_fields
    from opensquilla.onboarding.search_specs import get_search_provider_setup_spec

    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            if message == "Search fallback policy":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **kwargs):
            if message == "Use environment proxy for search?":
                return _Answer(False)
            if message == (
                "Enable search diagnostics? Include provider attempt/error details "
                "for troubleshooting?"
            ):
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def password(self, message: str, **_kwargs):
            assert message == (
                "Brave Search API key "
                "(create one at https://api-dashboard.search.brave.com/app/keys)"
            )
            return _Answer("brave-secret")

        def text(self, message: str, **kwargs):
            if message == "Max search results":
                return _Answer(kwargs.get("default"))
            if message == "Search HTTP proxy":
                return _Answer("")
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_search_fields(
        _Questionary(),
        get_search_provider_setup_spec("brave"),
    )

    assert answers["api_key"] == "brave-secret"
    assert answers["api_key_env"] == ""


def test_search_provider_detected_env_still_defaults_to_manual_key(monkeypatch):
    from opensquilla.onboarding.flow import _ask_search_fields
    from opensquilla.onboarding.search_specs import get_search_provider_setup_spec

    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "from-env")

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            if message == "Search fallback policy":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **kwargs):
            if message == "Use BRAVE_SEARCH_API_KEY from environment?":
                assert kwargs.get("default") is False
                return _Answer(False)
            if message == "Use environment proxy for search?":
                return _Answer(False)
            if message == (
                "Enable search diagnostics? Include provider attempt/error details "
                "for troubleshooting?"
            ):
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def password(self, message: str, **_kwargs):
            assert message == (
                "Brave Search API key "
                "(create one at https://api-dashboard.search.brave.com/app/keys)"
            )
            return _Answer("manual-brave-secret")

        def text(self, message: str, **kwargs):
            if message == "Max search results":
                return _Answer(kwargs.get("default"))
            if message == "Search HTTP proxy":
                return _Answer("")
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_search_fields(
        _Questionary(),
        get_search_provider_setup_spec("brave"),
    )

    assert answers["api_key"] == "manual-brave-secret"
    assert answers["api_key_env"] == ""


def test_search_provider_can_use_detected_env_when_requested(monkeypatch):
    from opensquilla.onboarding.flow import _ask_search_fields
    from opensquilla.onboarding.search_specs import get_search_provider_setup_spec

    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "from-env")

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            if message == "Search fallback policy":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **kwargs):
            if message == "Use BRAVE_SEARCH_API_KEY from environment?":
                assert kwargs.get("default") is False
                return _Answer(True)
            if message == "Use environment proxy for search?":
                return _Answer(False)
            if message == (
                "Enable search diagnostics? Include provider attempt/error details "
                "for troubleshooting?"
            ):
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

        def text(self, message: str, **kwargs):
            if message == "Max search results":
                return _Answer(kwargs.get("default"))
            if message == "Search HTTP proxy":
                return _Answer("")
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_search_fields(
        _Questionary(),
        get_search_provider_setup_spec("brave"),
    )

    assert answers["api_key"] == ""
    assert answers["api_key_env"] == "BRAVE_SEARCH_API_KEY"


def test_search_fallback_choice_names_duckduckgo_and_persists_value(monkeypatch):
    from opensquilla.onboarding.flow import _ask_search_fields
    from opensquilla.onboarding.search_specs import get_search_provider_setup_spec

    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            if message == "Search fallback policy":
                choices = kwargs.get("choices")
                assert choices == [
                    "off - no fallback; surface the original provider error",
                    "network - retry with DuckDuckGo on timeout/network errors",
                ]
                assert kwargs.get("default") == choices[0]
                return _Answer(choices[1])
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            if message == "Use environment proxy for search?":
                return _Answer(False)
            if message == (
                "Enable search diagnostics? Include provider attempt/error details "
                "for troubleshooting?"
            ):
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def password(self, message: str, **_kwargs):
            return _Answer("brave-secret")

        def text(self, message: str, **kwargs):
            if message == "Max search results":
                return _Answer(kwargs.get("default"))
            if message == "Search HTTP proxy":
                return _Answer("")
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_search_fields(
        _Questionary(),
        get_search_provider_setup_spec("brave"),
    )

    assert answers["fallback_policy"] == "network"


def test_search_provider_can_use_masked_api_key_prompt(monkeypatch):
    from opensquilla.onboarding.flow import _ask_search_fields
    from opensquilla.onboarding.search_specs import get_search_provider_setup_spec

    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary:
        def select(self, message: str, **kwargs):
            if message == "Search fallback policy":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def password(self, message: str, **_kwargs):
            assert message == (
                "Brave Search API key "
                "(create one at https://api-dashboard.search.brave.com/app/keys)"
            )
            return _Answer("brave-secret")

        def text(self, message: str, **kwargs):
            if message == "Max search results":
                return _Answer(kwargs.get("default"))
            if message == "Search HTTP proxy":
                return _Answer("")
            raise AssertionError(f"unexpected text prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            if message == "Use environment proxy for search?":
                return _Answer(False)
            if message == (
                "Enable search diagnostics? Include provider attempt/error details "
                "for troubleshooting?"
            ):
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    answers = _ask_search_fields(
        _Questionary(),
        get_search_provider_setup_spec("brave"),
    )

    assert answers["api_key"] == "brave-secret"
    assert answers["api_key_env"] == ""


def test_noninteractive_provider_configure_writes_config(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    from opensquilla.onboarding.flow import run_noninteractive_provider_configure

    result = run_noninteractive_provider_configure(
        "openrouter",
        {"model": "deepseek/deepseek-v4-flash", "api_key": "sk"},
    )
    assert result.path == target
    assert "openrouter" in target.read_text()


def test_noninteractive_channel_add_writes_config(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    from opensquilla.onboarding.flow import run_noninteractive_channel_add

    result = run_noninteractive_channel_add("slack", {"name": "w", "token": "x"})
    assert result.path == target
    assert "slack" in target.read_text()


def test_interactive_configure_without_tty_does_not_create_config(
    tmp_path, monkeypatch
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    from opensquilla.onboarding import flow

    monkeypatch.setattr(flow, "_is_tty", lambda: False)
    result = flow.run_interactive_configure("providers")

    assert result is None
    assert not target.exists()
