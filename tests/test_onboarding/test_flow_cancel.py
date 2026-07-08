"""User-cancellation handling in the interactive onboarding flow."""

from __future__ import annotations

from typing import Any

import pytest

from opensquilla.onboarding import flow
from opensquilla.onboarding.errors import UserCancelledError


class _Prompt:
    def __init__(self, value: Any) -> None:
        self._value = value

    def ask(self) -> Any:
        return self._value


class _Questionary:
    """Minimal stand-in that returns canned answers per prompt type."""

    def __init__(
        self,
        *,
        select_value: Any = None,
        password_value: Any = None,
        confirm_value: bool = False,
    ) -> None:
        self._select = select_value
        self._password = password_value
        self._confirm = confirm_value

    def select(self, *_args, **_kwargs):
        return _Prompt(self._select)

    def password(self, *_args, **_kwargs):
        return _Prompt(self._password)

    def confirm(self, *_args, **_kwargs):
        return _Prompt(self._confirm)

    def text(self, *_args, **_kwargs):
        return _Prompt("")


def test_search_choice_cancel_raises_user_cancelled():
    q = _Questionary(select_value=None)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_search_choice(q)
    assert exc_info.value.section == "search"


def test_search_api_key_cancel_raises_user_cancelled():
    spec = flow.get_search_provider_setup_spec("brave")
    q = _Questionary(password_value=None, confirm_value=False)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_search_fields(q, spec)
    assert exc_info.value.section == "search"


def test_search_api_key_cancel_aborts_before_followup_prompts(monkeypatch):
    """Once the user cancels the api_key prompt, the helper must abort
    immediately. Counting how many times ``.ask()`` is invoked after the
    password prompt protects against future prompt-label changes without
    making the test brittle to wording."""

    spec = flow.get_search_provider_setup_spec("brave")
    asks_after_password = {"count": 0}
    password_seen = {"seen": False}

    class _CountingPrompt:
        def __init__(self, kind: str, value: Any) -> None:
            self._kind = kind
            self._value = value

        def ask(self) -> Any:
            if self._kind == "password":
                password_seen["seen"] = True
            elif password_seen["seen"]:
                asks_after_password["count"] += 1
            return self._value

    class _Tracker:
        def select(self, *_a, **_kw):
            return _CountingPrompt("select", None)

        def password(self, *_a, **_kw):
            return _CountingPrompt("password", None)

        def confirm(self, *_a, **_kw):
            return _CountingPrompt("confirm", False)

        def text(self, *_a, **_kw):
            return _CountingPrompt("text", "")

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    with pytest.raises(UserCancelledError):
        flow._ask_search_fields(_Tracker(), spec)

    assert password_seen["seen"], "password prompt should have fired"
    assert asks_after_password["count"] == 0, (
        "no further prompts should run after api_key cancel"
    )


def test_search_fallback_cancel_raises_user_cancelled(monkeypatch):
    """A cancel at the fallback-policy select used to leak ``None`` into the
    enum mapper. With ``_ask_or_cancel``, it must surface as a typed cancel
    so the optional-section runner can route the user back cleanly."""

    spec = flow.get_search_provider_setup_spec("brave")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    fired: list[str] = []

    class _Tracker:
        def select(self, label, *_a, **_kw):
            fired.append(f"select:{label}")
            # Cancel only the fallback select; let earlier selects pass.
            if "fallback" in label:
                return _Prompt(None)
            return _Prompt(None)

        def password(self, *_a, **_kw):
            fired.append("password")
            return _Prompt("explicit-key")

        def confirm(self, *_a, **_kw):
            fired.append("confirm")
            return _Prompt(False)

        def text(self, label, *_a, **_kw):
            fired.append(f"text:{label}")
            return _Prompt("5" if "Max" in label else "")

    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_search_fields(_Tracker(), spec)
    assert exc_info.value.section == "search"
    assert any("fallback" in line for line in fired)


