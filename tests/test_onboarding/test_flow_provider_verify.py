"""Optional verify + discover in the interactive provider step (offline, stubbed).

Every probe/discovery call is stubbed at the ``flow._run_provider_probe`` /
``flow._run_provider_discovery`` seams — no test here may touch the network.
The quick-start contract under test: the verification adds ZERO new required
prompts (the only new prompt, "Save anyway?", appears solely on a failed
check and defaults to yes).
"""

from __future__ import annotations

import types
from io import StringIO
from typing import Any

import pytest
from rich.console import Console

from opensquilla.onboarding import flow
from opensquilla.onboarding.errors import UserCancelledError
from opensquilla.onboarding.flow import OnboardOptions, _ask_provider_fields
from opensquilla.onboarding.probe import (
    ProviderModelsDiscoverResult,
    ProviderProbeResult,
)
from opensquilla.onboarding.provider_specs import get_provider_setup_spec


class _Answer:
    def __init__(self, value: Any) -> None:
        self.value = value

    def ask(self) -> Any:
        return self.value


def _no_probe(**_kwargs: Any) -> Any:
    raise AssertionError("the provider probe must not run in this scenario")


def _no_discovery(**_kwargs: Any) -> Any:
    raise AssertionError("model discovery must not run in this scenario")


def _live_models(*rows: dict[str, Any]) -> ProviderModelsDiscoverResult:
    return ProviderModelsDiscoverResult(
        ok=True,
        provider_id="groq",
        source="live",
        models=list(rows),
    )


def _capture_console(monkeypatch) -> StringIO:
    output = StringIO()
    monkeypatch.setattr(
        flow,
        "console",
        Console(file=output, force_terminal=False, highlight=False),
    )
    return output


def _probing_spec(**overrides: Any) -> types.SimpleNamespace:
    """Synthetic direct-provider spec with a probe-able default model."""
    values: dict[str, Any] = {
        "provider_id": "fakeprov",
        "requires_api_key": True,
        "env_key": "FAKEPROV_API_KEY",
        "requires_base_url": False,
        "default_base_url": "",
        "router_supported": False,
        "can_probe": True,
        "default_direct_model": "fake-default-model",
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def test_discovery_upgrades_free_text_model_prompt_to_select(monkeypatch):
    _capture_console(monkeypatch)
    monkeypatch.setattr(flow, "_run_provider_probe", _no_probe)
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: _live_models(
            {"id": "llama-x", "contextWindow": 131_072},
            {"id": "llama-y", "contextWindow": 0},
        ),
    )
    captured: dict[str, Any] = {}

    class _Questionary:
        def select(self, message: str, **kwargs: Any) -> _Answer:
            captured["message"] = message
            captured["choices"] = kwargs.get("choices")
            return _Answer(kwargs["choices"][0])

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("groq"),
        OnboardOptions(api_key="sk-live"),
    )

    # The context window rides the label; a zero window keeps a bare id row;
    # the escape row is always last.
    assert captured["message"] == "Model"
    assert captured["choices"] == [
        "llama-x  ·  131,072 ctx",
        "llama-y",
        "Type a model id…",
    ]
    assert answers["model"] == "llama-x"
    assert answers["api_key"] == "sk-live"


def test_discovery_escape_row_falls_back_to_free_text(monkeypatch):
    _capture_console(monkeypatch)
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: _live_models({"id": "llama-x", "contextWindow": 131_072}),
    )

    class _Questionary:
        def select(self, message: str, **kwargs: Any) -> _Answer:
            assert message == "Model"
            return _Answer("Type a model id…")

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Model id"
            return _Answer("custom/typed-model")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("groq"),
        OnboardOptions(api_key="sk-live"),
    )

    assert answers["model"] == "custom/typed-model"


def test_discovery_without_models_keeps_free_text_prompt(monkeypatch):
    _capture_console(monkeypatch)
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: ProviderModelsDiscoverResult(
            ok=True, provider_id="groq", source="none"
        ),
    )

    class _Questionary:
        def select(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected select prompt: {message}")

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Model id"
            return _Answer("typed-model")

        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("groq"),
        OnboardOptions(api_key="sk-live"),
    )

    assert answers["model"] == "typed-model"


def test_failed_connection_check_shows_detail_and_never_blocks(monkeypatch):
    output = _capture_console(monkeypatch)
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: ProviderModelsDiscoverResult(
            ok=False,
            provider_id="groq",
            failure_kind="auth_invalid",
            detail="No API key available (checked $GROQ_API_KEY).",
        ),
    )
    prompts: list[str] = []

    class _Questionary:
        def confirm(self, message: str, **kwargs: Any) -> _Answer:
            prompts.append(message)
            assert message == "Save anyway?"
            # Offline setup must keep working: the default answer is yes.
            assert kwargs.get("default") is True
            return _Answer(True)

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Model id"
            return _Answer("typed-model")

        def select(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected select prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("groq"),
        OnboardOptions(api_key="sk-live"),
    )

    assert prompts == ["Save anyway?"]
    assert answers["model"] == "typed-model"
    out = output.getvalue()
    assert "Checking the connection…" in out
    assert "Could not verify groq" in out
    assert "No API key available" in out


