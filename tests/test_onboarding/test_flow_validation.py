"""Input validation and stored-value seeding in the interactive wizard.

These tests drive the questionary seams with a validate-aware fake prompt:
like the real library, a canned input is only returned once the prompt's
``validate=`` hook accepts it, so garbage input re-prompts instead of leaking
into ``int()``/pydantic and crashing the wizard mid-section.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from opensquilla.onboarding import flow
from opensquilla.onboarding.channel_specs import ChannelSetupField
from opensquilla.onboarding.errors import UserCancelledError
from opensquilla.onboarding.flow import OnboardOptions
from opensquilla.onboarding.provider_specs import get_provider_setup_spec
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec
from opensquilla.search.types import DEFAULT_SEARCH_MAX_RESULTS


class _ValidatedPrompt:
    """Fake prompt honouring ``validate=`` the way questionary does.

    Rejected input is re-asked (the next canned value is tried), so a
    garbage value can only be returned when the prompt carries no validator
    — which is exactly the regression each test pins.
    """

    def __init__(self, values: list[Any], validate: Any) -> None:
        self._values = list(values)
        self._validate = validate

    def ask(self) -> Any:
        while self._values:
            candidate = self._values.pop(0)
            if candidate is None:
                return None  # cancel short-circuits validation
            if self._validate is None or self._validate(candidate) is True:
                return candidate
        raise AssertionError("prompt inputs exhausted without an accepted value")


class _RecordingConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message: str = "", *_a, **_kw) -> None:
        self.messages.append(str(message))

    def joined(self) -> str:
        return "\n".join(self.messages)


# ---------------------------------------------------------------------------
# C1-5 — numeric prompts re-prompt on garbage instead of raising ValueError.
# ---------------------------------------------------------------------------


def _duckduckgo_search_questionary(max_results_inputs: list[Any]):
    class _Answer:
        def __init__(self, value: Any) -> None:
            self.value = value

        def ask(self) -> Any:
            return self.value

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            if message == "Max search results":
                return _ValidatedPrompt(max_results_inputs, kwargs.get("validate"))
            if message == "Search HTTP proxy":
                return _Answer("")
            raise AssertionError(f"unexpected text prompt: {message}")

        def select(self, message: str, **kwargs: Any):
            if message == "Search fallback policy":
                return _Answer(kwargs.get("default"))
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **_kwargs: Any):
            return _Answer(False)

        def password(self, message: str, **_kwargs: Any):
            raise AssertionError(f"unexpected password prompt: {message}")

    return _Questionary()


def test_search_max_results_garbage_reprompts_instead_of_crashing():
    """Typing a non-number used to raise a raw ``ValueError`` that aborted
    every remaining onboarding section and discarded the just-entered
    search credentials."""

    answers = flow._ask_search_fields(
        _duckduckgo_search_questionary(["banana", "7"]),
        get_search_provider_setup_spec("duckduckgo"),
    )

    assert answers["max_results"] == 7


def test_search_max_results_blank_keeps_default():
    answers = flow._ask_search_fields(
        _duckduckgo_search_questionary([""]),
        get_search_provider_setup_spec("duckduckgo"),
    )

    assert answers["max_results"] == DEFAULT_SEARCH_MAX_RESULTS


def test_search_max_results_validator_enforces_minimum_of_one():
    """The write side requires an integer >= 1; the prompt must reject the
    same range up front instead of failing at persist time."""

    answers = flow._ask_search_fields(
        _duckduckgo_search_questionary(["0", "-3", "2"]),
        get_search_provider_setup_spec("duckduckgo"),
    )

    assert answers["max_results"] == 2


def test_channel_int_field_garbage_reprompts_instead_of_crashing():
    field = ChannelSetupField(
        name="poll_interval",
        label="Poll interval",
        field_type="int",
        required=True,
        default=3,
    )

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            assert message == "Poll interval"
            return _ValidatedPrompt(["lots", "5"], kwargs.get("validate"))

    assert flow._ask_channel_field(_Questionary(), field, field.default) == 5


def test_channel_float_field_garbage_reprompts_instead_of_crashing():
    field = ChannelSetupField(
        name="timeout",
        label="Timeout seconds",
        field_type="float",
        required=True,
        default=1.5,
    )

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            assert message == "Timeout seconds"
            return _ValidatedPrompt(["fast", "2.5"], kwargs.get("validate"))

    assert flow._ask_channel_field(_Questionary(), field, field.default) == 2.5


# ---------------------------------------------------------------------------
# C1-6 — required base URL: validated input, Esc cancels.
# ---------------------------------------------------------------------------


def test_required_base_url_rejects_blank_and_non_http_schemes():
    """Plain Enter used to coerce the answer to '' and kill the wizard with
    a raw ``ValueError`` at persist time."""

    captured: dict[str, Any] = {}

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            assert message == "Base URL"
            captured["validate"] = kwargs.get("validate")
            return _ValidatedPrompt(
                ["", "ftp://intranet.test", "http://localhost:8000/v1"],
                kwargs.get("validate"),
            )

    answers = flow._ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("vllm"),
        OnboardOptions(model="stub-model"),
    )

    assert answers["base_url"] == "http://localhost:8000/v1"
    validate = captured["validate"]
    assert validate is not None
    assert validate("") is not True
    assert validate("   ") is not True
    assert validate("ftp://intranet.test") is not True
    assert validate("https://example.test/v1") is True


def test_required_base_url_cancel_raises_user_cancelled():
    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            assert message == "Base URL"
            return _ValidatedPrompt([None], kwargs.get("validate"))

    with pytest.raises(UserCancelledError) as exc_info:
        flow._ask_provider_fields(
            _Questionary(),
            get_provider_setup_spec("vllm"),
            OnboardOptions(model="stub-model"),
        )
    assert exc_info.value.section == "provider"


# ---------------------------------------------------------------------------
# C1-7 — wizard re-run seeds prompt defaults from the stored provider entry.
# ---------------------------------------------------------------------------


def _stored_config(provider: str, *, base_url: str, proxy: str) -> Any:
    return types.SimpleNamespace(
        llm=types.SimpleNamespace(provider=provider, base_url=base_url, proxy=proxy)
    )


def test_provider_rerun_seeds_base_url_prompt_and_keeps_proxy():
    """Re-running the wizard for an already-stored provider must default the
    Base URL prompt to the stored endpoint and keep the stored proxy —
    accepting the defaults used to silently resave the spec defaults."""

    captured: dict[str, Any] = {}

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            assert message == "Base URL"
            captured["default"] = kwargs.get("default")
            return _ValidatedPrompt([kwargs.get("default")], kwargs.get("validate"))

    answers = flow._ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("vllm"),
        OnboardOptions(model="stub-model"),
        config=_stored_config(
            "vllm",
            base_url="http://intranet.test:8000/v1",
            proxy="http://proxy.test:3128",
        ),
    )

    assert captured["default"] == "http://intranet.test:8000/v1"
    assert answers["base_url"] == "http://intranet.test:8000/v1"
    assert answers["proxy"] == "http://proxy.test:3128"


def test_provider_rerun_keeps_stored_custom_base_url_without_prompt(monkeypatch):
    """Providers that do not prompt for a base URL must still keep a stored
    custom endpoint and proxy on re-run instead of resaving spec defaults."""

    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)

    class _Questionary:
        def text(self, message: str, **_kwargs: Any):
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = flow._ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(api_key_env="OPENROUTER_API_KEY"),
        config=_stored_config(
            "openrouter",
            base_url="https://relay.internal.test/v1",
            proxy="http://proxy.test:3128",
        ),
    )

    assert answers["base_url"] == "https://relay.internal.test/v1"
    assert answers["proxy"] == "http://proxy.test:3128"


def test_provider_switch_ignores_other_providers_stored_endpoint(monkeypatch):
    """Stored values belong to the stored provider only — selecting a
    different provider must fall back to that provider's spec defaults."""

    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)

    class _Questionary:
        def text(self, message: str, **_kwargs: Any):
            raise AssertionError(f"unexpected text prompt: {message}")

    spec = get_provider_setup_spec("openrouter")
    answers = flow._ask_provider_fields(
        _Questionary(),
        spec,
        OnboardOptions(api_key_env="OPENROUTER_API_KEY"),
        config=_stored_config(
            "groq",
            base_url="https://groq-relay.internal.test/v1",
            proxy="http://proxy.test:3128",
        ),
    )

    assert answers["base_url"] == spec.default_base_url
    assert answers["proxy"] == ""


