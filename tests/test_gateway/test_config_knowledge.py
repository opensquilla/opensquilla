from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from opensquilla.gateway.config import GatewayConfig
from opensquilla.onboarding.config_store import load_config, persist_config


def test_gateway_config_loads_knowledge_http_section(tmp_path: Path) -> None:
    path = tmp_path / "opensquilla.toml"
    path.write_text(
        "\n".join(
            [
                "[knowledge]",
                'backend = "http"',
                'endpoint = "http://127.0.0.1:18765"',
                "timeout_seconds = 12.5",
                'api_key_env = "OPENSQUILLA_KNOWLEDGE_API_KEY"',
                "capability_ttl_seconds = 45",
            ]
        ),
        encoding="utf-8",
    )

    config = GatewayConfig.load_from_toml(path)

    assert config.knowledge.enabled is True
    assert config.knowledge.backend == "http"
    assert config.knowledge.endpoint == "http://127.0.0.1:18765"
    assert config.knowledge.timeout_seconds == 12.5
    assert config.knowledge.api_key_env == "OPENSQUILLA_KNOWLEDGE_API_KEY"
    assert config.knowledge.capability_ttl_seconds == 45.0


def test_gateway_config_defaults_knowledge_capability_ttl() -> None:
    assert GatewayConfig().knowledge.capability_ttl_seconds == 60.0


def test_gateway_config_rejects_zero_knowledge_capability_ttl() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(
            {"knowledge": {"capability_ttl_seconds": 0}},
        )


def test_env_knowledge_api_key_is_not_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "opensquilla.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_KNOWLEDGE__API_KEY", "env-knowledge-secret")

    config = load_config(path)

    assert config.knowledge.api_key == "env-knowledge-secret"
    assert "knowledge.api_key" in config._runtime_secret_paths
    assert "api_key" not in config.to_toml_dict()["knowledge"]
    assert "env-knowledge-secret" not in repr(config.to_public_dict())

    config.diagnostics_enabled = True
    persist_config(config, path=path)
    assert "env-knowledge-secret" not in path.read_text(encoding="utf-8")


def test_explicit_knowledge_api_key_survives_unrelated_persist(tmp_path: Path) -> None:
    path = tmp_path / "opensquilla.toml"
    path.write_text(
        "\n".join(
            [
                "[knowledge]",
                'backend = "http"',
                'api_key = "stored-knowledge-secret"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(path)
    config.diagnostics_enabled = True
    persist_config(config, path=path)

    assert "knowledge.api_key" not in config._runtime_secret_paths
    assert config.to_toml_dict()["knowledge"]["api_key"] == "stored-knowledge-secret"
    assert 'api_key = "stored-knowledge-secret"' in path.read_text(encoding="utf-8")
