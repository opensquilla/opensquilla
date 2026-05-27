"""Tests for non-interactive onboarding flow halves."""

from __future__ import annotations

import types
from io import StringIO

from rich.console import Console


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

        def checkbox(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

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
            assert kwargs.get("default") == (
                "Use environment variable OPENROUTER_API_KEY (detected)"
            )
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
    monkeypatch.setattr(flow, "detect_default_sources", lambda: [])

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


def test_interactive_onboard_migration_defaults_to_all_sources_and_keeps_imported_provider(
    tmp_path, monkeypatch
):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-imported-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: calls.append("start gate"))
    detected = [
        flow.DetectedMigrationSource("openclaw", tmp_path / ".openclaw"),
        flow.DetectedMigrationSource("hermes", tmp_path / ".hermes"),
    ]
    monkeypatch.setattr(flow, "detect_default_sources", lambda: detected)

    calls: list[str] = []
    batches: list[tuple[tuple[str, ...], bool, bool]] = []

    def fake_run_migration_batch(_detected, selected, options):
        batches.append((tuple(selected), options.apply, options.migrate_secrets))
        if options.apply:
            target.write_text(
                "\n".join(
                    [
                        "[llm]",
                        'provider = "openrouter"',
                        'model = "anthropic/claude-sonnet-4.5"',
                        'api_key_env = "OPENROUTER_API_KEY"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return flow.MigrationBatchResult(
            selected=tuple(selected),
            apply=options.apply,
            reports={
                name: {
                    "output_dir": str(tmp_path / "reports" / name),
                    "items": [
                        {
                            "kind": "config",
                            "status": "applied" if options.apply else "planned",
                        }
                    ],
                }
                for name in selected
            },
        )

    monkeypatch.setattr(flow, "run_migration_batch", fake_run_migration_batch)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Choice:
        def __init__(self, title, value, checked=False, description=None):
            self.title = title
            self.value = value
            self.checked = checked
            self.description = description

    class _Questionary(types.SimpleNamespace):
        Choice = _Choice

        def checkbox(self, message: str, choices, **kwargs):
            calls.append(message)
            assert message == "Select sources to import"
            assert kwargs.get("instruction") == (
                "Space select | Enter continue | A toggle all"
            )
            assert [choice.value for choice in choices] == ["openclaw", "hermes"]
            assert [choice.title for choice in choices] == ["OpenClaw", "Hermes Agent"]
            assert [choice.description for choice in choices] == [
                str(tmp_path / ".openclaw"),
                str(tmp_path / ".hermes"),
            ]
            assert all(choice.checked for choice in choices)
            return _Answer([choice.value for choice in choices])

        def confirm(self, message: str, **kwargs):
            calls.append(message)
            if message == "Review migration options now?":
                assert kwargs.get("default") is True
                return _Answer(True)
            if message == "Import saved API keys/tokens from detected legacy .env files?":
                assert kwargs.get("default") is False
                return _Answer(False)
            if message == "Apply this migration now?":
                assert kwargs.get("default") is True
                return _Answer(True)
            if message == "Use imported provider credentials?":
                assert kwargs.get("default") is True
                return _Answer(True)
            if message == "Edit router tier models now?":
                return _Answer(False)
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
                "Enable image generation now?",
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def select(self, message: str, **_kwargs):
            calls.append(message)
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer(_kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected password prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert batches == [
        (("openclaw", "hermes"), False, False),
        (("openclaw", "hermes"), True, False),
    ]
    assert "LLM provider" not in calls
    assert "Router mode" in calls
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "openrouter"
    assert data["llm"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert data["llm"]["model"] == "deepseek/deepseek-v4-flash"
    assert data["squilla_router"]["enabled"] is True
    assert data["squilla_router"]["tier_profile"] == "openrouter"
    assert "api_key" not in data["llm"]


def test_interactive_onboard_imported_provider_prefers_inline_key_over_env(
    tmp_path, monkeypatch
):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)
    monkeypatch.setattr(
        flow,
        "detect_default_sources",
        lambda: [flow.DetectedMigrationSource("openclaw", tmp_path / ".openclaw")],
    )

    calls: list[str] = []

    def fake_run_migration_batch(_detected, selected, options):
        if options.apply:
            target.write_text(
                "\n".join(
                    [
                        "[llm]",
                        'provider = "openrouter"',
                        'model = "anthropic/claude-sonnet-4.5"',
                        'api_key = "sk-imported"',
                        'api_key_env = "OPENROUTER_API_KEY"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return flow.MigrationBatchResult(
            selected=tuple(selected),
            apply=options.apply,
            reports={
                "openclaw": {
                    "output_dir": str(tmp_path / "reports" / "openclaw"),
                    "items": [{"kind": "config", "status": "planned"}],
                }
            },
        )

    monkeypatch.setattr(flow, "run_migration_batch", fake_run_migration_batch)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def confirm(self, message: str, **kwargs):
            calls.append(message)
            if message == "Review migration options now?":
                return _Answer(True)
            if message == "Import saved API keys/tokens from detected legacy .env files?":
                return _Answer(True)
            if message == "Apply this migration now?":
                return _Answer(True)
            if message == "Use imported provider credentials?":
                return _Answer(True)
            if message == "Edit router tier models now?":
                return _Answer(False)
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
                "Enable image generation now?",
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected password prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert "LLM provider" not in calls
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "openrouter"
    assert data["llm"]["api_key"] == "sk-imported"
    assert data["llm"].get("api_key_env", "") == ""
    assert data["llm"]["model"] == "deepseek/deepseek-v4-flash"


def test_interactive_onboard_imported_provider_finalize_error_continues_setup(
    tmp_path, monkeypatch
):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    console_output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=console_output, force_terminal=False, highlight=False),
    )
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)
    monkeypatch.setattr(
        flow,
        "detect_default_sources",
        lambda: [flow.DetectedMigrationSource("openclaw", tmp_path / ".openclaw")],
    )
    monkeypatch.setattr(
        flow,
        "_use_imported_provider_credentials_with_router_defaults",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad imported provider")),
    )

    calls: list[str] = []

    def fake_run_migration_batch(_detected, selected, options):
        if options.apply:
            target.write_text(
                "\n".join(
                    [
                        "[llm]",
                        'provider = "openrouter"',
                        'model = "anthropic/claude-sonnet-4.5"',
                        'api_key_env = "OPENROUTER_API_KEY"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return flow.MigrationBatchResult(
            selected=tuple(selected),
            apply=options.apply,
            reports={
                "openclaw": {
                    "output_dir": str(tmp_path / "reports" / "openclaw"),
                    "items": [{"kind": "config", "status": "planned"}],
                }
            },
        )

    monkeypatch.setattr(flow, "run_migration_batch", fake_run_migration_batch)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def confirm(self, message: str, **kwargs):
            calls.append(message)
            if message == "Review migration options now?":
                return _Answer(True)
            if message == "Import saved API keys/tokens from detected legacy .env files?":
                return _Answer(False)
            if message == "Apply this migration now?":
                return _Answer(True)
            if message == "Use imported provider credentials?":
                return _Answer(True)
            if message == "Edit router tier models now?":
                return _Answer(False)
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
                "Enable image generation now?",
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "LLM provider":
                return _Answer("openrouter (OpenRouter)")
            if message == "LLM API key source":
                return _Answer("Use environment variable OPENROUTER_API_KEY")
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected password prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert "LLM provider" in calls
    out = console_output.getvalue()
    assert "Imported provider settings could not be finalized" in out
    assert "Continue provider setup to finish onboarding" in out
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "openrouter"
    assert data["llm"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert data["llm"]["model"] == "deepseek/deepseek-v4-flash"


def test_onboard_migration_selection_summary_lists_checked_sources(tmp_path, monkeypatch):
    from opensquilla.onboarding import flow

    console_output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=console_output, force_terminal=False, highlight=False),
    )

    detected = [
        flow.DetectedMigrationSource("openclaw", tmp_path / ".openclaw"),
        flow.DetectedMigrationSource("hermes", tmp_path / ".hermes"),
    ]

    flow._print_selected_migration_sources(detected, ["openclaw", "hermes"])

    out = console_output.getvalue()
    assert "Selected migration sources" in out
    assert "☑ OpenClaw" in out
    assert "☑ Hermes Agent" in out
    unwrapped_out = out.replace("\n", "")
    assert str(tmp_path / ".openclaw") in unwrapped_out
    assert str(tmp_path / ".hermes") in unwrapped_out


def test_onboard_migration_source_prompt_uses_clear_continue_language(tmp_path):
    from opensquilla.onboarding import flow

    captured: dict[str, object] = {}

    class _Answer:
        def ask(self):
            return ["openclaw", "hermes"]

    class _Choice:
        def __init__(self, title, value, checked=False, description=None):
            self.title = title
            self.value = value
            self.checked = checked
            self.description = description

    class _Questionary:
        Choice = _Choice

        def checkbox(self, message: str, **kwargs):
            captured["message"] = message
            captured["instruction"] = kwargs.get("instruction")
            return _Answer()

    selected = flow._ask_migration_sources(
        _Questionary(),
        [
            flow.DetectedMigrationSource("openclaw", tmp_path / ".openclaw"),
            flow.DetectedMigrationSource("hermes", tmp_path / ".hermes"),
        ],
    )

    assert selected == ["openclaw", "hermes"]
    assert captured == {
        "message": "Select sources to import",
        "instruction": "Space select | Enter continue | A toggle all",
    }


def test_onboard_migration_preview_hides_unwritten_report_path(tmp_path, monkeypatch):
    from opensquilla.onboarding import flow

    console_output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=console_output, force_terminal=False, highlight=False),
    )
    missing_report_dir = tmp_path / "dry-run-report"

    flow._print_migration_summary(
        flow.MigrationBatchResult(
            selected=("openclaw",),
            apply=False,
            reports={
                "openclaw": {
                    "output_dir": str(missing_report_dir),
                    "items": [{"kind": "config", "status": "planned"}],
                }
            },
        ),
        title="Migration preview",
    )

    out = console_output.getvalue()
    assert "Migration preview" in out
    assert "planned=1" in out
    assert str(missing_report_dir) not in out


def test_interactive_onboard_migration_preview_failure_continues_provider_setup(
    tmp_path, monkeypatch
):
    import sys
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: calls.append("start gate"))
    detected = [flow.DetectedMigrationSource("openclaw", tmp_path / ".openclaw")]
    monkeypatch.setattr(flow, "detect_default_sources", lambda: detected)

    calls: list[str] = []
    batches: list[tuple[tuple[str, ...], bool]] = []

    def fake_run_migration_batch(_detected, selected, options):
        batches.append((tuple(selected), options.apply))
        return flow.MigrationBatchResult(
            selected=tuple(selected),
            apply=options.apply,
            reports={
                "openclaw": {
                    "output_dir": str(tmp_path / "reports" / "openclaw"),
                    "items": [{"kind": "source", "status": "error", "reason": "bad source"}],
                }
            },
        )

    monkeypatch.setattr(flow, "run_migration_batch", fake_run_migration_batch)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def confirm(self, message: str, **kwargs):
            calls.append(message)
            if message == "Review migration options now?":
                assert kwargs.get("default") is True
                return _Answer(True)
            if message == "Import saved API keys/tokens from detected legacy .env files?":
                assert kwargs.get("default") is False
                return _Answer(False)
            if message == "Edit router tier models now?":
                return _Answer(False)
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
                "Enable image generation now?",
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "LLM provider":
                return _Answer("openrouter (OpenRouter)")
            if message == "LLM API key source":
                return _Answer("Use environment variable OPENROUTER_API_KEY")
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected password prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert batches == [(("openclaw",), False)]
    assert "Apply this migration now?" not in calls
    assert "LLM provider" in calls
    data = target.read_text()
    assert 'provider = "openrouter"' in data
    assert 'api_key_env = "OPENROUTER_API_KEY"' in data