def test_provider_choice_cancel_raises_user_cancelled():
    """Provider select returning ``None`` previously crashed with
    ``AttributeError: 'NoneType' object has no attribute 'split'``."""

    from opensquilla.onboarding.flow import OnboardOptions

    q = _Questionary(select_value=None)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_provider_choice(q, OnboardOptions())
    assert exc_info.value.section == "provider"


class _RecordingConsole:
    """Stand-in for ``opensquilla.ui.console`` that records ``print`` calls.

    The real ``console`` is a Rich ``Console`` constructed at import time with
    a captured stdout reference, which makes ``capsys`` brittle under full
    test-suite execution. Monkeypatching ``flow.console`` keeps the assertion
    deterministic regardless of how Rich initialised in earlier tests.
    """

    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message: str = "", *_a, **_kw) -> None:
        self.messages.append(str(message))

    def joined(self) -> str:
        return "\n".join(self.messages)


def test_optional_section_runner_swallows_user_cancelled(monkeypatch):
    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    def _runner():
        raise UserCancelledError(section="search")

    flow._run_optional_section(
        section="search", label="search", runner=_runner
    )

    text = recorder.joined().lower()
    assert "search setup cancelled" in text
    assert "opensquilla onboard configure search" in recorder.joined()


def test_optional_section_runner_resume_hint_uses_section_slug_not_label(monkeypatch):
    """For multi-word labels (e.g. "image generation"), the resume hint must
    use the typed section slug so the command is actually runnable."""

    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    def _runner():
        raise UserCancelledError(section="image-generation")

    flow._run_optional_section(
        section="image-generation",
        label="image generation",
        runner=_runner,
    )

    assert "opensquilla onboard configure image-generation" in recorder.joined()


def test_optional_section_runner_swallows_keyboard_interrupt(monkeypatch):
    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    def _runner():
        raise KeyboardInterrupt

    flow._run_optional_section(
        section="search", label="search", runner=_runner
    )

    assert "interrupted" in recorder.joined().lower()


def test_optional_section_runner_propagates_value_error():
    """ValueError must propagate — those indicate real validation or
    programming errors, not user cancels. Swallowing them would let
    "Onboarding Complete" print over a broken config.

    Contract note: interactive numeric prompts now carry ``validate=`` hooks,
    so a user typo re-prompts at the input line and never surfaces here as a
    ValueError. Propagation stays pinned for genuine programming errors."""

    def _runner():
        raise ValueError("search provider 'brave' requires an api_key")

    with pytest.raises(ValueError):
        flow._run_optional_section(
            section="search", label="search", runner=_runner
        )


def test_optional_section_runner_propagates_unexpected_exception():
    class _BoomError(RuntimeError):
        pass

    def _runner():
        raise _BoomError("unexpected")

    with pytest.raises(_BoomError):
        flow._run_optional_section(
            section="search", label="search", runner=_runner
        )


# ---------------------------------------------------------------------------
# Image generation: cancel must never flow onward as ``None``.
# ---------------------------------------------------------------------------


def test_image_generation_provider_choice_cancel_raises_user_cancelled():
    """A cancel at the provider select used to crash with
    ``AttributeError: 'NoneType' object has no attribute 'split'`` — which
    escapes ``_run_optional_section`` and kills the whole wizard."""

    from opensquilla.gateway.config import GatewayConfig

    q = _Questionary(select_value=None)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_image_generation_choice(q, GatewayConfig())
    assert exc_info.value.section == "image-generation"


def test_image_generation_enabled_confirm_cancel_raises_user_cancelled(monkeypatch):
    """Cancelling the "Image generation enabled?" consent confirm used to
    store ``None`` and persist ``enabled = false`` under a success banner."""

    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.image_generation_specs import (
        get_image_generation_provider_setup_spec,
    )

    monkeypatch.setattr(flow, "console", _RecordingConsole())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-image-env")

    class _Prompted:
        def select(self, message, **_kw):
            if message == "Image API key source":
                return _Prompt("Use environment variable OPENAI_API_KEY")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message, **kwargs):
            return _Prompt(kwargs.get("default"))

        def confirm(self, message, **_kw):
            assert message == "Image generation enabled?"
            return _Prompt(None)

        def password(self, message, **_kw):
            raise AssertionError(f"unexpected password prompt: {message}")

    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_image_generation_fields(
            _Prompted(),
            get_image_generation_provider_setup_spec("openai"),
            GatewayConfig(),
        )
    assert exc_info.value.section == "image-generation"


