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
        "Image generation=Needs action | Voice audio=Later | "
        "Memory embedding=Needs action"
    ) in text
    assert text.index("  Capabilities:") < text.index("Commands:")


def test_onboarding_finish_output_uses_product_router_label():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding.next_steps import format_next_steps

    text = format_next_steps(GatewayConfig(), config_path="/tmp/opensquilla/custom.toml")

    assert "  Router: SquillaRouter, default=c1" in text
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


def test_headless_setup_commands_cover_the_ensemble_section():
    from opensquilla.onboarding.next_steps import headless_setup_commands

    for section in ("ensemble", "llm-ensemble", "llm_ensemble"):
        commands = headless_setup_commands(section)
        assert commands == [
            (
                "Headless ensemble",
                "opensquilla onboard configure ensemble --enabled",
            )
        ]


def test_quote_cli_arg_uses_posix_quoting_off_windows(monkeypatch):
    import shlex

    from opensquilla.onboarding import next_steps

    monkeypatch.setattr(next_steps.platform, "system", lambda: "Linux")

    assert next_steps.quote_cli_arg("/tmp/plain.toml") == "/tmp/plain.toml"
    assert next_steps.quote_cli_arg("/tmp/with space.toml") == shlex.quote(
        "/tmp/with space.toml"
    )
    assert next_steps.quote_cli_arg("/tmp/it's.toml") == shlex.quote("/tmp/it's.toml")


def test_quote_cli_arg_uses_powershell_quoting_on_windows(monkeypatch):
    from opensquilla.onboarding import next_steps

    monkeypatch.setattr(next_steps.platform, "system", lambda: "Windows")

    # Plain values stay copyable as-is.
    assert next_steps.quote_cli_arg("config.toml") == "config.toml"
    # Values needing quotes get PowerShell literal strings, not the POSIX
    # '"'"' dance that PowerShell cannot parse.
    assert (
        next_steps.quote_cli_arg("C:\\Setup Files\\config.toml")
        == "'C:\\Setup Files\\config.toml'"
    )
    assert next_steps.quote_cli_arg("C:\\it's.toml") == "'C:\\it''s.toml'"
    assert '"\'"' not in next_steps.quote_cli_arg("C:\\it's.toml")
    # PowerShell also treats Unicode smart quotes as single-quote delimiters,
    # so they must be doubled as well or the literal terminates early.
    assert (
        next_steps.quote_cli_arg("C:\\Users\\O’Brien\\config.toml")
        == "'C:\\Users\\O’’Brien\\config.toml'"
    )


def test_config_cli_arg_is_powershell_safe_on_windows(monkeypatch):
    from opensquilla.onboarding import next_steps

    monkeypatch.setattr(next_steps.platform, "system", lambda: "Windows")

    arg = next_steps._config_cli_arg("C:\\Setup Files\\config.toml")

    assert arg == " --config 'C:\\Setup Files\\config.toml'"


def test_set_env_command_is_bare_on_both_platforms(monkeypatch):
    from opensquilla.onboarding import next_steps

    monkeypatch.setattr(next_steps.platform, "system", lambda: "Linux")
    assert next_steps.set_env_command("DUMMY_KEY") == 'export DUMMY_KEY="<your-key>"'
    assert next_steps.set_env_hint("DUMMY_KEY") == 'export DUMMY_KEY="<your-key>"'

    monkeypatch.setattr(next_steps.platform, "system", lambda: "Windows")
    assert next_steps.set_env_command("DUMMY_KEY") == '$env:DUMMY_KEY = "<your-key>"'
    # The human hint keeps the shell label; the bare command never carries it.
    assert (
        next_steps.set_env_hint("DUMMY_KEY")
        == 'PowerShell: $env:DUMMY_KEY = "<your-key>"'
    )


def test_env_recovery_commands_carry_only_the_command_on_windows(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps
    from opensquilla.onboarding.status import get_onboarding_status

    cfg = GatewayConfig()
    cfg.llm.api_key = ""
    cfg.llm.api_key_env = "DUMMY_UNSET_LLM_KEY"
    monkeypatch.delenv("DUMMY_UNSET_LLM_KEY", raising=False)
    monkeypatch.setattr(next_steps.platform, "system", lambda: "Windows")

    commands = next_steps.env_recovery_commands(get_onboarding_status(cfg))

    assert commands
    for entry in commands:
        assert set(entry) == {"section", "label", "command"}
        assert entry["command"] == '$env:DUMMY_UNSET_LLM_KEY = "<your-key>"'
        assert "PowerShell" not in entry["command"]


def test_status_display_words_have_a_single_source_of_truth():
    from opensquilla.cli import onboard_cmd
    from opensquilla.onboarding import next_steps
    from opensquilla.onboarding.section_status import SECTION_STATUS_DISPLAY

    # The status table renders through the shared mapping object itself…
    assert onboard_cmd._STATUS_DISPLAY is SECTION_STATUS_DISPLAY
    # …and the capability summary uses a mechanically derived string view.
    assert next_steps._CAPABILITY_STATUS_DISPLAY == {
        status.value: display for status, display in SECTION_STATUS_DISPLAY.items()
    }
    assert set(next_steps._CAPABILITY_STATUS_DISPLAY) == {
        "ok", "optional", "missing", "degraded", "unknown",
    }


def test_next_steps_mention_persistent_env_file_alongside_export_hint(
    tmp_path, monkeypatch
):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "state-home"))
    cfg = GatewayConfig()
    cfg.llm.api_key = ""
    cfg.llm.api_key_env = "DUMMY_UNSET_LLM_KEY"
    monkeypatch.delenv("DUMMY_UNSET_LLM_KEY", raising=False)

    text = next_steps.format_next_steps(cfg, config_path="/tmp/config.toml")

    env_file = str(tmp_path / "state-home" / ".env")
    assert (
        f"Persist key across restarts: add DUMMY_UNSET_LLM_KEY=<your-key> to {env_file}"
        in text
    )
    # The persist hint sits with the export hint in the Commands block.
    commands = text.split("Commands:", 1)[1].split("Reference:", 1)[0]
    assert "Set key before starting gateway:" in commands
    assert "Persist key across restarts:" in commands


