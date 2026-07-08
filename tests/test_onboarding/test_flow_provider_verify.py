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


def test_router_supported_provider_probes_the_default_tier_model(monkeypatch):
    """A router-supported provider never types a direct model, so its bad
    keys used to surface only at the first chat: the pre-save probe was
    gated on a branch such a provider could never reach. It must now probe
    with the model the save will actually use — the default tier's model
    (the spec's ``default_direct_model``) — while still skipping discovery
    and adding zero prompts on success."""

    output = _capture_console(monkeypatch)
    probe_calls: list[dict[str, Any]] = []

    def fake_probe(**kwargs: Any) -> ProviderProbeResult:
        probe_calls.append(kwargs)
        return ProviderProbeResult(
            ok=True, provider_id=kwargs["provider_id"], model=kwargs["model"]
        )

    monkeypatch.setattr(flow, "_run_provider_probe", fake_probe)
    monkeypatch.setattr(flow, "_run_provider_discovery", _no_discovery)

    spec = get_provider_setup_spec("openrouter")

    class _Questionary:
        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

        def select(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected select prompt: {message}")

        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        spec,
        OnboardOptions(api_key="sk-live"),
    )

    assert spec.default_direct_model, "openrouter must expose a default tier model"
    assert [call["model"] for call in probe_calls] == [spec.default_direct_model]
    assert probe_calls[0]["api_key"] == "sk-live"
    # The router still drives model selection: no direct model is stored.
    assert answers["model"] == ""
    assert "connection verified" in output.getvalue()


def test_router_supported_provider_probe_failure_offers_save_anyway(monkeypatch):
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
    prompts: list[str] = []

    class _Questionary:
        def confirm(self, message: str, **kwargs: Any) -> _Answer:
            prompts.append(message)
            assert message == "Save anyway?"
            # Offline setup must keep working: the default answer is yes.
            assert kwargs.get("default") is True
            return _Answer(True)

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(api_key="sk-bad"),
    )

    assert prompts == ["Save anyway?"]
    assert answers["model"] == ""
    out = output.getvalue()
    assert "Could not verify openrouter" in out
    assert "Incorrect API key provided" in out


def test_router_supported_provider_probe_decline_cancels_provider_section(monkeypatch):
    _capture_console(monkeypatch)
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

    class _Questionary:
        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Save anyway?"
            return _Answer(False)

    with pytest.raises(UserCancelledError) as exc_info:
        _ask_provider_fields(
            _Questionary(),
            get_provider_setup_spec("openrouter"),
            OnboardOptions(api_key="sk-bad"),
        )
    assert exc_info.value.section == "provider"


def test_router_supported_provider_broken_probe_machinery_degrades_silently(monkeypatch):
    # ``None`` means the probe could not even be attempted — it must never
    # block the router-driven quick-start with an extra prompt.
    _capture_console(monkeypatch)
    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)
    monkeypatch.setattr(flow, "_run_provider_discovery", _no_discovery)

    class _Questionary:
        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        OnboardOptions(api_key="sk-live"),
    )

    assert answers["model"] == ""


