"""Wizard re-runs must seed prompts from the stored config, not factory
defaults, and channel edits must survive a rename with blank secrets.

Regression coverage for the destructive-re-save class: pressing Enter
through a search or image-generation wizard re-run used to persist factory
defaults over the operator's stored settings, and renaming a channel while
leaving a secret blank (as the wizard hint instructs) crashed with an
uncaught ValueError because the keep-current merge was keyed to the payload
name.
"""

from __future__ import annotations

import sys
import tomllib
import types
from typing import Any

from opensquilla.onboarding import flow
from opensquilla.onboarding.config_store import load_config
from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
)
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec


class _Answer:
    def __init__(self, value: Any) -> None:
        self.value = value

    def ask(self) -> Any:
        return self.value


class _RecordingConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message: str = "", *_a, **_kw) -> None:
        self.messages.append(str(message))

    def joined(self) -> str:
        return "\n".join(self.messages)


class _EnterThroughQuestionary(types.SimpleNamespace):
    """Answers every prompt with its default (a plain Enter), recording the
    defaults so tests can assert what the wizard offered."""

    def __init__(self, *, password_value: str = "sk-new") -> None:
        super().__init__()
        self.defaults: dict[str, Any] = {}
        self._password_value = password_value

    def select(self, message, **kwargs):
        self.defaults[message] = kwargs.get("default")
        choices = list(kwargs.get("choices") or [])
        return _Answer(kwargs.get("default") or (choices[0] if choices else None))

    def text(self, message, **kwargs):
        self.defaults[message] = kwargs.get("default")
        return _Answer(kwargs.get("default"))

    def confirm(self, message, **kwargs):
        self.defaults[message] = kwargs.get("default")
        return _Answer(kwargs.get("default"))

    def password(self, message, **kwargs):
        self.defaults[message] = None
        return _Answer(self._password_value)

    def checkbox(self, message, **kwargs):
        raise AssertionError(f"unexpected checkbox prompt: {message}")


# ---------------------------------------------------------------------------
# R7 — search wizard re-run seeds stored values.
# ---------------------------------------------------------------------------


_STORED_SEARCH_TOML = (
    'search_provider = "brave"\n'
    'search_api_key = "brave-stored-key"\n'
    "search_max_results = 10\n"
    'search_proxy = "http://127.0.0.1:7890"\n'
    "search_use_env_proxy = true\n"
    'search_fallback_policy = "network"\n'
    "search_diagnostics = true\n"
)