def test_missing_env_warning_mentions_persistent_env_file(tmp_path, monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(tmp_path / "state-home"))
    cfg = GatewayConfig()
    cfg.llm.api_key = ""
    cfg.llm.api_key_env = "DUMMY_UNSET_LLM_KEY"
    monkeypatch.delenv("DUMMY_UNSET_LLM_KEY", raising=False)

    warnings = next_steps.env_reference_warnings(cfg)

    env_file = str(tmp_path / "state-home" / ".env")
    assert any(
        "DUMMY_UNSET_LLM_KEY=<your-key>" in warning and env_file in warning
        for warning in warnings
    )


def test_next_steps_advertise_the_configure_hub(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    cfg = GatewayConfig()

    text = next_steps.format_next_steps(cfg, config_path="/tmp/config.toml")

    commands = text.split("Commands:", 1)[1].split("Reference:", 1)[0]
    assert (
        "Change settings anytime: opensquilla onboard configure --config /tmp/config.toml"
        in commands
    )


def test_fix_next_names_the_exact_command_for_a_degraded_capability(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    cfg = GatewayConfig()
    cfg.search_provider = "tavily"
    cfg.search_api_key = ""
    cfg.search_api_key_env = "DUMMY_UNSET_SEARCH_KEY"
    monkeypatch.delenv("DUMMY_UNSET_SEARCH_KEY", raising=False)

    text = next_steps.format_next_steps(cfg, config_path="/tmp/config.toml")

    assert "Fix next:" in text
    fix_block = text.split("Fix next:", 1)[1].split("Reference:", 1)[0]
    assert "opensquilla onboard configure search --config /tmp/config.toml" in fix_block


def test_fix_next_absent_when_nothing_needs_attention():
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    # Fresh defaults: every capability is either ready or a deliberate
    # "Later" opt-out — nothing to nag about.
    text = next_steps.format_next_steps(GatewayConfig(), config_path="/tmp/config.toml")

    assert "Fix next:" not in text


def test_fix_next_never_advertises_the_nonexistent_configure_audio(monkeypatch):
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    cfg = GatewayConfig()
    cfg.audio.enabled = True  # enabled without any provider credential
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    text = next_steps.format_next_steps(cfg, config_path="/tmp/config.toml")

    assert "Fix next:" in text
    assert "onboard configure audio" not in text
    assert "opensquilla onboard catalog audio" in text


def test_fix_next_audio_command_comes_from_the_headless_command_table(monkeypatch):
    """The audio fix line must advertise the command recorded once in
    _HEADLESS_SETUP_COMMANDS — a rename there must not leave a stale
    hardcoded copy in the Fix-next checklist."""
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps

    cfg = GatewayConfig()
    cfg.audio.enabled = True  # enabled without any provider credential
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setitem(
        next_steps._HEADLESS_SETUP_COMMANDS,
        "audio",
        ("Audio recipes", "opensquilla onboard catalog audio-renamed"),
    )

    text = next_steps.format_next_steps(cfg, config_path="/tmp/config.toml")

    fix_block = text.split("Fix next:", 1)[1]
    assert "opensquilla onboard catalog audio-renamed --config /tmp/config.toml" in fix_block
    assert "catalog audio --config" not in fix_block


def test_capability_summary_and_fix_lines_share_one_label_status_resolver(monkeypatch):
    """Both lines of the same printed block derive (label, display) through
    _capability_section_view, so a wording change can never make the
    Capabilities summary and the Fix-next checklist disagree."""
    from opensquilla.gateway.config import GatewayConfig
    from opensquilla.onboarding import next_steps
    from opensquilla.onboarding.status import get_onboarding_status

    cfg = GatewayConfig()
    cfg.search_provider = "tavily"
    cfg.search_api_key = ""
    cfg.search_api_key_env = "DUMMY_UNSET_SEARCH_KEY"
    monkeypatch.delenv("DUMMY_UNSET_SEARCH_KEY", raising=False)
    status = get_onboarding_status(cfg)

    label, display, _value, needs_action = next_steps._capability_section_view(
        status, "search"
    )

    assert needs_action is True
    summary = next_steps._capabilities_summary(status)
    assert f"{label}={display}" in summary
    fix_lines = next_steps._capability_fix_lines(status, "")
    assert any(line.startswith(f"  {label} ({display}): ") for line in fix_lines)