def test_save_anyway_declined_cancels_the_provider_section(monkeypatch):
    _capture_console(monkeypatch)
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: ProviderModelsDiscoverResult(
            ok=False,
            provider_id="groq",
            failure_kind="auth_invalid",
            detail="No API key available (checked $GROQ_API_KEY).",
        ),
    )

    class _Questionary:
        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Save anyway?"
            return _Answer(False)

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

    with pytest.raises(UserCancelledError) as exc_info:
        _ask_provider_fields(
            _Questionary(),
            get_provider_setup_spec("groq"),
            OnboardOptions(api_key="sk-live"),
        )
    assert exc_info.value.section == "provider"


def test_probe_runs_with_default_model_before_discovery(monkeypatch):
    output = _capture_console(monkeypatch)
    probe_calls: list[dict[str, Any]] = []

    def fake_probe(**kwargs: Any) -> ProviderProbeResult:
        probe_calls.append(kwargs)
        return ProviderProbeResult(
            ok=True, provider_id=kwargs["provider_id"], model=kwargs["model"]
        )

    monkeypatch.setattr(flow, "_run_provider_probe", fake_probe)
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: _live_models({"id": "fake-model-a", "contextWindow": 8192}),
    )

    class _Questionary:
        def select(self, message: str, **kwargs: Any) -> _Answer:
            assert message == "Model"
            return _Answer(kwargs["choices"][0])

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        _probing_spec(),
        OnboardOptions(api_key="sk-live"),
    )

    assert [call["model"] for call in probe_calls] == ["fake-default-model"]
    assert probe_calls[0]["api_key"] == "sk-live"
    assert answers["model"] == "fake-model-a"
    assert "connection verified" in output.getvalue()


def test_probe_failure_skips_discovery_and_offers_save_anyway(monkeypatch):
    output = _capture_console(monkeypatch)
    monkeypatch.setattr(
        flow,
        "_run_provider_probe",
        lambda **kwargs: ProviderProbeResult(
            ok=False,
            provider_id=kwargs["provider_id"],
            model=kwargs["model"],
            failure_kind="auth_invalid",
            message="Incorrect API key provided",
        ),
    )
    monkeypatch.setattr(flow, "_run_provider_discovery", _no_discovery)

    class _Questionary:
        def confirm(self, message: str, **kwargs: Any) -> _Answer:
            assert message == "Save anyway?"
            assert kwargs.get("default") is True
            return _Answer(True)

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Model id"
            return _Answer("typed-model")

        def select(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected select prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        _probing_spec(),
        OnboardOptions(api_key="sk-bad"),
    )

    assert answers["model"] == "typed-model"
    assert "Could not verify fakeprov" in output.getvalue()
    assert "Incorrect API key provided" in output.getvalue()


def test_router_supported_provider_skips_verify_and_discovery(monkeypatch):
    monkeypatch.setattr(flow, "_run_provider_probe", _no_probe)
    monkeypatch.setattr(flow, "_run_provider_discovery", _no_discovery)

    class _Questionary:
        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

        def select(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(api_key="sk-live"),
    )

    assert answers["model"] == ""


def test_explicit_model_option_skips_verify_and_discovery(monkeypatch):
    monkeypatch.setattr(flow, "_run_provider_probe", _no_probe)
    monkeypatch.setattr(flow, "_run_provider_discovery", _no_discovery)

    class _Questionary:
        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("groq"),
        OnboardOptions(api_key="sk-live", model="preset-model"),
    )

    assert answers["model"] == "preset-model"


def test_unprobeable_spec_keeps_free_text_prompt(monkeypatch):
    monkeypatch.setattr(flow, "_run_provider_probe", _no_probe)
    monkeypatch.setattr(flow, "_run_provider_discovery", _no_discovery)

    class _Questionary:
        def text(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Model id"
            return _Answer("typed-model")

    answers = _ask_provider_fields(
        _Questionary(),
        _probing_spec(can_probe=False),
        OnboardOptions(api_key="sk-live"),
    )

    assert answers["model"] == "typed-model"


def test_broken_discovery_machinery_degrades_to_free_text(monkeypatch):
    # The seam returns None when the discovery call itself blew up; the flow
    # must degrade to the plain free-text prompt without any extra prompt.
    _capture_console(monkeypatch)
    monkeypatch.setattr(flow, "_run_provider_discovery", lambda **_kw: None)

    class _Questionary:
        def text(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Model id"
            return _Answer("typed-model")

        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("groq"),
        OnboardOptions(api_key="sk-live"),
    )

    assert answers["model"] == "typed-model"