def test_interactive_onboard_migration_prompts_for_missing_imported_provider_key(
    tmp_path, monkeypatch
):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("IMPORTED_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: calls.append("start gate"))
    detected = [flow.DetectedMigrationSource("openclaw", tmp_path / ".openclaw")]
    monkeypatch.setattr(flow, "detect_default_sources", lambda: detected)

    calls: list[str] = []

    def fake_run_migration_batch(_detected, selected, options):
        if options.apply:
            target.write_text(
                "\n".join(
                    [
                        "[llm]",
                        'provider = "openrouter"',
                        'model = "anthropic/claude-sonnet-4.5"',
                        'api_key_env = "IMPORTED_OPENROUTER_KEY"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return flow.MigrationBatchResult(
            selected=tuple(selected),
            apply=options.apply,
            reports={
                "openclaw": {
                    "output_dir": str(tmp_path / "reports" / "openclaw"),
                    "items": [{"kind": "config", "status": "planned"}],
                }
            },
        )

    monkeypatch.setattr(flow, "run_migration_batch", fake_run_migration_batch)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def confirm(self, message: str, **kwargs):
            calls.append(message)
            if message == "Review migration options now?":
                return _Answer(True)
            if message == "Import saved API keys/tokens from detected legacy .env files?":
                assert kwargs.get("default") is False
                return _Answer(False)
            if message == "Apply this migration now?":
                return _Answer(True)
            if message == "Edit router tier models now?":
                return _Answer(False)
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
                "Enable image generation now?",
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "LLM API key source":
                assert "Use environment variable IMPORTED_OPENROUTER_KEY" in kwargs.get(
                    "choices", []
                )
                assert "Use environment variable OPENROUTER_API_KEY" in kwargs.get(
                    "choices", []
                )
                assert kwargs.get("default") == "Paste API key now"
                return _Answer("Paste API key now")
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def password(self, message: str, **_kwargs):
            calls.append(message)
            if message == "API key":
                return _Answer("sk-new")
            raise AssertionError(f"unexpected password prompt: {message}")

        def text(self, message: str, **_kwargs):
            calls.append(message)
            raise AssertionError(f"unexpected text prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert "LLM provider" not in calls
    assert "Router mode" in calls
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "openrouter"
    assert data["llm"]["api_key"] == "sk-new"
    assert data["llm"]["model"] == "deepseek/deepseek-v4-flash"


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
    monkeypatch.setattr(flow, "detect_default_sources", lambda: [])

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
                assert kwargs.get("default") == (
                    "Use environment variable OPENROUTER_API_KEY (detected)"
                )
                return _Answer("Use environment variable OPENROUTER_API_KEY (detected)")
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer(kwargs.get("default"))
            if message == "Image generation provider":
                assert kwargs.get("default") == "openrouter (OpenRouter Images)"
                return _Answer("openrouter (OpenRouter Images)")
            if message == "Image API key source":
                assert (
                    "Use environment variable OPENROUTER_API_KEY"
                    in kwargs.get("choices", [])
                )
                assert "Reuse matching LLM provider key" not in kwargs.get("choices", [])
                assert kwargs.get("default") == "Use environment variable OPENROUTER_API_KEY"
                return _Answer("Use environment variable OPENROUTER_API_KEY")
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


def test_onboard_if_needed_core_ready_repairs_memory_embedding_without_provider_setup(
    tmp_path,
    monkeypatch,
):
    import sys
    import tomllib
    import types

    from opensquilla.gateway.config import (
        GatewayConfig,
        LlmProviderConfig,
        MemoryEmbeddingConfig,
    )
    from opensquilla.onboarding import flow
    from opensquilla.onboarding.config_store import persist_config

    target = tmp_path / "c.toml"
    cfg = GatewayConfig(config_path=str(target))
    cfg.llm = LlmProviderConfig(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash",
        api_key="sk-core",
    )
    cfg.memory.embedding = MemoryEmbeddingConfig(provider="openai")
    persist_config(cfg, path=target, backup=False)

    calls: list[str] = []
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-memory-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: calls.append("start gate"))
    monkeypatch.setattr(flow, "detect_default_sources", lambda: [])

    banner_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        flow,
        "banner_panel",
        lambda title, subtitle: banner_calls.append((title, subtitle)) or title,
    )

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def confirm(self, message: str, **kwargs):
            calls.append(message)
            if message == "Configure memory embeddings now?":
                assert kwargs.get("default") is True
                return _Answer(True)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def select(self, message: str, **kwargs):
            calls.append(message)
            if message == "Memory embedding provider":
                return _Answer("openai (OpenAI)")
            if message == "Memory API key source":
                assert "Use environment variable OPENAI_API_KEY (detected)" in kwargs.get(
                    "choices", []
                )
                return _Answer("Use environment variable OPENAI_API_KEY (detected)")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            calls.append(message)
            if message == "Memory embedding model":
                return _Answer(kwargs.get("default"))
            if message == "Memory embedding base URL":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_onboard(flow.OnboardOptions(if_needed=True))

    assert "LLM provider" not in calls
    assert calls.index("Configure memory embeddings now?") < calls.index(
        "Memory embedding provider"
    )
    assert banner_calls == [
        (
            "OpenSquilla Onboarding",
            "Migration · Provider · SquillaRouter · Channels · Capabilities",
        )
    ]
    data = tomllib.loads(target.read_text())
    assert data["memory"]["embedding"]["provider"] == "openai"
    assert data["memory"]["embedding"]["remote"]["api_key_env"] == "OPENAI_API_KEY"
    assert "api_key" not in data["memory"]["embedding"]["remote"]


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


def test_interactive_configure_image_generation_uses_explicit_config_path(
    tmp_path,
    monkeypatch,
):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    default_target = tmp_path / "default.toml"
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(default_target))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-image-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            if message == "Image generation provider":
                return _Answer("openai (OpenAI Images)")
            if message == "Image API key source":
                return _Answer("Use environment variable OPENAI_API_KEY")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            if message == "Primary image model":
                return _Answer(kwargs.get("default"))
            if message == "Image base URL":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **kwargs):
            if message == "Image generation enabled?":
                assert kwargs.get("default") is True
                return _Answer(True)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_configure("image-generation", config_path=target)

    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is True
    assert data["image_generation"]["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert not default_target.exists()


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


def test_interactive_feishu_websocket_prompts_only_core_fields(tmp_path, monkeypatch):
    import sys
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    console_output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=console_output, force_terminal=False, highlight=False),
    )
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

    out = console_output.getvalue()
    normalized_out = " ".join(out.split())
    assert "Feishu websocket mode requires the base lark-oapi dependency" in out
    assert "Portable zip:" in out
    assert "latest recommended portable package" in out
    assert "OPENSQUILLA_INSTALL_EXTRAS" not in normalized_out
    assert "https://opensquilla.ai/install.ps1" in normalized_out
    assert "https://opensquilla.ai/install.sh" in normalized_out
    assert "bash -s --" in normalized_out
    assert "uv sync --extra recommended" in normalized_out
    assert "--extra feishu" not in normalized_out
    assert "Restarting alone will not install Python packages." in out
    assert calls == ["Channel type", "Channel name", "App id", "App secret", "Connection mode"]
    data = target.read_text()
    assert 'type = "feishu"' in data
    assert 'app_id = "cli_test"' in data
    assert 'connection_mode = "websocket"' in data