# ---------------------------------------------------------------------------
# C1-8 — channel edit: blank keeps the stored secret.
# ---------------------------------------------------------------------------


def test_channel_secret_with_stored_value_allows_blank_and_hints(monkeypatch):
    recorder = _RecordingConsole()
    monkeypatch.setattr(flow, "console", recorder)

    field = ChannelSetupField(
        name="token",
        label="Bot token",
        field_type="password",
        required=True,
        secret=True,
    )
    captured: dict[str, Any] = {}

    class _Questionary:
        def password(self, message: str, **kwargs: Any):
            assert message == "Bot token"
            captured["validate"] = kwargs.get("validate")
            return _ValidatedPrompt([""], kwargs.get("validate"))

    result = flow._ask_channel_field(_Questionary(), field, "xoxb-stored")

    # Blank resolves to the stored value at the prompt itself (not via the
    # mutation's by-name merge), so the keep promise also holds when the
    # operator renames the entry in the same edit.
    assert result == "xoxb-stored"
    validate = captured["validate"]
    assert validate is not None
    assert validate("") is True
    # Broken terminal pastes are still rejected even in keep-current mode.
    assert validate("\x1b[200~xoxb-new\x1b[201~") is not True
    assert "leave blank to keep the stored value" in recorder.joined()


def test_channel_secret_without_stored_value_still_requires_input():
    field = ChannelSetupField(
        name="token",
        label="Bot token",
        field_type="password",
        required=True,
        secret=True,
    )
    captured: dict[str, Any] = {}

    class _Questionary:
        def password(self, message: str, **kwargs: Any):
            captured["validate"] = kwargs.get("validate")
            return _ValidatedPrompt(["", "xoxb-new"], kwargs.get("validate"))

    result = flow._ask_channel_field(_Questionary(), field, None)

    assert result == "xoxb-new"
    assert captured["validate"]("") is not True


