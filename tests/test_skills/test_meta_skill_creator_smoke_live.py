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
    """Scaffold for future cross-vendor LLM wiring.

    Phase 1: real_fixture_gen raises NotImplementedError when llm_chat is
    provided. When that wiring lands, replace this body with a real LLM
    call asserting the fixture is non-empty and plausibly matches the
    SKILL.md's domain.
    """
    pytest.skip("scaffold only — real LLM wiring deferred to follow-on iteration")