def test_image_generation_configure_cancel_persists_nothing(tmp_path, monkeypatch):
    """An end-to-end cancel at the consent confirm must leave the config
    untouched instead of writing ``enabled = false`` and printing
    "Image generation configured."."""

    import sys
    import types

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-image-env")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "console", _RecordingConsole())

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _FakeQuestionary(types.SimpleNamespace):
        def select(self, message, **kwargs):
            if message == "Image generation provider":
                return _Answer("openai (OpenAI Images)")
            if message == "Image API key source":
                return _Answer("Use environment variable OPENAI_API_KEY")
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message, **kwargs):
            return _Answer(kwargs.get("default"))

        def confirm(self, message, **_kw):
            assert message == "Image generation enabled?"
            return _Answer(None)

        def password(self, message, **_kw):
            raise AssertionError(f"unexpected password prompt: {message}")

        def checkbox(self, message, **_kw):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _FakeQuestionary())

    with pytest.raises(UserCancelledError):
        flow.run_interactive_image_generation_configure(config_path=target)

    assert not target.exists()


# ---------------------------------------------------------------------------
# Channel wizard cancels.
# ---------------------------------------------------------------------------


def _channel_questionary_module(select_value):
    import types

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _FakeQuestionary(types.SimpleNamespace):
        def select(self, message, **_kw):
            return _Answer(select_value)

        def text(self, message, **_kw):
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message, **_kw):
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message, **_kw):
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def checkbox(self, message, **_kw):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    return _FakeQuestionary()


def test_channel_add_type_select_cancel_raises_user_cancelled(tmp_path, monkeypatch):
    """Cancelling the channel-type select used to crash with
    ``KeyError: "unknown channel type: None"``."""

    import sys

    target = tmp_path / "c.toml"
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setitem(sys.modules, "questionary", _channel_questionary_module(None))

    with pytest.raises(UserCancelledError) as exc_info:
        flow.run_interactive_channel_add(None, config_path=target)
    assert exc_info.value.section == "channels"
    assert not target.exists()


def test_channel_edit_picker_cancel_raises_user_cancelled(tmp_path, monkeypatch):
    """Cancelling the channel-to-edit select used to crash with a bare
    ``StopIteration`` from the entry lookup."""

    import sys

    from opensquilla.onboarding.setup_engine import SetupEngine

    target = tmp_path / "c.toml"
    engine = SetupEngine(path=target)
    engine.apply(
        "channels",
        {
            "type": "slack",
            "name": "slack-main",
            "token": "xoxb-stored",
            "signing_secret": "ss-stored",
        },
    )
    engine.persist()
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "console", _RecordingConsole())
    monkeypatch.setitem(sys.modules, "questionary", _channel_questionary_module(None))

    before = target.read_text()
    with pytest.raises(UserCancelledError) as exc_info:
        flow.run_interactive_channel_edit(None, config_path=target)
    assert exc_info.value.section == "channels"
    assert target.read_text() == before


@pytest.mark.parametrize(
    ("field_type", "extra"),
    [
        ("select", {"choices": ("webhook", "socket")}),
        ("bool", {"default": True}),
        ("password", {"secret": True}),
        ("int", {"default": 3}),
        ("float", {"default": 1.5}),
        ("text", {}),
    ],
)
def test_channel_field_prompt_cancel_raises_user_cancelled(field_type, extra):
    """Every channel field prompt must convert a cancel into the typed
    error instead of storing ``None``/coerced garbage for pydantic to
    reject much later."""

    from opensquilla.onboarding.channel_specs import ChannelSetupField

    field = ChannelSetupField(
        name="sample",
        label="Sample field",
        field_type=field_type,
        required=True,
        **extra,
    )

    class _CancellingQuestionary(_Questionary):
        def text(self, *_a, **_kw):
            return _Prompt(None)

    q = _CancellingQuestionary(
        select_value=None, password_value=None, confirm_value=None
    )
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_channel_field(q, field, field.default)
    assert exc_info.value.section == "channels"