def test_interactive_channel_add_uses_explicit_config_path(tmp_path, monkeypatch):
    import sys
    import types

    from opensquilla.onboarding import flow

    default_target = tmp_path / "default.toml"
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(default_target))
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            if message == "Channel type":
                return _Answer("slack")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            if message == "Channel name":
                return _Answer("slack-main")
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            if message == "Bot token (xoxb-...)":
                return _Answer("xoxb-test")
            if message == "Signing secret":
                return _Answer("signing-secret")
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def checkbox(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_channel_add(None, config_path=target)

    assert 'type = "slack"' in target.read_text()
    assert not default_target.exists()


def test_optional_onboarding_section_receives_explicit_config_path(tmp_path):
    from opensquilla.onboarding import flow

    target = tmp_path / "custom.toml"
    seen = {}

    def runner(*, config_path=None):
        seen["config_path"] = config_path

    flow._run_optional_section(
        section="search",
        label="search",
        runner=runner,
        config_path=target,
    )

    assert seen["config_path"] == target


def test_channel_saved_output_separates_configured_from_connected(monkeypatch):
    from opensquilla.onboarding import flow
    from opensquilla.onboarding.flow import _print_channel_saved

    console_output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=console_output, force_terminal=False, highlight=False),
    )

    _print_channel_saved("feishu")

    out = console_output.getvalue()
    assert "configured, not connected yet" in out
    assert "Restart the gateway process" in out
    assert "opensquilla channels status feishu --json" in out


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