def test_channel_edit_blank_secrets_keep_stored_values(tmp_path, monkeypatch):
    """End-to-end edit: leaving both secret prompts blank must round-trip the
    stored credentials through the mutation layer's keep-current merge."""

    target = tmp_path / "c.toml"
    from opensquilla.onboarding.setup_engine import SetupEngine

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

    passwords: list[str] = []

    class _Answer:
        def __init__(self, value: Any) -> None:
            self.value = value

        def ask(self) -> Any:
            return self.value

    class _Questionary(types.SimpleNamespace):
        def select(self, message: str, **kwargs: Any):
            if message == "Channel to edit":
                return _Answer("slack-main")
            return _Answer(kwargs.get("default") or list(kwargs.get("choices") or [])[0])

        def text(self, message: str, **kwargs: Any):
            return _ValidatedPrompt([kwargs.get("default", "")], kwargs.get("validate"))

        def password(self, message: str, **kwargs: Any):
            passwords.append(message)
            return _ValidatedPrompt([""], kwargs.get("validate"))

        def confirm(self, message: str, **kwargs: Any):
            return _Answer(bool(kwargs.get("default")))

        def checkbox(self, message: str, **_kwargs: Any):
            raise AssertionError(f"unexpected checkbox prompt: {message}")

    monkeypatch.setitem(sys.modules, "questionary", _Questionary())

    flow.run_interactive_channel_edit(None, config_path=target)

    assert passwords, "the edit flow should have prompted for at least one secret"
    data = target.read_text()
    assert 'token = "xoxb-stored"' in data
    assert 'signing_secret = "ss-stored"' in data


# ---------------------------------------------------------------------------
# C1-9 — free-text model prompt must reject a blank submit (R9).
# ---------------------------------------------------------------------------


