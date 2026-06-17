"""meta_command_launch: pops a pending /meta launch onto ctx.metadata.

The store is one-shot: the first turn after ``meta.run`` stamps a launch
seeds ``ctx.metadata["meta_launch"]``; a subsequent turn (no new stamp)
leaves no marker. A turn with no session id or no pending launch is a
no-op.
"""

from __future__ import annotations

import pytest

from opensquilla.engine.steps.meta_command import (
    meta_command_launch,
    pending_meta_launch_pop,
    pending_meta_launch_put,
)


def _make_ctx(session_key: str):
    """Minimal TurnContext-shaped stub the step reads.

    The step only touches ``ctx.session_key`` (read) and ``ctx.metadata``
    (read/write), so a tiny class with those two attributes is sufficient
    and avoids constructing a full provider-bearing TurnContext.
    """

    class _Ctx:
        def __init__(self, key: str) -> None:
            self.session_key = key
            self.metadata: dict = {}

    return _Ctx(session_key)


@pytest.mark.asyncio
async def test_meta_command_launch_seeds_marker_then_one_shot_consumes() -> None:
    pending_meta_launch_put("S1", "meta-tiny")

    ctx = _make_ctx("S1")
    out = await meta_command_launch(ctx)
    assert out is ctx
    assert ctx.metadata["meta_launch"] == {"name": "meta-tiny"}

    # One-shot: a second turn (no new stamp) leaves no marker.
    ctx2 = _make_ctx("S1")
    await meta_command_launch(ctx2)
    assert "meta_launch" not in ctx2.metadata


@pytest.mark.asyncio
async def test_meta_command_launch_no_pending_is_noop() -> None:
    # Ensure no residual entry for this session.
    pending_meta_launch_pop("S-empty")

    ctx = _make_ctx("S-empty")
    await meta_command_launch(ctx)
    assert "meta_launch" not in ctx.metadata


@pytest.mark.asyncio
async def test_meta_command_launch_no_session_id_is_noop() -> None:
    # Even if a launch were stamped under the empty key, an empty session
    # id must not resolve it (the store ignores empty keys on put).
    pending_meta_launch_put("", "meta-tiny")

    ctx = _make_ctx("")
    await meta_command_launch(ctx)
    assert "meta_launch" not in ctx.metadata


def test_pending_store_is_one_shot_and_isolated_per_session() -> None:
    pending_meta_launch_put("A", "meta-a")
    pending_meta_launch_put("B", "meta-b")

    assert pending_meta_launch_pop("A") == "meta-a"
    # Second pop on A returns None (consumed); B is untouched.
    assert pending_meta_launch_pop("A") is None
    assert pending_meta_launch_pop("B") == "meta-b"
    assert pending_meta_launch_pop("B") is None
