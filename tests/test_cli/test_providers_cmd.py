"""CLI tests for `opensquilla providers`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


def test_providers_list_shows_all_supported(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    result = runner.invoke(app, ["providers", "list"])
    assert result.exit_code == 0
    out = result.stdout
    for pid in ("openrouter", "openai", "ollama", "vllm", "azure"):
        assert pid in out


def test_providers_list_marks_unsupported(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    result = runner.invoke(app, ["providers", "list"])
    assert result.exit_code == 0
    assert "openai_codex" in result.stdout
    assert "unsupported" in result.stdout.lower() or "disabled" in result.stdout.lower()


def test_providers_configure_writes_config(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    result = runner.invoke(
        app,
        [
            "providers", "configure", "openrouter",
            "--model", "deepseek/deepseek-v4-flash",
            "--api-key", "sk-test",
        ],
    )
    assert result.exit_code == 0, result.stdout
    text = target.read_text()
    assert "openrouter" in text
    assert "deepseek/deepseek-v4-flash" in text
    assert "sk-test" not in result.stdout


def test_providers_configure_unsupported_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    result = runner.invoke(
        app, ["providers", "configure", "openai_codex", "--model", "x"]
    )
    assert result.exit_code != 0
    assert (
        "not runtime-supported" in result.stdout.lower()
        or "not runtime-supported" in (result.stderr or "").lower()
    )


def test_providers_configure_ollama_no_key_required(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    result = runner.invoke(
        app, ["providers", "configure", "ollama", "--model", "llama3"]
    )
    assert result.exit_code == 0
    assert "ollama" in target.read_text()


def test_providers_configure_openai_compatible_with_env_key(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    result = runner.invoke(
        app,
        [
            "providers", "configure", "openai_compatible",
            "--model", "local-model",
            "--base-url", "http://localhost:8008/v1",
            "--api-key-env", "SELF_HOSTED_OPENAI_KEY",
        ],
    )

    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    text = target.read_text()
    assert "openai_compatible" in text
    assert "local-model" in text
    assert "http://localhost:8008/v1" in text
    assert "SELF_HOSTED_OPENAI_KEY" in text


def test_providers_configure_openai_compatible_writes_tool_support(tmp_path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    result = runner.invoke(
        app,
        [
            "providers", "configure", "openai_compatible",
            "--model", "local-model",
            "--base-url", "http://localhost:8008/v1",
            "--tool-support", "off",
        ],
    )

    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    text = target.read_text()
    assert 'tool_support = "off"' in text


def test_providers_configure_vllm_is_hidden_until_runtime_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(tmp_path / "c.toml"))
    result = runner.invoke(
        app,
        ["providers", "configure", "vllm", "--model", "x", "--api-key", "k"],
    )
    assert result.exit_code != 0
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "not runtime-supported" in combined
