"""Tests for onboarding memory embedding provider catalog."""

from __future__ import annotations

import pytest

from opensquilla.onboarding.memory_embedding_specs import (
    get_memory_embedding_provider_setup_spec,
    memory_embedding_provider_catalog_payload,
)


def test_memory_embedding_catalog_covers_all_setup_providers():
    payload = memory_embedding_provider_catalog_payload()
    provider_ids = {row["providerId"] for row in payload}

    assert {
        "auto",
        "local",
        "openai",
        "openai-compatible",
        "ollama",
        "none",
    } <= provider_ids


def test_memory_embedding_payload_exposes_readiness_metadata():
    payload = memory_embedding_provider_catalog_payload()

    for row in payload:
        assert row["blocking"] is False
        assert row["canProbe"] is False
        assert row["deployment"] in {"auto", "local", "cloud", "custom", "disabled"}
        assert row["whatYouNeed"]
        assert row["readmeScenarios"]


def test_memory_embedding_remote_requires_key():
    spec = get_memory_embedding_provider_setup_spec("openai")

    assert spec.requires_api_key is True
    assert spec.deployment == "cloud"
    assert spec.env_key == "OPENAI_API_KEY"


def test_unknown_memory_embedding_provider_raises():
    with pytest.raises(KeyError):
        get_memory_embedding_provider_setup_spec("does-not-exist")