# ---------------------------------------------------------------------------
# Router consent prompts.
# ---------------------------------------------------------------------------


def test_router_mode_cancel_raises_user_cancelled():
    """Cancelling the "Router mode" consent select used to map ``None`` to
    "recommended" and persist ``squilla_router.enabled = true``."""

    from opensquilla.gateway.config import GatewayConfig

    q = _Questionary(select_value=None)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_router_fields(
            q,
            GatewayConfig(),
            provider_id="openrouter",
            requested_mode="recommended",
        )
    assert exc_info.value.section == "router"


def test_router_default_tier_cancel_raises_user_cancelled(monkeypatch):
    """Cancelling the default-tier select must not silently persist c1."""

    from opensquilla.gateway.config import GatewayConfig

    monkeypatch.setattr(flow, "console", _RecordingConsole())

    class _Prompted:
        def select(self, message, **_kw):
            if message == "Router mode":
                return _Prompt("SquillaRouter")
            if message == "Default text model":
                return _Prompt(None)
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message, **_kw):
            raise AssertionError(f"unexpected confirm prompt: {message}")

    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_router_fields(
            _Prompted(),
            GatewayConfig(),
            provider_id="openrouter",
            requested_mode="recommended",
        )
    assert exc_info.value.section == "router"


# ---------------------------------------------------------------------------
# Provider key-source select.
# ---------------------------------------------------------------------------


def test_provider_key_source_cancel_raises_before_password_prompt(monkeypatch):
    """A cancel at the key-source select used to be indistinguishable from
    "Paste API key now" and dropped the user into a required password
    prompt."""

    from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_fields
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    password_fired: list[str] = []

    class _Prompted:
        def select(self, message, **_kw):
            assert message == "LLM API key source"
            return _Prompt(None)

        def password(self, message, **_kw):
            password_fired.append(message)
            return _Prompt("sk-should-never-be-asked")

    with pytest.raises(UserCancelledError) as exc_info:
        _ask_provider_fields(
            _Prompted(),
            get_provider_setup_spec("openrouter"),
            OnboardOptions(),
        )
    assert exc_info.value.section == "provider"
    assert password_fired == []


# ---------------------------------------------------------------------------
# Required provider stage: cancel propagates out of the wizard entry point.
# ---------------------------------------------------------------------------


def test_onboard_cancel_at_required_provider_stage_propagates(tmp_path, monkeypatch):
    """Cancelling the required provider select must surface as a typed
    cancellation from ``run_interactive_onboard`` (the CLI boundary decides
    how to render it) and must not write any config."""

    import sys
    import types

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)
    monkeypatch.setattr(flow, "detect_default_sources", lambda: [])
    monkeypatch.setattr(flow, "console", _RecordingConsole())

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _FakeQuestionary(types.SimpleNamespace):
        def select(self, message, **_kw):
            assert message == "LLM provider"
            return _Answer(None)

        def text(self, message, **_kw):
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message, **_kw):
            raise AssertionError(f"unexpected password prompt: {message}")

        def confirm(self, message, **_kw):
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def checkbox(self, message, **_kw):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _FakeQuestionary())

    with pytest.raises(UserCancelledError) as exc_info:
        flow.run_interactive_onboard(flow.OnboardOptions())
    assert exc_info.value.section == "provider"
    assert not target.exists()


