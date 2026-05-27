"""meta_resolution sticky-continuation tests.

Covers the in-memory session-keyed cache that keeps a meta-skill match
alive across follow-up turns when the LLM failed to actually emit
``meta_invoke`` on the originating turn (e.g. length-capped on
reasoning).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import importlib

mr = importlib.import_module("opensquilla.engine.steps.meta_resolution")
meta_resolution = mr.meta_resolution
from opensquilla.skills.meta.types import MetaPlan, MetaStep


def _meta_spec(*, name: str, triggers: tuple[str, ...]):
    """Build a minimal meta skill spec that ``parse_meta_plan`` accepts."""
    plan = MetaPlan(
        name=name,
        triggers=triggers,
        priority=50,
        steps=(MetaStep(id="s1", skill="paper-section-author", kind="agent"),),
    )
    spec = SimpleNamespace(
        name=name,
        kind="meta",
        triggers=list(triggers),
        composition_raw={
            "meta_priority": plan.priority,
            "steps": [{"id": "s1", "skill": "paper-section-author", "kind": "agent"}],
        },
        metadata={"opensquilla": {"meta_priority": plan.priority}},
        body="",
    )
    return spec


def _ctx(*, message: str, session_id: str, skills: list):
    loader = MagicMock()
    loader.load_all.return_value = skills
    return SimpleNamespace(
        message=message,
        session_key=session_id,
        metadata={"skill_loader": loader},
        system_prompt="",
        config=SimpleNamespace(squilla_router=SimpleNamespace(tiers={})),
        surface_kind="cli",
    )


@pytest.fixture(autouse=True)
def _clear_sticky_cache():
    """Ensure each test sees a fresh sticky cache."""
    with mr._sticky_lock:
        mr._meta_sticky_cache.clear()
    yield
    with mr._sticky_lock:
        mr._meta_sticky_cache.clear()


@pytest.mark.asyncio
async def test_fresh_match_arms_sticky_cache():
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    ctx = _ctx(message="帮我写篇论文", session_id="S-A", skills=skills)

    out = await meta_resolution(ctx)
    assert "meta_match" in out.metadata
    assert out.metadata.get("meta_match_sticky") is not True

    cached = mr._sticky_get("S-A")
    assert cached is not None
    assert cached["skill"] == "meta-paper-write"
    assert cached["trigger"] == "帮我写篇论文"
    assert cached["uses"] == mr._STICKY_MAX_USES


@pytest.mark.asyncio
async def test_followup_without_trigger_replays_from_sticky():
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    # T1: arm cache.
    await meta_resolution(_ctx(
        message="帮我写篇论文", session_id="S-B", skills=skills,
    ))

    # T2: same session, follow-up text does not contain the trigger.
    out = await meta_resolution(_ctx(
        message="我想写一个关于 RAG 的论文，20 页左右",
        session_id="S-B",
        skills=skills,
    ))
    assert "meta_match" in out.metadata
    assert out.metadata.get("meta_match_sticky") is True
    assert out.metadata.get("meta_match").plan.name == "meta-paper-write"
    # uses decremented by 1
    assert mr._sticky_get("S-B")["uses"] == mr._STICKY_MAX_USES - 1


@pytest.mark.asyncio
async def test_sticky_replay_clamps_thinking_to_low():
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    ctx_fresh = _ctx(message="帮我写篇论文", session_id="S-C", skills=skills)
    out_fresh = await meta_resolution(ctx_fresh)
    assert out_fresh.metadata.get("thinking_level") == "low"
    assert out_fresh.metadata.get("thinking_source") == "meta_resolution"

    ctx_followup = _ctx(message="补充细节", session_id="S-C", skills=skills)
    out_followup = await meta_resolution(ctx_followup)
    assert out_followup.metadata.get("meta_match_sticky") is True
    assert out_followup.metadata.get("thinking_level") == "low"


@pytest.mark.asyncio
async def test_sticky_uses_decrement_to_zero_then_drops():
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    # Fresh match arms cache with MAX_USES.
    await meta_resolution(_ctx(
        message="帮我写篇论文", session_id="S-D", skills=skills,
    ))

    for _ in range(mr._STICKY_MAX_USES):
        out = await meta_resolution(_ctx(
            message="follow-up", session_id="S-D", skills=skills,
        ))
        assert out.metadata.get("meta_match_sticky") is True

    # After exhausting uses, the next no-trigger turn no longer matches.
    out_after = await meta_resolution(_ctx(
        message="another follow-up", session_id="S-D", skills=skills,
    ))
    assert "meta_match" not in out_after.metadata
    assert mr._sticky_get("S-D") is None


@pytest.mark.asyncio
async def test_sticky_cancel_keyword_drops_entry():
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    await meta_resolution(_ctx(
        message="帮我写篇论文", session_id="S-E", skills=skills,
    ))
    assert mr._sticky_get("S-E") is not None

    # User cancels — sticky cache is dropped, no replay on this turn.
    out = await meta_resolution(_ctx(
        message="算了，取消吧", session_id="S-E", skills=skills,
    ))
    assert "meta_match" not in out.metadata
    assert mr._sticky_get("S-E") is None


@pytest.mark.asyncio
async def test_fresh_match_on_followup_refreshes_uses():
    """If the user re-utters the trigger, uses are re-armed."""
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    await meta_resolution(_ctx(
        message="帮我写篇论文", session_id="S-F", skills=skills,
    ))
    # Burn one use.
    await meta_resolution(_ctx(
        message="补充", session_id="S-F", skills=skills,
    ))
    assert mr._sticky_get("S-F")["uses"] == mr._STICKY_MAX_USES - 1

    # Re-trigger restores full budget.
    await meta_resolution(_ctx(
        message="帮我写篇论文", session_id="S-F", skills=skills,
    ))
    assert mr._sticky_get("S-F")["uses"] == mr._STICKY_MAX_USES


@pytest.mark.asyncio
async def test_sessions_are_isolated():
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    await meta_resolution(_ctx(
        message="帮我写篇论文", session_id="S-G1", skills=skills,
    ))
    # Different session — no sticky for it.
    out = await meta_resolution(_ctx(
        message="hello", session_id="S-G2", skills=skills,
    ))
    assert "meta_match" not in out.metadata
    assert mr._sticky_get("S-G1") is not None
    assert mr._sticky_get("S-G2") is None


@pytest.mark.asyncio
async def test_no_sticky_when_skill_was_removed():
    """If the meta-skill is no longer loaded, sticky entry is dropped."""
    skills = [_meta_spec(name="meta-paper-write", triggers=("帮我写篇论文",))]
    await meta_resolution(_ctx(
        message="帮我写篇论文", session_id="S-H", skills=skills,
    ))
    # Next turn — loader returns nothing.
    out = await meta_resolution(_ctx(
        message="follow-up", session_id="S-H", skills=[],
    ))
    assert "meta_match" not in out.metadata
    assert mr._sticky_get("S-H") is None
