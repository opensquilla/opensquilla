"""Cross-provider router tiers (R3) with provider-state safety (R2).

The preview flag ``squilla_router.cross_provider_tiers`` lets a routed tier
execute on its own provider, with credentials from ``[llm_profiles.<id>]``
or the registry env key. Provider-bound continuity state (thinking blocks /
thought signatures) minted by another provider is never replayed to the
tier's provider.
"""

from __future__ import annotations

from opensquilla.engine.selector_override import (
    apply_model_override,
    cross_provider_tier_config,
    resolve_tier_provider_config,
)
from opensquilla.gateway.config import GatewayConfig, LlmProviderProfile
from opensquilla.provider.anthropic import _build_message_payload
from opensquilla.provider.openai import _build_openai_messages
from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig
from opensquilla.provider.types import (
    ContentBlockText,
    ContentBlockThinking,
    ContentBlockToolUse,
    Message,
)

# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def _config_with_flag(**profiles: LlmProviderProfile) -> GatewayConfig:
    cfg = GatewayConfig()
    cfg.squilla_router.cross_provider_tiers = True
    cfg.llm_profiles = dict(profiles)
    return cfg


def test_profile_credentials_resolve(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = _config_with_flag(openai=LlmProviderProfile(api_key="sk-profile"))
    resolved = resolve_tier_provider_config(cfg, "openai", "gpt-5.4-nano")
    assert resolved is not None
    assert resolved.provider == "openai"
    assert resolved.api_key == "sk-profile"
    assert resolved.base_url == "https://api.openai.com/v1"
    assert resolved.replay_provider_state is False


def test_env_fallback_resolves(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    cfg = _config_with_flag()
    resolved = resolve_tier_provider_config(cfg, "deepseek", "deepseek-v4-flash")
    assert resolved is not None
    assert resolved.api_key == "sk-env"
    assert resolved.base_url == "https://api.deepseek.com"


def test_unresolvable_credentials_return_none(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = _config_with_flag()
    assert resolve_tier_provider_config(cfg, "openai", "gpt-5.4-nano") is None
    assert resolve_tier_provider_config(cfg, "no-such-provider", "m") is None


# ---------------------------------------------------------------------------
# Execution gate
# ---------------------------------------------------------------------------


def test_gate_requires_flag(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cfg = GatewayConfig()  # flag off
    metadata = {"routing_applied": True, "routed_provider": "openai"}
    assert (
        cross_provider_tier_config(cfg, metadata, "gpt-5.4-nano", active_provider_id="openrouter")
        is None
    )


def test_gate_executes_when_flag_on(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cfg = _config_with_flag()
    metadata = {"routing_applied": True, "routed_provider": "openai"}
    resolved = cross_provider_tier_config(
        cfg, metadata, "gpt-5.4-nano", active_provider_id="openrouter"
    )
    assert resolved is not None
    assert resolved.provider == "openai"


def test_gate_skips_same_provider(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cfg = _config_with_flag()
    metadata = {"routing_applied": True, "routed_provider": "openrouter"}
    assert (
        cross_provider_tier_config(cfg, metadata, "m", active_provider_id="openrouter") is None
    )


def test_gate_blocked_by_continuity_diagnostic(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cfg = _config_with_flag()
    metadata = {
        "routing_applied": True,
        "routed_provider": "openai",
        "provider_state_continuity": {"decision": "discard_provider_state"},
    }
    assert (
        cross_provider_tier_config(cfg, metadata, "m", active_provider_id="openrouter") is None
    )
    assert metadata["routed_provider_blocked"] == "provider_state_continuity"


# ---------------------------------------------------------------------------
# Selector application
# ---------------------------------------------------------------------------


def test_override_provider_config_switches_chain_head() -> None:
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig("openrouter", "deepseek/deepseek-v4-pro", api_key="or-key")
        )
    )
    tier_cfg = ProviderConfig(
        "openai",
        "gpt-5.4-nano",
        api_key="oa-key",
        base_url="https://api.openai.com/v1",
        replay_provider_state=False,
    )
    selector.override_provider_config(tier_cfg)
    assert selector.active_provider_id == "openai"
    assert selector.current_config.api_key == "oa-key"
    # The previous primary remains reachable as a fallback.
    assert selector.has_fallback()
    assert selector._chain[1].provider == "openrouter"


def test_apply_model_override_uses_tier_config() -> None:
    selector = ModelSelector(
        SelectorConfig(primary=ProviderConfig("openrouter", "m", api_key="k"))
    )
    metadata: dict[str, object] = {"routing_applied": True}
    tier_cfg = ProviderConfig(
        "openai", "gpt-5.4-nano", api_key="oa", base_url="https://api.openai.com/v1"
    )
    provider = apply_model_override(
        selector,
        "gpt-5.4-nano",
        turn_metadata=metadata,
        realign_routed_model=False,
        tier_provider_config=tier_cfg,
    )
    assert provider is not None
    assert metadata["routed_provider_applied"] == "openai"
    assert selector.active_provider_id == "openai"


# ---------------------------------------------------------------------------
# R2: provider-bound state never crosses providers
# ---------------------------------------------------------------------------

_SIGNED_ASSISTANT = Message(
    role="assistant",
    content=[
        ContentBlockThinking(thinking="chain of thought", signature="sig-anthropic"),
        ContentBlockText(text="doing it"),
        ContentBlockToolUse(id="call_1", name="search", input={"q": "x"}),
    ],
)


def test_anthropic_drops_foreign_thinking_blocks() -> None:
    replayed = _build_message_payload(_SIGNED_ASSISTANT, model="claude-x")
    assert any(part["type"] == "thinking" for part in replayed["content"])

    stripped = _build_message_payload(
        _SIGNED_ASSISTANT, model="claude-x", replay_provider_state=False
    )
    assert not any(part["type"] == "thinking" for part in stripped["content"])
    # Text and tool_use survive.
    assert any(part["type"] == "tool_use" for part in stripped["content"])


def test_openai_skips_foreign_thought_signature() -> None:
    (replayed,) = _build_openai_messages(_SIGNED_ASSISTANT)
    assert (
        replayed["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
        == "sig-anthropic"
    )

    (stripped,) = _build_openai_messages(_SIGNED_ASSISTANT, replay_provider_state=False)
    assert "extra_content" not in stripped["tool_calls"][0]