def test_onboard_router_cancel_keeps_provider_and_skips_router(tmp_path, monkeypatch):
    """Cancelling the router step of the full wizard must skip the router
    section without persisting a fabricated router answer and without
    discarding the provider credentials entered just before it."""

    import sys
    import types

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "_wait_for_setup_start", lambda: None)
    monkeypatch.setattr(flow, "detect_default_sources", lambda: [])
    # The pre-save connection check is not under test here; degrade silently.
    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)
    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    real_upsert_router = flow.upsert_router
    router_calls: list[dict[str, Any]] = []

    def recording_upsert_router(*args: Any, **kwargs: Any) -> Any:
        router_calls.append(kwargs)
        return real_upsert_router(*args, **kwargs)

    monkeypatch.setattr(flow, "upsert_router", recording_upsert_router)

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _FakeQuestionary(types.SimpleNamespace):
        def select(self, message, **_kw):
            if message == "LLM provider":
                return _Answer("openrouter (OpenRouter)")
            if message == "LLM API key source":
                return _Answer("Use environment variable OPENROUTER_API_KEY")
            if message == "Router mode":
                return _Answer(None)
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message, **_kw):
            if message in {
                "Configure a messaging channel now?",
                "Configure web search now?",
                "Enable image generation now?",
            }:
                return _Answer(False)
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def text(self, message, **_kw):
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message, **_kw):
            raise AssertionError(f"unexpected password prompt: {message}")

        def checkbox(self, message, **_kw):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _FakeQuestionary())

    flow.run_interactive_onboard(flow.OnboardOptions())

    assert router_calls == [], "a cancelled router step must not call upsert_router"
    joined = recorder.joined()
    assert "router setup cancelled" in joined.lower()
    assert "opensquilla onboard configure router" in joined
    import tomllib

    data = tomllib.loads(target.read_text())
    # The credentials entered right before the router cancel are kept.
    assert data["llm"]["api_key_env"] == "OPENROUTER_API_KEY"


# ---------------------------------------------------------------------------
# Router tier editor: Esc must cancel, not persist (R3).
# ---------------------------------------------------------------------------


def test_router_tier_editor_select_cancel_raises_user_cancelled():
    """Esc at "Tier to edit" used to map to Done and let both callers run
    upsert_router + persist_config — a destructive re-save on explicit
    abort. It must raise the typed cancel like every sibling prompt."""

    from opensquilla.gateway.config import GatewayConfig

    q = _Questionary(select_value=None)
    with pytest.raises(UserCancelledError) as exc_info:
        flow._router_tier_overrides(q, GatewayConfig())
    assert exc_info.value.section == "router"


def test_router_tier_editor_text_prompt_cancel_raises_user_cancelled():
    """Esc at the tier provider/model text prompts used to silently mean
    keep-current-and-continue."""

    from opensquilla.gateway.config import GatewayConfig

    class _Prompted:
        def select(self, message, **_kw):
            assert message == "Tier to edit"
            return _Prompt("Route c1")

        def text(self, message, **_kw):
            assert message == "c1 provider"
            return _Prompt(None)

    with pytest.raises(UserCancelledError) as exc_info:
        flow._router_tier_overrides(_Prompted(), GatewayConfig())
    assert exc_info.value.section == "router"


def test_router_configure_tier_editor_cancel_persists_nothing(tmp_path, monkeypatch):
    """End-to-end: `onboard configure router` -> SquillaRouter -> edit tiers
    -> Esc at "Tier to edit" must not write config.toml (previously it
    replaced a hand-edited inline ladder with the packaged profile)."""

    import sys
    import types

    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "console", _RecordingConsole())

    class _Answer:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class _FakeQuestionary(types.SimpleNamespace):
        def select(self, message, **_kw):
            if message == "Router mode":
                return _Answer("SquillaRouter")
            if message == "Default text model":
                return _Answer("Route c1")
            if message == "Tier to edit":
                return _Answer(None)  # Esc
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message, **_kw):
            assert message == "Edit router tier models now?"
            return _Answer(True)

        def text(self, message, **_kw):
            raise AssertionError(f"unexpected text prompt: {message}")

        def password(self, message, **_kw):
            raise AssertionError(f"unexpected password prompt: {message}")

        def checkbox(self, message, **_kw):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _FakeQuestionary())

    with pytest.raises(UserCancelledError) as exc_info:
        flow.run_interactive_router_configure(config_path=target)
    assert exc_info.value.section == "router"
    assert not target.exists()