def test_router_supported_spec_without_default_model_skips_probe(monkeypatch):
    """When no model can be determined for the probe there is nothing to
    verify — behavior stays exactly as before the router-provider check."""

    monkeypatch.setattr(flow, "_run_provider_probe", _no_probe)
    monkeypatch.setattr(flow, "_run_provider_discovery", _no_discovery)

    class _Questionary:
        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

    answers = _ask_provider_fields(
        _Questionary(),
        _probing_spec(router_supported=True, default_direct_model=""),
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


def test_wizard_probe_suppresses_provider_log_noise(monkeypatch, capsys):
    # The provider layer logs request/response details via structlog, which is
    # unconfigured in the wizard process and would print raw records into the
    # interactive prompt stream mid-probe. The seam must silence them for the
    # duration of the probe and restore logging afterwards.
    import structlog

    from opensquilla.onboarding import probe as probe_module

    sentinel = object()

    async def _noisy_probe(**_kwargs: Any) -> Any:
        structlog.get_logger("opensquilla.provider").warning(
            "provider.chat_http_error", status_code=401, response_body="synthetic-401-body"
        )
        return sentinel

    monkeypatch.setattr(probe_module, "probe_llm_provider", _noisy_probe)

    config_before = dict(structlog.get_config())
    result = flow._run_provider_probe(provider_id="openrouter", model="dummy/model")

    captured = capsys.readouterr()
    assert result is sentinel
    assert "chat_http_error" not in captured.out + captured.err
    assert "synthetic-401-body" not in captured.out + captured.err
    # The suppression must be scoped to the probe: whatever structlog config
    # was active before (test runs share the process) is restored verbatim.
    assert dict(structlog.get_config()) == config_before


def test_wizard_discovery_suppresses_provider_log_noise(monkeypatch, capsys):
    import structlog

    from opensquilla.onboarding import probe as probe_module

    sentinel = object()

    async def _noisy_discovery(**_kwargs: Any) -> Any:
        structlog.get_logger("opensquilla.provider").warning(
            "provider.models_http_error", status_code=401
        )
        return sentinel

    monkeypatch.setattr(probe_module, "discover_provider_models", _noisy_discovery)

    result = flow._run_provider_discovery(provider_id="openrouter")

    captured = capsys.readouterr()
    assert result is sentinel
    assert "models_http_error" not in captured.out + captured.err


def test_quiet_provider_logs_is_a_plain_module_level_contextmanager():
    """The suppression seam is one directly decorated function, not a factory
    returning a freshly decorated closure per call: the decorated form keeps
    the call sites identical while dropping the per-probe indirection."""
    import inspect

    # ``contextlib.contextmanager`` exposes the generator via ``__wrapped__``;
    # the old factory shape had no such attribute on the module-level name.
    wrapped = getattr(flow._quiet_provider_logs, "__wrapped__", None)
    assert wrapped is not None
    assert inspect.isgeneratorfunction(wrapped)

    # And it still behaves as a context manager end to end.
    import structlog

    config_before = dict(structlog.get_config())
    with flow._quiet_provider_logs():
        assert dict(structlog.get_config()) != config_before
    assert dict(structlog.get_config()) == config_before


def test_direct_and_router_checks_share_the_probe_and_confirm_helper(monkeypatch):
    """Both provider checks must run through _probe_and_confirm so a UX fix
    (wording, retry, redaction) lands on the direct and the router path at
    once instead of drifting between two copies."""
    calls: list[str] = []
    real = flow._probe_and_confirm

    def _tracing(questionary, spec, answers):
        calls.append(spec.provider_id)
        return real(questionary, spec, answers)

    monkeypatch.setattr(flow, "_probe_and_confirm", _tracing)
    monkeypatch.setattr(
        flow,
        "_run_provider_probe",
        lambda **kwargs: ProviderProbeResult(
            ok=True, provider_id=kwargs["provider_id"], model=kwargs["model"]
        ),
    )
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: _live_models({"id": "fake-model-a", "contextWindow": 8192}),
    )
    _capture_console(monkeypatch)

    class _Questionary:
        def select(self, message: str, **kwargs: Any) -> _Answer:
            assert message == "Model"
            return _Answer(kwargs["choices"][0])

        def text(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected text prompt: {message}")

        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

    # Direct-provider path.
    flow._ask_direct_provider_model(
        _Questionary(), _probing_spec(), {"api_key": "sk-live"}
    )
    # Router-provider path.
    flow._verify_router_provider_connection(
        _Questionary(),
        _probing_spec(provider_id="fakerouterprov", router_supported=True),
        {"api_key": "sk-live"},
    )

    assert calls == ["fakeprov", "fakerouterprov"]


def test_probe_and_confirm_save_anyway_decline_cancels(monkeypatch):
    _capture_console(monkeypatch)
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

    class _Questionary:
        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            assert message == "Save anyway?"
            return _Answer(False)

    with pytest.raises(UserCancelledError) as exc_info:
        flow._probe_and_confirm(_Questionary(), _probing_spec(), {"api_key": "sk-bad"})
    assert exc_info.value.section == "provider"


def test_probe_keyboard_interrupt_skips_the_check_not_the_wizard(monkeypatch):
    """Ctrl+C while the live probe waits on a stalled network interrupts the
    CHECK, not the setup session: ``_run_provider_probe`` must degrade to
    ``None`` (probe skipped) instead of letting KeyboardInterrupt reach the
    CLI boundary and discard the operator's typed answers."""
    from opensquilla.onboarding import probe as probe_module

    output = _capture_console(monkeypatch)

    async def _stalled_probe(**_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(probe_module, "probe_llm_provider", _stalled_probe)

    result = flow._run_provider_probe(
        provider_id="openrouter", model="dummy/model", api_key="sk-live"
    )

    assert result is None
    assert "connection check skipped" in output.getvalue()


def test_discovery_keyboard_interrupt_skips_discovery_not_the_wizard(monkeypatch):
    from opensquilla.onboarding import probe as probe_module

    output = _capture_console(monkeypatch)

    async def _stalled_discovery(**_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(probe_module, "discover_provider_models", _stalled_discovery)

    result = flow._run_provider_discovery(provider_id="groq", api_key="sk-live")

    assert result is None
    assert "model discovery skipped" in output.getvalue()


def test_router_check_interrupted_probe_saves_without_save_anyway_prompt(monkeypatch):
    """An interrupted probe is check-skipped inside _probe_and_confirm: the
    router-provider verification must continue to the save with no failure
    panel, no "Save anyway?" prompt, and no exception."""
    from opensquilla.onboarding import probe as probe_module

    output = _capture_console(monkeypatch)

    async def _stalled_probe(**_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(probe_module, "probe_llm_provider", _stalled_probe)

    class _Questionary:
        def confirm(self, message: str, **_kwargs: Any) -> _Answer:
            raise AssertionError(f"unexpected confirm prompt: {message}")

    flow._verify_router_provider_connection(
        _Questionary(),
        _probing_spec(provider_id="fakerouterprov", router_supported=True),
        {"api_key": "sk-live"},
    )

    out = output.getvalue()
    assert "connection check skipped" in out
    assert "connection verified" not in out
    assert "Save anyway?" not in out
