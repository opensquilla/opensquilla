from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from opensquilla.gateway.config import GatewayConfig, KnowledgeConfig


def test_rag_provider_defaults_are_disabled_and_safe() -> None:
    knowledge = GatewayConfig().knowledge

    assert knowledge.enabled is False
    assert knowledge.provider_base_url == "http://127.0.0.1:18765/opensquilla-rag"
    assert knowledge.authentication_token_env is None
    assert knowledge.legacy_knowledge_adapter is False
    assert knowledge.legacy_config_present is False


def test_gateway_config_loads_and_normalizes_provider_section(tmp_path: Path) -> None:
    path = tmp_path / "opensquilla.toml"
    path.write_text(
        "\n".join(
            [
                "[knowledge]",
                "enabled = true",
                'provider_base_url = "http://127.0.0.1:18766/opensquilla-rag/"',
                'authentication_token_env = " OPENSQUILLA_KNOWLEDGE_API_KEY "',
                "connect_timeout_seconds = 2.5",
                "request_timeout_seconds = 45",
                "probe_interval_seconds = 30",
                "unavailable_after_seconds = 120",
                "max_consecutive_failures = 4",
                'retrieval_profile_override = " profile-a "',
                'collection_scope = [" datasets ", "reports", "datasets"]',
            ]
        ),
        encoding="utf-8",
    )

    knowledge = GatewayConfig.load_from_toml(path).knowledge

    assert knowledge.enabled is True
    assert knowledge.provider_base_url == "http://127.0.0.1:18766/opensquilla-rag"
    assert knowledge.authentication_token_env == "OPENSQUILLA_KNOWLEDGE_API_KEY"
    assert knowledge.collection_scope == ["datasets", "reports"]
    assert knowledge.retrieval_profile_override == "profile-a"
    assert knowledge.max_consecutive_failures == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("connect_timeout_seconds", 0),
        ("request_timeout_seconds", 0),
        ("probe_interval_seconds", 0),
        ("unavailable_after_seconds", 0),
        ("max_consecutive_failures", 0),
    ],
)
def test_provider_numeric_limits_must_be_positive(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        KnowledgeConfig.model_validate({field: value})


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1/provider",
        "http://user:pass@127.0.0.1/provider",
        "http://127.0.0.1/provider?token=secret",
        "http://127.0.0.1/provider#fragment",
    ],
)
def test_provider_url_rejects_unsafe_forms(url: str) -> None:
    with pytest.raises(ValidationError):
        KnowledgeConfig(provider_base_url=url)


@pytest.mark.parametrize("name", ["1TOKEN", "TOKEN-NAME", "TOKEN NAME", ""])
def test_authentication_token_env_requires_environment_variable_name(name: str) -> None:
    with pytest.raises(ValidationError):
        KnowledgeConfig(authentication_token_env=name)


def test_actual_environment_token_is_never_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROVIDER_TOKEN", "secret-provider-value")
    config = GatewayConfig.model_validate(
        {"knowledge": {"authentication_token_env": "RAG_PROVIDER_TOKEN"}}
    )

    assert "secret-provider-value" not in repr(config.to_public_dict())
    assert config.to_toml_dict()["knowledge"]["authentication_token_env"] == "RAG_PROVIDER_TOKEN"


def test_legacy_fields_are_recorded_but_do_not_enable_standard_or_legacy_path() -> None:
    knowledge = KnowledgeConfig.model_validate(
        {
            "backend": "http",
            "endpoint": "http://127.0.0.1:18766",
            "timeout_seconds": 90,
            "capability_ttl_seconds": 30,
            "api_key_env": "OLD_TOKEN",
        }
    )

    assert knowledge.enabled is False
    assert knowledge.legacy_knowledge_adapter is False
    assert knowledge.legacy_config_present is True


def test_legacy_adapter_requires_explicit_opt_in() -> None:
    knowledge = KnowledgeConfig.model_validate(
        {
            "legacy_knowledge_adapter": True,
            "backend": "http",
            "endpoint": "http://127.0.0.1:18766",
        }
    )

    assert knowledge.legacy_knowledge_adapter is True
    assert knowledge.legacy_config_present is True


def test_plaintext_legacy_api_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        KnowledgeConfig.model_validate({"api_key": "do-not-store-this"})
