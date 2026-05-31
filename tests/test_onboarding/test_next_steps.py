"""Tests for onboarding next-step guidance."""

from __future__ import annotations


def test_next_steps_uses_powershell_env_hint_on_windows(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    cfg = GatewayConfig()
    cfg.llm.api_key = ""
    cfg.llm.api_key_env = "OPENROUTER_API_KEY"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(next_steps.platform, "system", lambda: "Windows")

    text = next_steps.format_next_steps(cfg, config_path="C:/tmp/config.toml")

    assert 'PowerShell: $env:OPENROUTER_API_KEY = "<your-key>"' in text
    assert "$OPENROUTER_API_KEY=<your-key>" not in text


def test_onboarding_finish_output_separates_summary_from_commands():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import format_next_steps

    text = format_next_steps(GatewayConfig(), config_path="C:/tmp/config.toml")

    assert text.startswith("Configuration summary:")
    assert "Next steps:" not in text
    assert "Commands:" in text
    assert "  Run gateway now: opensquilla gateway run" in text
    assert "  Start gateway in background: opensquilla gateway start --json" in text
    assert "  Restart running gateway: opensquilla gateway restart --json" in text
    assert "Reference:" in text
    assert "  Web UI: http://127.0.0.1:18791/control/setup" in text
    assert "uv run" not in text


def test_onboarding_finish_output_summarizes_all_capability_sections():
    from opensquilla.gateway.config import GatewayConfig, LlmProviderConfig
    from opensquilla.onboarding.next_steps import format_next_steps

    cfg = GatewayConfig()
    cfg.llm = LlmProviderConfig(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
    )
    cfg.image_generation.enabled = True
    cfg.image_generation.primary = "openai/gpt-image-1"
    cfg.image_generation.providers.openai.api_key = ""
    cfg.memory.embedding.provider = "openai"
    cfg.memory.embedding.remote.api_key = ""

    text = format_next_steps(cfg, config_path="/tmp/opensquilla/custom.toml")

    assert (
        "  Capabilities: Web search=Ready | Channels=Later | "
        "Image generation=Needs action | Memory embedding=Needs action"
    ) in text
    assert text.index("  Capabilities:") < text.index("Commands:")


def test_onboarding_finish_output_uses_product_router_label():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import format_next_steps

    text = format_next_steps(GatewayConfig(), config_path="/tmp/opensquilla/custom.toml")

    assert "  Router: SquillaRouter, default=t1" in text
    assert "profile=openrouter-mix" not in text


def test_onboarding_finish_output_keeps_explicit_config_in_gateway_commands():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import format_next_steps

    text = format_next_steps(GatewayConfig(), config_path="/tmp/opensquilla/custom.toml")

    assert (
        "  Run gateway now: opensquilla gateway run --config /tmp/opensquilla/custom.toml"
        in text
    )
    assert (
        "  Start gateway in background: "
        "opensquilla gateway start --json --config /tmp/opensquilla/custom.toml"
    ) in text
    assert (
        "  Restart running gateway: "
        "opensquilla gateway restart --json --config /tmp/opensquilla/custom.toml"
    ) in text


def test_onboarding_finish_output_uses_configured_web_setup_url():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import format_next_steps

    cfg = GatewayConfig(port=19999)
    cfg.control_ui.base_path = "/ops"

    text = format_next_steps(cfg)

    assert "  Web UI: http://127.0.0.1:19999/ops/setup" in text
    assert "  Web UI: http://127.0.0.1:18791/control/" not in text


def test_onboarding_finish_output_puts_missing_env_hint_in_commands(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    cfg = GatewayConfig()
    cfg.llm.api_key = ""
    cfg.llm.api_key_env = "OPENROUTER_API_KEY"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    text = next_steps.format_next_steps(cfg, config_path="C:/tmp/config.toml")

    commands = text.split("Commands:", 1)[1].split("Reference:", 1)[0]
    reference = text.split("Reference:", 1)[1]
    env_hint = next_steps._set_env_hint("OPENROUTER_API_KEY")
    assert f"Set key before starting gateway: {env_hint}" in commands
    assert "Set key before starting gateway" not in reference


def test_onboarding_finish_output_keeps_provider_key_url_as_reference():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import format_next_steps

    cfg = GatewayConfig()
    cfg.llm.provider = "openrouter"

    text = format_next_steps(cfg, config_path="C:/tmp/config.toml")

    assert "Reference:" in text
    assert "  Provider keys: https://openrouter.ai/keys" in text


def test_env_reference_warnings_cover_llm_and_search_missing_env(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import env_reference_warnings

    cfg = GatewayConfig()
    cfg.llm.api_key = ""
    cfg.llm.api_key_env = "OPENROUTER_API_KEY"
    cfg.search_provider = "brave"
    cfg.search_api_key = ""
    cfg.search_api_key_env = "BRAVE_SEARCH_API_KEY"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    warnings = env_reference_warnings(cfg)

    assert any(
        "LLM provider" in warning and "OPENROUTER_API_KEY" in warning
        for warning in warnings
    )
    assert any(
        "Search provider" in warning and "BRAVE_SEARCH_API_KEY" in warning
        for warning in warnings
    )


def test_env_reference_warnings_cover_image_and_memory_missing_env(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import env_reference_warnings

    cfg = GatewayConfig()
    cfg.image_generation.enabled = True
    cfg.image_generation.primary = "openrouter/google/gemini-3.1-flash-image-preview"
    cfg.image_generation.providers.openrouter.api_key = ""
    cfg.image_generation.providers.openrouter.api_key_env = "OPENSQUILLA_IMAGE_KEY"
    cfg.memory.embedding.provider = "openai"
    cfg.memory.embedding.remote.api_key = ""
    cfg.memory.embedding.remote.api_key_env = "OPENAI_EMBEDDINGS_API_KEY"
    monkeypatch.delenv("OPENSQUILLA_IMAGE_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDINGS_API_KEY", raising=False)

    warnings = env_reference_warnings(cfg)

    assert any(
        "Image generation provider" in warning and "OPENSQUILLA_IMAGE_KEY" in warning
        for warning in warnings
    )
    assert any(
        "Memory embedding" in warning and "OPENAI_EMBEDDINGS_API_KEY" in warning
        for warning in warnings
    )


def test_env_reference_warnings_do_not_warn_for_image_generation_missing_env_when_disabled(
    monkeypatch,
):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import env_reference_warnings

    cfg = GatewayConfig()
    cfg.image_generation.enabled = False
    cfg.image_generation.providers.openrouter.api_key = ""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    warnings = env_reference_warnings(cfg)

    assert not any("Image generation" in warning for warning in warnings)
