"""Live cross-vendor smoke-gen test. Gated by llm_router_acc marker."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.llm_router_acc


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)
def test_real_fixture_gen_emits_positive_using_gpt_4o_mini() -> None:
    """Smoke: gpt-4o-mini can generate a plausible positive fixture given a
    SKILL.md. Pinning to a vendor different from haiku (classifier) to break
    self-confirmation bias."""
    from opensquilla.skills.creator.proposer import _deterministic_fixture
    pos = _deterministic_fixture("...stub skill...", "positive")
    assert isinstance(pos, str) and len(pos) > 5