def test_free_text_model_prompt_rejects_blank_then_accepts_model():
    """Providers without a derivable default model raise ValueError('model
    is required') deep in the mutation after the operator already typed the
    API key — the model prompt must re-ask on a blank submit instead."""
    captured: dict[str, Any] = {}

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            assert message == "Model id"
            captured["validate"] = kwargs.get("validate")
            return _ValidatedPrompt(["", "   ", "my-model"], kwargs.get("validate"))

    result = flow._prompt_free_text_model(_Questionary())

    assert result == "my-model"
    validate = captured["validate"]
    assert validate is not None
    assert validate("") is not True
    assert validate("   ") is not True
    assert validate("my-model") is True


def test_free_text_model_prompt_cancel_raises_user_cancelled():
    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            return _ValidatedPrompt([None], kwargs.get("validate"))

    with pytest.raises(UserCancelledError) as exc_info:
        flow._prompt_free_text_model(_Questionary())
    assert exc_info.value.section == "provider"


# ---------------------------------------------------------------------------
# Wizard numeric channel fields share the headless --field coercer (F32).
# ---------------------------------------------------------------------------


def test_channel_int_field_blank_keeps_the_displayed_default():
    """Clearing the pre-filled default must keep it — the wizard twin of the
    headless contract where omitting --field keeps the stored/spec value.
    The old hand-rolled coercion silently turned a blank answer into 0."""

    field = ChannelSetupField(
        name="poll_timeout_s",
        label="Polling timeout (s)",
        field_type="int",
        required=False,
        default=30,
    )

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            return _ValidatedPrompt([""], kwargs.get("validate"))

    assert flow._ask_channel_field(_Questionary(), field, field.default) == 30


def test_channel_int_field_agrees_with_headless_coercion_semantics():
    """The wizard validator and the headless --field parser must accept and
    reject exactly the same spellings for the same spec field."""

    from opensquilla.cli.channel_fields import coerce_channel_field_value

    field = ChannelSetupField(
        name="intents",
        label="Intents bitmask",
        field_type="int",
        required=False,
        default=0,
    )
    validate = flow._channel_number_validator(field)

    import typer

    for raw in ("5", "-3", " 12 "):
        assert validate(raw) is True
        expected = coerce_channel_field_value("int", raw.strip(), field_name="intents")
        value, error = flow._coerce_channel_prompt_value(field, raw.strip())
        assert error is None
        assert value == expected

    for raw in ("abc", "7.5", "0x10"):
        wizard_verdict = validate(raw)
        assert wizard_verdict is not True
        with pytest.raises(typer.BadParameter) as exc_info:
            coerce_channel_field_value("int", raw, field_name="intents")
        # Same wording too, with the flag swapped for the field label the
        # wizard user actually sees.
        assert wizard_verdict == str(exc_info.value.message).replace(
            "--field intents", "Intents bitmask"
        )


def test_channel_int_field_error_names_the_label_not_the_flag():
    """The wizard user never typed --field: the re-prompt message must carry
    the field label while keeping the shared coercer's wording."""

    field = ChannelSetupField(
        name="intents",
        label="Intents bitmask",
        field_type="int",
        required=False,
        default=0,
    )
    verdict = flow._channel_number_validator(field)("banana")

    assert isinstance(verdict, str)
    assert "Intents bitmask" in verdict
    assert "--field" not in verdict
    assert "expects an integer" in verdict


def test_channel_float_field_agrees_with_headless_coercion_semantics():
    import typer

    from opensquilla.cli.channel_fields import coerce_channel_field_value

    field = ChannelSetupField(
        name="poll_idle_sleep_s",
        label="Poll idle sleep (s)",
        field_type="float",
        required=False,
        default=1.5,
    )

    class _Questionary:
        def text(self, message: str, **kwargs: Any):
            return _ValidatedPrompt(["not-a-number", "2.5"], kwargs.get("validate"))

    value = flow._ask_channel_field(_Questionary(), field, field.default)

    assert value == coerce_channel_field_value("float", "2.5", field_name=field.name)
    assert isinstance(value, float)

    # Rejection wording stays in lockstep with the headless parser as well.
    wizard_verdict = flow._channel_number_validator(field)("not-a-number")
    with pytest.raises(typer.BadParameter) as exc_info:
        coerce_channel_field_value("float", "not-a-number", field_name=field.name)
    assert wizard_verdict == str(exc_info.value.message).replace(
        f"--field {field.name}", field.label
    )