def test_search_provider_detected_env_prefers_env_but_can_use_manual_key(monkeypatch):
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
                assert kwargs.get("default") is True
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
                assert kwargs.get("default") is True
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


def test_interactive_configure_search_uses_explicit_config_path(tmp_path, monkeypatch):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    default_target = tmp_path / "default.toml"
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(default_target))
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            if message == "Search provider":
                return _Answer("duckduckgo (DuckDuckGo)")
            if message == "Search fallback policy":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            if message == "Max search results":
                return _Answer("7")
            if message == "Search HTTP proxy":
                return _Answer("")
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            if message in {
                "Use environment proxy for search?",
                flow._SEARCH_DIAGNOSTICS_PROMPT,
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_configure("search", config_path=target)

    data = tomllib.loads(target.read_text())
    assert data["search_provider"] == "duckduckgo"
    assert data["search_max_results"] == 7
    assert not default_target.exists()


def test_interactive_configure_memory_embedding_is_in_section_menu(
    tmp_path,
    monkeypatch,
):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-memory-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            if message == "Section":
                assert "memory-embedding" in kwargs["choices"]
                return _Answer("memory-embedding")
            if message == "Memory embedding provider":
                return _Answer("openai (OpenAI)")
            if message == "Memory API key source":
                return _Answer("Use environment variable OPENAI_API_KEY")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **kwargs):
            if message == "Memory embedding model":
                return _Answer("text-embedding-3-small")
            if message == "Memory embedding base URL":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_configure(config_path=target)

    data = tomllib.loads(target.read_text())
    remote = data["memory"]["embedding"]["remote"]
    assert data["memory"]["embedding"]["provider"] == "openai"
    assert remote["api_key_env"] == "OPENAI_API_KEY"
    assert "api_key" not in remote


