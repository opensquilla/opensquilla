"""CLI tests for `opensquilla onboard` and `configure`."""

from __future__ import annotations

import tomllib

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


def test_onboard_noninteractive_provider(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    result = runner.invoke(
        app,
        [
            "onboard",
            "--provider", "openrouter",
            "--model", "deepseek/deepseek-v4-flash",
            "--api-key", "sk",
            "--skip-channels", "--skip-search",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "openrouter" in target.read_text()
    assert "sk" not in result.stdout


def test_onboard_accepts_skip_image_generation_option(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    result = runner.invoke(
        app,
        [
            "onboard",
            "--provider",
            "openrouter",
            "--model",
            "deepseek/deepseek-v4-flash",
            "--api-key",
            "sk",
            "--skip-channels",
            "--skip-search",
            "--skip-image-generation",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is False


def test_onboard_noninteractive_provider_can_use_env_key_and_router(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "onboard",
            "--provider",
            "deepseek",
            "--model",
            "deepseek-chat",
            "--api-key-env",
            "DEEPSEEK_API_KEY",
            "--router",
            "recommended",
            "--minimal",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "deepseek"
    assert data["llm"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert "api_key" not in data["llm"]
    assert data["squilla_router"]["tier_profile"] == "deepseek"
    assert "tiers" not in data["squilla_router"]
    assert "DEEPSEEK_API_KEY" in result.stdout
    assert "warning" in result.stdout.lower()
    assert "not set in this shell" in result.stdout


def test_onboard_noninteractive_provider_can_omit_model_for_router_profile(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    result = runner.invoke(
        app,
        [
            "onboard",
            "--provider",
            "deepseek",
            "--api-key-env",
            "DEEPSEEK_API_KEY",
            "--minimal",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "deepseek"
    assert data["llm"]["model"] == "deepseek-v4-flash"
    assert data["squilla_router"]["tier_profile"] == "deepseek"


def test_onboard_noninteractive_provider_without_router_profile_disables_router(
    tmp_path, monkeypatch
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "onboard",
            "--provider",
            "anthropic",
            "--model",
            "claude-3-5-sonnet-latest",
            "--api-key-env",
            "ANTHROPIC_API_KEY",
            "--minimal",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "anthropic"
    assert data["llm"]["api_key_env"] == "ANTHROPIC_API_KEY"
    assert "api_key" not in data["llm"]
    assert data["squilla_router"]["enabled"] is False


def test_onboard_if_needed_skips_when_configured(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    runner.invoke(
        app,
        [
            "onboard",
            "--provider", "openrouter",
            "--model", "x", "--api-key", "k",
            "--skip-channels", "--skip-search",
        ],
    )
    mtime_before = target.stat().st_mtime
    result = runner.invoke(app, ["onboard", "--if-needed"])
    assert result.exit_code == 0
    assert "already complete" in result.stdout.lower()
    assert target.stat().st_mtime == mtime_before


def test_onboard_if_needed_skips_when_key_comes_from_env(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\n'
        'provider = "openrouter"\n'
        'model = "deepseek/deepseek-v4-flash"\n'
        'api_key_env = "OPENROUTER_API_KEY"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["onboard", "--if-needed"])

    assert result.exit_code == 0
    assert "already complete" in result.stdout.lower()


def test_onboard_if_needed_does_not_treat_env_as_config_without_config_file(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")

    result = runner.invoke(app, ["onboard", "--if-needed"])

    assert result.exit_code == 2
    assert "requires a TTY" in result.stdout
    assert "already complete" not in result.stdout.lower()
    assert not target.exists()


def test_onboard_if_needed_requires_config_to_reference_env_key(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\n'
        'provider = "openrouter"\n'
        'model = "deepseek/deepseek-v4-flash"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["onboard", "--if-needed"])

    assert result.exit_code == 2
    assert "requires a TTY" in result.stdout
    assert "already complete" not in result.stdout.lower()


def test_onboard_if_needed_does_not_accept_settings_env_without_config_reference(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\n'
        'provider = "openrouter"\n'
        'model = "deepseek/deepseek-v4-flash"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_LLM_API_KEY", "sk-from-settings-env")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["onboard", "--if-needed"])

    assert result.exit_code == 2
    assert "requires a TTY" in result.stdout
    assert "already complete" not in result.stdout.lower()


def test_onboard_if_needed_does_not_accept_settings_env_with_empty_config(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    target.write_text("", encoding="utf-8")
    monkeypatch.setenv("OPENSQUILLA_LLM_API_KEY", "sk-from-settings-env")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["onboard", "--if-needed"])

    assert result.exit_code == 2
    assert "requires a TTY" in result.stdout
    assert "already complete" not in result.stdout.lower()


def test_onboard_if_needed_requires_referenced_env_even_with_settings_env(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\n'
        'provider = "openrouter"\n'
        'model = "deepseek/deepseek-v4-flash"\n'
        'api_key_env = "OPENROUTER_API_KEY"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENSQUILLA_LLM_API_KEY", "sk-from-settings-env")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["onboard", "--if-needed"])

    assert result.exit_code == 2
    assert "requires a TTY" in result.stdout
    assert "already complete" not in result.stdout.lower()


def test_configure_provider_noninteractive_uses_setup_engine(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "provider",
            "--provider",
            "openrouter",
            "--model",
            "deepseek/deepseek-v4-flash",
            "--api-key-env",
            "OPENROUTER_API_KEY",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "openrouter"
    assert data["llm"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert "api_key" not in data["llm"]


def test_configure_provider_can_omit_model_for_router_profile(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "provider",
            "--provider",
            "deepseek",
            "--api-key-env",
            "DEEPSEEK_API_KEY",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "deepseek"
    assert data["llm"]["model"] == "deepseek-v4-flash"


def test_configure_provider_recomputes_existing_router_profile(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\nprovider = "deepseek"\nmodel = "deepseek-chat"\n'
        '[squilla_router]\ntier_profile = "deepseek"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "provider",
            "--provider",
            "openai",
            "--model",
            "gpt-5.4-mini",
            "--api-key-env",
            "OPENAI_API_KEY",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["llm"]["provider"] == "openai"
    assert data["squilla_router"]["tier_profile"] == "openai"
    assert "tiers" not in data["squilla_router"]


def test_configure_saved_path_escapes_rich_markup_chars(tmp_path, monkeypatch):
    root = tmp_path / "opensquilla-[review]"
    root.mkdir()
    target = root / "config[dev].toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "provider",
            "--provider",
            "openrouter",
            "--model",
            "deepseek/deepseek-v4-flash",
            "--api-key-env",
            "OPENROUTER_API_KEY",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert str(target) in result.stdout


def test_configure_provider_errors_go_to_stderr(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["configure", "provider", "--provider", "not-a-provider"])

    assert result.exit_code == 2
    assert "unknown provider" in result.stderr
    assert "unknown provider" not in result.stdout


def test_configure_router_noninteractive_can_disable(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\nprovider = "openrouter"\nmodel = "deepseek/deepseek-v4-flash"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["configure", "router", "--router", "disabled"])

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["squilla_router"]["enabled"] is False


def test_configure_router_invalid_mode_reports_clean_error(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    target.write_text(
        '[llm]\nprovider = "deepseek"\nmodel = "deepseek-chat"\n'
        '[squilla_router]\ntier_profile = "deepseek"\n',
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["configure", "router", "--router", "openrouter-mix"])

    assert result.exit_code == 2
    assert "openrouter-mix router mode is only valid" in result.output
    assert "Traceback" not in result.output
    assert target.read_text(encoding="utf-8") == before


def test_configure_search_noninteractive(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        ["configure", "search", "--search-provider", "duckduckgo", "--max-results", "7"],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["search_provider"] == "duckduckgo"
    assert data["search_max_results"] == 7


def test_configure_search_can_use_env_key_reference(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "configure",
            "search",
            "--search-provider",
            "brave",
            "--api-key-env",
            "BRAVE_SEARCH_API_KEY",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["search_provider"] == "brave"
    assert data["search_api_key_env"] == "BRAVE_SEARCH_API_KEY"
    assert "search_api_key" not in data
    assert "warning" in result.stdout.lower()
    assert "BRAVE_SEARCH_API_KEY" in result.stdout


def test_configure_image_generation_missing_env_is_blocked(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "configure",
            "image-generation",
            "--image-provider",
            "openrouter",
            "--primary",
            "openrouter/google/gemini-3.1-flash-image-preview",
        ],
    )

    assert result.exit_code == 2
    assert "requires an api_key" in result.stderr


def test_configure_channel_noninteractive_adds_slack(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "channel",
            "--channel-type",
            "slack",
            "--name",
            "work",
            "--token",
            "xoxb-secret",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["channels"]["channels"][0]["type"] == "slack"
    assert data["channels"]["channels"][0]["name"] == "work"


def test_configure_channels_noninteractive_accepts_spec_fields_for_feishu(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "channels",
            "--channel-type",
            "feishu",
            "--name",
            "feishu-main",
            "--field",
            "app_id=cli_123",
            "--field",
            "app_secret=secret_123",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    entry = data["channels"]["channels"][0]
    assert entry["type"] == "feishu"
    assert entry["name"] == "feishu-main"
    assert entry["app_id"] == "cli_123"
    assert entry["app_secret"] == "secret_123"
    assert "secret_123" not in result.stdout


def test_configure_channels_rejects_unknown_field(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "channels",
            "--channel-type",
            "feishu",
            "--name",
            "feishu-main",
            "--field",
            "not_a_field=value",
        ],
    )

    assert result.exit_code == 2
    assert "unknown field" in result.output.lower()
    assert not target.exists()


def test_configure_channels_token_only_does_not_complete_feishu(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "channels",
            "--channel-type",
            "feishu",
            "--name",
            "feishu-main",
            "--token",
            "secret",
        ],
    )

    assert result.exit_code == 2
    assert "app_id" in result.output or "app_secret" in result.output
    assert not target.exists()


def test_configure_image_generation_noninteractive_uses_env(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-image-env")

    result = runner.invoke(
        app,
        [
            "configure",
            "image-generation",
            "--image-provider",
            "openrouter",
            "--primary",
            "openrouter/google/gemini-3.1-flash-image-preview",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["image_generation"]["enabled"] is True
    assert data["image_generation"]["providers"]["openrouter"]["api_key"] == ""


def test_configure_image_generation_can_use_nondefault_env_reference(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENSQUILLA_TEST_IMAGE_KEY", "sk-image-env")

    result = runner.invoke(
        app,
        [
            "configure",
            "image-generation",
            "--image-provider",
            "openrouter",
            "--primary",
            "openrouter/google/gemini-3.1-flash-image-preview",
            "--api-key-env",
            "OPENSQUILLA_TEST_IMAGE_KEY",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    provider = data["image_generation"]["providers"]["openrouter"]
    assert provider["api_key"] == ""
    assert provider["api_key_env"] == "OPENSQUILLA_TEST_IMAGE_KEY"


def test_configure_memory_embedding_noninteractive(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(
        app,
        [
            "configure",
            "memory-embedding",
            "--memory-provider",
            "local",
            "--onnx-dir",
            "models/bge",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = tomllib.loads(target.read_text())
    assert data["memory"]["embedding"]["provider"] == "local"
    assert data["memory"]["embedding"]["local"]["onnx_dir"] == "models/bge"


def test_onboard_without_tty_prints_hint_without_writing_config(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 2
    assert "requires a TTY" in result.stdout
    assert "--api-key-env" in result.stdout
    assert "--router" in result.stdout
    assert not target.exists()


def test_init_help_mentions_onboard():
    result = runner.invoke(app, ["init", "--help"])
    assert "onboard" in result.stdout.lower()
