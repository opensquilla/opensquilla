"""Tests for onboarding search provider catalog."""

from __future__ import annotations

from opensquilla.onboarding.search_specs import (
    get_search_provider_setup_spec,
    list_search_provider_setup_specs,
    search_provider_catalog_payload,
)


def test_search_catalog_includes_known_providers():
    ids = {s.provider_id for s in list_search_provider_setup_specs()}
    assert {"brave", "duckduckgo", "tavily", "exa", "perplexity"} <= ids


def test_search_catalog_marks_unsupported_providers_disabled():
    specs = {s.provider_id: s for s in list_search_provider_setup_specs()}
    assert specs["brave"].runtime_supported is True
    assert specs["duckduckgo"].runtime_supported is True
    assert specs["tavily"].runtime_supported is False
    assert specs["exa"].runtime_supported is False
    assert specs["perplexity"].runtime_supported is False


def test_brave_search_spec_requires_api_key():
    spec = get_search_provider_setup_spec("brave")
    assert spec.requires_api_key is True
    assert spec.env_key == "BRAVE_SEARCH_API_KEY"


def test_duckduckgo_search_spec_does_not_require_api_key():
    spec = get_search_provider_setup_spec("duckduckgo")
    assert spec.requires_api_key is False


def test_search_catalog_payload_is_web_safe_shape():
    payload = search_provider_catalog_payload()
    first = payload[0]
    assert "providerId" in first
    assert "runtimeSupported" in first
    assert "fields" in first
    assert "blocking" in first
    assert "whatYouNeed" in first


def test_search_catalog_explains_fallback_and_diagnostics_fields():
    spec = get_search_provider_setup_spec("brave")
    fields = {field.name: field for field in spec.fields}

    assert "DuckDuckGo" in fields["fallback_policy"].description
    assert "attempt/error details" in fields["diagnostics"].description


def test_search_payload_marks_search_as_optional_capability():
    payload = search_provider_catalog_payload()

    assert all(row["blocking"] is False for row in payload)
    assert all(row["canProbe"] is False for row in payload)
    assert all(row["readmeScenarios"] for row in payload)