def test_search_fields_seed_defaults_from_stored_config(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    target = tmp_path / "c.toml"
    target.write_text(_STORED_SEARCH_TOML, encoding="utf-8")
    cfg = load_config(target)

    q = _EnterThroughQuestionary(password_value="brave-rotated-key")
    answers = flow._ask_search_fields(q, get_search_provider_setup_spec("brave"), cfg)

    # An Enter-through key rotation keeps every stored global setting.
    assert answers["api_key"] == "brave-rotated-key"
    assert answers["max_results"] == 10
    assert answers["proxy"] == "http://127.0.0.1:7890"
    assert answers["use_env_proxy"] is True
    assert answers["fallback_policy"] == "network"
    assert answers["diagnostics"] is True
    assert q.defaults["Max search results"] == "10"
    assert q.defaults["Search HTTP proxy"] == "http://127.0.0.1:7890"


def test_search_configure_rerun_enter_through_keeps_stored_settings(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    target = tmp_path / "c.toml"
    target.write_text(_STORED_SEARCH_TOML, encoding="utf-8")
    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "console", _RecordingConsole())

    class _Q(_EnterThroughQuestionary):
        def select(self, message, **kwargs):
            if message == "Search provider":
                return _Answer("brave (Brave Search)")
            return super().select(message, **kwargs)

    monkeypatch.setitem(
        sys.modules, "questionary", _Q(password_value="brave-rotated-key")
    )

    flow.run_interactive_search_configure(config_path=target)

    data = tomllib.loads(target.read_text())
    assert data["search_api_key"] == "brave-rotated-key"
    assert data["search_max_results"] == 10
    assert data["search_proxy"] == "http://127.0.0.1:7890"
    assert data["search_use_env_proxy"] is True
    assert data["search_fallback_policy"] == "network"
    assert data["search_diagnostics"] is True


# ---------------------------------------------------------------------------
# R7 — image-generation wizard re-run seeds stored values.
# ---------------------------------------------------------------------------


def test_image_generation_fields_seed_defaults_from_stored_config(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    target = tmp_path / "c.toml"
    target.write_text(
        "[image_generation]\n"
        "enabled = false\n"
        'primary = "openai/custom-image-model"\n'
        "[image_generation.providers.openai]\n"
        'api_key = "sk-image-old"\n'
        'base_url = "https://images.example.test/v1"\n',
        encoding="utf-8",
    )
    cfg = load_config(target)

    q = _EnterThroughQuestionary(password_value="sk-image-new")
    answers = flow._ask_image_generation_fields(
        q, get_image_generation_provider_setup_spec("openai"), cfg
    )

    # An Enter-through key rotation keeps the stored custom model, base URL,
    # and the deliberate enabled=false decision.
    assert answers["primary"] == "openai/custom-image-model"
    assert answers["base_url"] == "https://images.example.test/v1"
    assert answers["enabled"] is False
    assert q.defaults["Primary image model"] == "openai/custom-image-model"
    assert q.defaults["Image base URL"] == "https://images.example.test/v1"
    assert q.defaults["Image generation enabled?"] is False


def test_image_generation_fields_fresh_config_defaults_unchanged(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    spec = get_image_generation_provider_setup_spec("openai")

    q = _EnterThroughQuestionary(password_value="sk-image-first")
    answers = flow._ask_image_generation_fields(q, spec, GatewayConfig())

    assert answers["primary"] == spec.default_model
    assert answers["base_url"] == spec.default_base_url
    assert answers["enabled"] is True


# ---------------------------------------------------------------------------
# R8 — channel edit rename with a blank (keep-current) secret.
# ---------------------------------------------------------------------------


def test_channel_edit_rename_with_blank_secret_keeps_token(tmp_path, monkeypatch):
    """Following the wizard's own "leave blank to keep the stored value"
    hint while renaming the entry used to crash with an uncaught
    ValueError ("channel field 'token' requires a non-empty value") because
    the keep-current merge looked up the stored entry by the NEW name."""
    from opensquilla.onboarding.setup_engine import SetupEngine

    target = tmp_path / "c.toml"
    engine = SetupEngine(path=target)
    engine.apply(
        "channels",
        {"type": "telegram", "name": "t1", "token": "tg-stored-token"},
    )
    engine.persist()

    monkeypatch.setattr(flow, "_is_tty", lambda: True)
    monkeypatch.setattr(flow, "console", _RecordingConsole())

    class _Q(_EnterThroughQuestionary):
        def select(self, message, **kwargs):
            if message == "Channel to edit":
                return _Answer("t1")
            return super().select(message, **kwargs)

        def text(self, message, **kwargs):
            if message == "Channel name":
                return _Answer("t2")  # rename in the same edit
            return super().text(message, **kwargs)

        def password(self, message, **kwargs):
            return _Answer("")  # blank = keep stored value, per the hint

    monkeypatch.setitem(sys.modules, "questionary", _Q())

    flow.run_interactive_channel_edit(None, config_path=target)

    entries = {
        e.name: e for e in load_config(target).channels.channels
    }
    assert "t2" in entries
    assert entries["t2"].token == "tg-stored-token"


# ---------------------------------------------------------------------------
# Provider re-save keeps the stored model (router-supported and direct).
# ---------------------------------------------------------------------------


def _stored_llm_config(provider: str, model: str) -> Any:
    from opensquilla.gateway.config import GatewayConfig

    return GatewayConfig(llm={"provider": provider, "model": model, "api_key": "sk-old"})


def test_same_provider_resave_passes_keep_current_model_not_reset_sentinel(
    monkeypatch,
):
    """A same-provider re-save of a router-supported provider must send
    ``model=None`` (the mutation layer's keep-current) — the legacy ``""``
    sentinel means "derive the tier default", which silently swapped a
    hand-set ``llm.model`` on an Enter-through key rotation."""
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)

    class _Questionary:
        def text(self, message, **_kwargs):
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = flow._ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        flow.OnboardOptions(api_key_env="OPENROUTER_API_KEY"),
        config=_stored_llm_config("openrouter", "corp/pinned-model"),
    )

    assert answers["model"] is None, (
        "same-provider re-save must engage keep-current, not the reset sentinel"
    )


def test_provider_switch_keeps_the_legacy_derive_default_sentinel(monkeypatch):
    """Switching providers has no stored model to keep: the legacy ``""``
    (derive the provider's default model) must stay pinned."""
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)

    class _Questionary:
        def text(self, message, **_kwargs):
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = flow._ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        flow.OnboardOptions(api_key_env="OPENROUTER_API_KEY"),
        config=_stored_llm_config("groq", "some/other-model"),
    )

    assert answers["model"] == ""