def test_interactive_memory_embedding_configure_without_tty_prints_hint(
    tmp_path,
    monkeypatch,
    capsys,
):
    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: False)

    result = flow.run_interactive_memory_embedding_configure(config_path=target)

    assert result.warnings == ["tty_required"]
    assert not target.exists()
    out = capsys.readouterr().out
    assert "Headless memory embedding:" in out
    assert "opensquilla onboard configure memory-embedding --config" in out


def test_interactive_configure_provider_accepts_singular_section_alias(
    tmp_path,
    monkeypatch,
):
    from opensquilla.onboarding import flow
    from opensquilla.onboarding.config_store import PersistResult

    target = tmp_path / "custom.toml"
    seen = {}
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    def fake_run_interactive_onboard(options):
        seen["config_path"] = options.config_path
        return PersistResult(
            path=target,
            backup_path=None,
            restart_required=False,
            warnings=[],
        )

    monkeypatch.setattr(flow, "run_interactive_onboard", fake_run_interactive_onboard)

    result = flow.run_interactive_configure("provider", config_path=target)

    assert result is not None
    assert seen["config_path"] == target


def test_interactive_configure_router_persists(tmp_path, monkeypatch):
    import sys
    import tomllib
    import types

    from opensquilla.onboarding import flow

    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\nprovider = "openrouter"\nmodel = "deepseek/deepseek-v4-flash"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs):
            if message == "Router mode":
                return _Answer("Disabled")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def checkbox(self, message: str, **_kwargs):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_configure("router", config_path=target)

    data = tomllib.loads(target.read_text())
    assert data["squilla_router"]["enabled"] is False


def test_interactive_configure_provider_receives_explicit_config_path(
    tmp_path,
    monkeypatch,
):
    from opensquilla.onboarding import flow
    from opensquilla.onboarding.config_store import PersistResult

    target = tmp_path / "custom.toml"
    seen = {}
    monkeypatch.setattr(flow, "_is_tty", lambda: True)

    def fake_run_interactive_onboard(options):
        seen["config_path"] = options.config_path
        return PersistResult(
            path=target,
            backup_path=None,
            restart_required=False,
            warnings=[],
        )

    monkeypatch.setattr(flow, "run_interactive_onboard", fake_run_interactive_onboard)

    result = flow.run_interactive_configure("providers", config_path=target)

    assert result is not None
    assert seen["config_path"] == target


def test_interactive_configure_without_tty_does_not_create_config(
    tmp_path, monkeypatch, capsys
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    from opensquilla.onboarding import flow

    monkeypatch.setattr(flow, "_is_tty", lambda: False)
    result = flow.run_interactive_configure("providers")

    assert result is None
    out = capsys.readouterr().out
    assert "Guided CLI:" in out
    assert "Provider recipes:" in out
    assert "Headless provider:" not in out
    assert "Check status:" in out
    assert not target.exists()
