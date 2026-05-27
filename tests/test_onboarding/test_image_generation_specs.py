"""Tests for onboarding image generation provider catalog."""

from __future__ import annotations

from opensquilla.onboarding.image_generation_specs import (
    image_generation_provider_catalog_payload,
)


def test_image_generation_payload_exposes_optional_capability_metadata():
    payload = image_generation_provider_catalog_payload()

    assert {row["providerId"] for row in payload} == {"openai", "openrouter"}
    for row in payload:
        assert row["blocking"] is False
        assert row["canProbe"] is False
        assert row["deployment"] == "cloud"
        assert row["whatYouNeed"]
        assert row["readmeScenarios"]
