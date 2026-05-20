"""Live cross-vendor smoke-gen test. Gated by llm_router_acc marker."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.llm_router_acc


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)
def test_smoke_live_scaffold_deterministic_path() -> None:
    """Phase 1 scaffold: confirms the live-test infrastructure exists.
    Real cross-vendor LLM wiring lands in a follow-on iteration; this
    test currently exercises the deterministic fallback only.
    """
    from opensquilla.skills.creator.proposer import _deterministic_fixture
    pos = _deterministic_fixture("...stub skill...", "positive")
    assert isinstance(pos, str) and len(pos) > 5