def test_same_provider_enter_through_resave_keeps_stored_model_end_to_end(
    monkeypatch,
):
    """The mutation layer really keeps the stored model for the wizard's
    keep-current answer — the ``""`` regression resets it to the derived
    tier default."""
    from opensquilla.onboarding.mutations import upsert_llm_provider
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)
    stored = _stored_llm_config("openrouter", "corp/pinned-model")

    class _Questionary:
        def text(self, message, **_kwargs):
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = flow._ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("openrouter"),
        flow.OnboardOptions(api_key_env="OPENROUTER_API_KEY"),
        config=stored,
    )
    res = upsert_llm_provider(
        stored,
        provider_id="openrouter",
        model=answers["model"],
        api_key=answers.get("api_key", ""),
        api_key_env=answers.get("api_key_env", ""),
        base_url=answers.get("base_url", ""),
        proxy=answers.get("proxy", ""),
    )

    assert res.config.llm.model == "corp/pinned-model"


def test_direct_provider_free_text_model_prompt_seeds_the_stored_model(
    monkeypatch,
):
    """On a same-provider re-run the free-text "Model id" prompt must default
    to the stored model so plain Enter keeps it instead of retyping it."""
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)
    monkeypatch.setattr(flow, "_run_provider_discovery", lambda **_kw: None)

    q = _EnterThroughQuestionary(password_value="sk-rotated")
    answers = flow._ask_provider_fields(
        q,
        get_provider_setup_spec("groq"),
        flow.OnboardOptions(),
        config=_stored_llm_config("groq", "stored-direct-model"),
    )

    assert q.defaults["Model id"] == "stored-direct-model"
    assert answers["model"] == "stored-direct-model"


def test_direct_provider_discovery_select_preselects_the_stored_model(
    monkeypatch,
):
    """When live discovery upgrades the prompt to a select, the stored model
    must be pre-selected — defaulting to the first discovered row switches
    models on an Enter-through re-save."""
    from opensquilla.onboarding.probe import ProviderModelsDiscoverResult
    from opensquilla.onboarding.provider_specs import get_provider_setup_spec

    monkeypatch.setattr(flow, "_run_provider_probe", lambda **_kw: None)
    monkeypatch.setattr(
        flow,
        "_run_provider_discovery",
        lambda **_kw: ProviderModelsDiscoverResult(
            ok=True,
            provider_id="groq",
            source="live",
            models=[
                {"id": "llama-first", "contextWindow": 0},
                {"id": "stored-direct-model", "contextWindow": 0},
            ],
        ),
    )

    captured: dict[str, Any] = {}

    class _Questionary:
        def select(self, message, **kwargs):
            assert message == "Model"
            captured["default"] = kwargs.get("default")
            return _Answer(kwargs.get("default"))

        def text(self, message, **_kwargs):
            raise AssertionError(f"unexpected text prompt: {message}")

    answers = flow._ask_provider_fields(
        _Questionary(),
        get_provider_setup_spec("groq"),
        flow.OnboardOptions(api_key="sk-live"),
        config=_stored_llm_config("groq", "stored-direct-model"),
    )

    assert captured["default"] == "stored-direct-model"
    assert answers["model"] == "stored-direct-model"


# ---------------------------------------------------------------------------
# Router re-enable keeps a preserved operator-authored ladder.
# ---------------------------------------------------------------------------


_HAND_TIERS = {
    "c0": {"provider": "openrouter", "model": "hand-c0"},
    "c1": {"provider": "openrouter", "model": "hand-c1"},
    "c2": {"provider": "openrouter", "model": "hand-c2"},
    "c3": {"provider": "openrouter", "model": "hand-c3"},
}


def _config_with_preserved_hand_ladder(*, enabled: bool) -> Any:
    from opensquilla.gateway.config import GatewayConfig

    return GatewayConfig(
        llm={"provider": "openrouter", "model": "hand-c1", "api_key": "sk-old"},
        squilla_router={
            "enabled": enabled,
            "tier_profile": None,
            "tiers": {name: dict(tier) for name, tier in _HAND_TIERS.items()},
        },
    )


class _RouterEnterThroughQuestionary:
    def select(self, message, **kwargs):
        if message == "Router mode":
            return _Answer("SquillaRouter")
        if message == "Default text model":
            return _Answer(kwargs.get("default"))
        raise AssertionError(f"unexpected select prompt: {message}")

    def confirm(self, message, **kwargs):
        if message == "Edit router tier models now?":
            return _Answer(False)
        raise AssertionError(f"unexpected confirm prompt: {message}")


def test_router_reenable_over_preserved_hand_ladder_restores_it(monkeypatch):
    """Disabling the router preserves an operator-authored inline ladder so a
    later re-enable can restore it. The wizard's re-enable maps the
    "SquillaRouter" choice to the custom mode in that state — plain
    "recommended" would wipe the preserved ladder with the packaged profile,
    the exact silent reset the preservation exists to prevent."""
    from opensquilla.onboarding.mutations import upsert_router

    cfg = _config_with_preserved_hand_ladder(enabled=False)

    payload = flow._ask_router_fields(
        _RouterEnterThroughQuestionary(),
        cfg,
        provider_id="openrouter",
        requested_mode="recommended",
    )

    assert payload["mode"] == "custom"
    reenabled = upsert_router(
        cfg,
        mode=payload["mode"],
        default_tier=payload.get("defaultTier"),
        tiers=payload.get("tiers"),
    ).config
    assert reenabled.squilla_router.enabled is True
    for tier in ("c0", "c1", "c2", "c3"):
        assert reenabled.squilla_router.tiers[tier]["model"] == f"hand-{tier}"


def test_router_enter_through_on_enabled_hand_ladder_keeps_it(monkeypatch):
    """The hub Router section's Enter-through over an ENABLED hand-edited
    ladder must not reset it either."""
    payload = flow._ask_router_fields(
        _RouterEnterThroughQuestionary(),
        _config_with_preserved_hand_ladder(enabled=True),
        provider_id="openrouter",
        requested_mode="recommended",
    )

    assert payload["mode"] == "custom"


def test_router_explicit_recommended_still_resets_the_ladder(monkeypatch):
    """An explicit ``--router recommended`` is a deliberate reset request:
    the hand-customized guard must not override it."""
    payload = flow._ask_router_fields(
        _RouterEnterThroughQuestionary(),
        _config_with_preserved_hand_ladder(enabled=False),
        provider_id="openrouter",
        requested_mode="recommended",
        explicit_mode=True,
    )

    assert payload["mode"] == "recommended"


def test_router_custom_tier_edit_sends_the_full_effective_ladder(monkeypatch):
    """When the operator edits one tier over a preserved custom ladder, the
    payload must carry the FULL effective ladder: sending only the edited
    tier would merge it onto the packaged preset base and wipe the untouched
    stored tiers."""

    class _Questionary(_RouterEnterThroughQuestionary):
        def __init__(self) -> None:
            self._tier_picks = iter(["Route c2", "Done"])

        def select(self, message, **kwargs):
            if message == "Tier to edit":
                return _Answer(next(self._tier_picks))
            return super().select(message, **kwargs)

        def text(self, message, **kwargs):
            if message == "c2 provider":
                return _Answer(kwargs.get("default"))
            if message == "c2 model":
                return _Answer("edited-c2")
            raise AssertionError(f"unexpected text prompt: {message}")

        def confirm(self, message, **kwargs):
            if message == "Edit router tier models now?":
                return _Answer(True)
            raise AssertionError(f"unexpected confirm prompt: {message}")

    payload = flow._ask_router_fields(
        _Questionary(),
        _config_with_preserved_hand_ladder(enabled=False),
        provider_id="openrouter",
        requested_mode="recommended",
    )

    assert payload["mode"] == "custom"
    tiers = payload["tiers"]
    assert tiers["c2"]["model"] == "edited-c2"
    for untouched in ("c0", "c1", "c3"):
        assert tiers[untouched]["model"] == f"hand-{untouched}"
