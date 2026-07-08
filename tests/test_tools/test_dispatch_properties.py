"""Property tests for dispatch_legacy.py invariants.

Three properties verified across the corpus:

1. Idempotent status normalisation:
   normalize(normalize(s)) == normalize(s) for any returned execution_status.

2. Artifact monotonicity:
   len(ctx.published_artifacts) after dispatch >= before for any case.

3. First denial wins:
   When two policies would each deny, only the first policy's error_class appears.
   This is verified structurally against the multiple_policies_would_deny_first_wins
   case (owner_only fires before denied_tools in the waterfall).

hypothesis is not available in this environment; cases are hand-rolled
parametrizations drawn from ALL_CASES plus targeted edge inputs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_tools.dispatch_corpus import ALL_CASES, CorpusCase

from opensquilla.execution_status import normalize_execution_status
from opensquilla.tool_boundary import ToolCall
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    ToolSpec,
    current_tool_context,
)

# ---------------------------------------------------------------------------
# Property 1: Idempotent status normalisation
# ---------------------------------------------------------------------------
#
# normalize_execution_status is a pure function. For any execution_status
# dict returned by dispatch, applying normalize again must produce the same
# result (i.e., it is already in canonical form after one application).
#
# We verify this against every corpus case result PLUS a set of hand-rolled
# raw dicts that cover all branches of normalize_execution_status.


_RAW_STATUS_SAMPLES: list[dict[str, Any]] = [
    # Canonical forms — should be unchanged
    {
        "version": 1,
        "status": "success",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": None,
        "source": "tool_runtime",
        "preservation_class": "normal",
    },
    {
        "version": 1,
        "status": "error",
        "exit_code": 1,
        "timed_out": False,
        "truncated": True,
        "reason": "nonzero_exit",
        "source": "adapter",
        "preservation_class": "diagnostic",
    },
    {
        "version": 1,
        "status": "timeout",
        "exit_code": None,
        "timed_out": True,
        "truncated": False,
        "reason": "tool_timeout",
        "source": "adapter",
        "preservation_class": "diagnostic",
    },
    # Invalid status — normalises to unknown
    {
        "version": 1,
        "status": "bogus_status",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": None,
        "source": "tool_runtime",
        "preservation_class": "normal",
    },
    # Invalid source — normalises to unknown
    {
        "version": 1,
        "status": "success",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": None,
        "source": "made_up_source",
        "preservation_class": "normal",
    },
    # Invalid preservation_class — normalises to normal
    {
        "version": 1,
        "status": "success",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": None,
        "source": "tool_runtime",
        "preservation_class": "invalid_class",
    },
    # Non-dict input — normalises to unknown sentinel
    "not a dict",  # type: ignore[list-item]
    None,  # type: ignore[list-item]
    42,  # type: ignore[list-item]
    # Empty dict — all fields default
    {},
    # approval_pending round-trip
    {
        "version": 1,
        "status": "unknown",
        "exit_code": None,
        "timed_out": False,
        "truncated": False,
        "reason": "approval_pending",
        "source": "tool_runtime",
        "preservation_class": "ephemeral",
    },
]


@pytest.mark.parametrize(
    "raw_status",
    _RAW_STATUS_SAMPLES,
    ids=[f"sample_{i}" for i in range(len(_RAW_STATUS_SAMPLES))],
)
def test_normalize_execution_status_is_idempotent(raw_status: Any) -> None:
    """normalize(normalize(s)) == normalize(s) for any status input."""
    once = normalize_execution_status(raw_status)
    twice = normalize_execution_status(once)
    assert once == twice, (
        f"normalize is not idempotent: once={once!r}, twice={twice!r}"
    )


@pytest.mark.parametrize(
    "case",
    ALL_CASES,
    ids=[c.name for c in ALL_CASES],
)
@pytest.mark.asyncio
async def test_corpus_execution_status_is_already_normalised(case: CorpusCase) -> None:
    """Any execution_status returned by dispatch is already in normalised form."""
    ctx = case.ctx_factory()
    registry = case.registry_factory()
    handler = build_tool_handler(
        registry,
        ctx,
        known_skill_names=set(case.known_skill_names) if case.known_skill_names else None,
    )
    token = current_tool_context.set(None)
    if case.setup is not None:
        case.setup()
    try:
        result = await handler(case.tool_call)
    finally:
        current_tool_context.reset(token)
        if case.teardown is not None:
            case.teardown()

    if result.execution_status is not None:
        # Preflight rejections annotate the normalised status with exactly two
        # diagnostic keys that normalize_execution_status does not carry.
        # Assert their shape explicitly, then require the remainder to be in
        # normalised form already.
        comparable = dict(result.execution_status)
        preflight_rejected = comparable.pop("preflight_rejected", None)
        reason_code = comparable.pop("reason_code", None)
        assert preflight_rejected in (None, True), (
            f"[{case.name}] unexpected preflight_rejected value: "
            f"{preflight_rejected!r}"
        )
        if preflight_rejected:
            assert isinstance(reason_code, str) and reason_code, (
                f"[{case.name}] preflight rejection missing reason_code: "
                f"{result.execution_status!r}"
            )
        else:
            assert reason_code is None, (
                f"[{case.name}] reason_code present without preflight_rejected: "
                f"{result.execution_status!r}"
            )
        re_normalised = normalize_execution_status(comparable)
        assert comparable == re_normalised, (
            f"[{case.name}] execution_status not already normalised: "
            f"{result.execution_status!r} != {re_normalised!r}"
        )


# ---------------------------------------------------------------------------
# Property 2: Artifact monotonicity
# ---------------------------------------------------------------------------
#
# For any dispatch call, len(ctx.published_artifacts) after >= before.
# Publishing artifacts is append-only — dispatch never removes items.


@pytest.mark.parametrize(
    "case",
    ALL_CASES,
    ids=[c.name for c in ALL_CASES],
)
@pytest.mark.asyncio
async def test_artifact_list_never_shrinks_after_dispatch(case: CorpusCase) -> None:
    """len(ctx.published_artifacts) after dispatch >= before for any case."""
    ctx = case.ctx_factory()
    registry = case.registry_factory()
    handler = build_tool_handler(
        registry,
        ctx,
        known_skill_names=set(case.known_skill_names) if case.known_skill_names else None,
    )
    token = current_tool_context.set(None)
    if case.setup is not None:
        case.setup()
    try:
        before = len(ctx.published_artifacts) if ctx is not None else 0
        await handler(case.tool_call)
        after = len(ctx.published_artifacts) if ctx is not None else 0
    finally:
        current_tool_context.reset(token)
        if case.teardown is not None:
            case.teardown()

    assert after >= before, (
        f"[{case.name}] artifact list shrank: before={before}, after={after}"
    )


# ---------------------------------------------------------------------------
# Property 3: First denial wins
# ---------------------------------------------------------------------------
#
# When multiple policies would deny a request, the waterfall fires them in
# document order. The corpus case `multiple_policies_would_deny_first_wins`
# sets up owner_only=True (lines 215–231) + denied_tools (lines 233–251).
# Owner-only fires first → OwnerOnly error_class, not PolicyDenied.


@pytest.mark.asyncio
async def test_first_denial_wins_owner_only_before_denied_tools() -> None:
    """owner_only check (lines 215-231) fires before denied_tools check (233-251)."""
    registry = ToolRegistry()

    async def _handler() -> str:
        return "should not reach"

    registry.register(
        ToolSpec(name="double_deny_tool", description="test", parameters={}, owner_only=True),
        _handler,
    )

    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.INTERACTIVE,
        agent_id="main",
        session_key="agent:main:corpus",
        denied_tools={"double_deny_tool"},
    )

    handler = build_tool_handler(registry, ctx)
    token = current_tool_context.set(None)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-first-wins",
                tool_name="double_deny_tool",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is True
    payload = json.loads(result.content)
    # OwnerOnly is the FIRST check; denied_tools is second.
    # If denied_tools fired first we'd see PolicyDenied.
    assert payload["error_class"] == "OwnerOnly", (
        f"Expected OwnerOnly (first denial wins), got {payload['error_class']!r}. "
        "This indicates the waterfall order has changed — update the corpus."
    )


@pytest.mark.asyncio
async def test_first_denial_wins_denied_tools_before_private_memory() -> None:
    """denied_tools check (lines 233-251) fires before private_memory check (253-270).

    Configure ctx with memory_get in denied_tools AND SUBAGENT caller (which
    triggers private_memory_read_tool_denied). denied_tools fires first → PolicyDenied
    with reason=denied. If private_memory fired first we'd get the same error_class
    (PolicyDenied) but the log reason differs — we inspect log events.
    """
    import structlog.testing

    registry = ToolRegistry()

    async def _handler() -> str:
        return "should not reach"

    registry.register(
        ToolSpec(name="memory_get", description="test", parameters={}),
        _handler,
    )

    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.SUBAGENT,
        interaction_mode=InteractionMode.UNATTENDED,
        agent_id="sub1",
        session_key="subagent:sub1:corpus",
        denied_tools={"memory_get"},  # explicit deny fires at line 234
    )

    handler = build_tool_handler(registry, ctx)
    token = current_tool_context.set(None)
    try:
        with structlog.testing.capture_logs() as captured:
            result = await handler(
                ToolCall(
                    tool_use_id="tc-deny-before-privmem",
                    tool_name="memory_get",
                    arguments={},
                )
            )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is True
    # Both policies produce PolicyDenied — distinguish by log reason field
    block_events = [
        e for e in captured if e.get("event") == "dispatch.defense_in_depth_block"
    ]
    assert block_events, "Expected at least one defense_in_depth_block log event"
    # denied_tools fires first: reason="denied" (line 240)
    # private_memory fires second: reason="private_memory_scope" (line 257)
    first_reason = block_events[0].get("reason")
    assert first_reason == "denied", (
        f"Expected first block reason='denied' (denied_tools check), got {first_reason!r}. "
        "Waterfall order may have changed."
    )


@pytest.mark.asyncio
async def test_session_search_is_denied_by_private_memory_scope_for_subagents() -> None:
    import structlog.testing

    registry = ToolRegistry()

    async def _handler() -> str:
        return "should not reach"

    registry.register(
        ToolSpec(name="session_search", description="test", parameters={}),
        _handler,
    )
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.SUBAGENT,
        interaction_mode=InteractionMode.UNATTENDED,
        agent_id="sub1",
        session_key="subagent:agent:main:parent",
    )

    handler = build_tool_handler(registry, ctx)
    token = current_tool_context.set(None)
    try:
        with structlog.testing.capture_logs() as captured:
            result = await handler(
                ToolCall(
                    tool_use_id="tc-subagent-session-search",
                    tool_name="session_search",
                    arguments={"query": "needle"},
                )
            )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is True
    assert "not available in this context" in result.content
    assert any(
        event.get("reason") == "private_memory_scope"
        for event in captured
        if event.get("event") == "dispatch.defense_in_depth_block"
    )


# ---------------------------------------------------------------------------
# Property 4: Contextvar set during handler call (HIGH 2)
# ---------------------------------------------------------------------------
#
# dispatch_legacy sets current_tool_context to effective_ctx before invoking
# the registered handler (line 343) and resets it in the finally block (line 492).
# Dispatch must honour the same contract so nested tool calls see their parent context.
#
# The _contextvar_reading_registry helper captures current_tool_context.get()
# mid-execution into registry._corpus_captured. This test asserts that captured
# value IS effective_ctx — not None, not some other context.


@pytest.mark.asyncio
async def test_contextvar_is_effective_ctx_during_handler_call() -> None:
    """current_tool_context.get() inside a handler equals effective_ctx (legacy line 343).

    Rationale: dispatch could run without setting the contextvar before dispatch and
    the existing ``contextvar_must_be_none_after`` assertion would still pass
    (None → dispatch → None is indistinguishable from None → set → dispatch → reset → None
    if we only check after the fact). This test closes that gap by asserting the
    value seen *inside* the handler matches the context the handler was built for.
    """
    registry = ToolRegistry()
    captured_during: list[ToolContext | None] = []

    async def _ctx_reader() -> str:
        captured_during.append(current_tool_context.get())
        return "done"

    registry.register(
        ToolSpec(name="ctx_reader", description="ctx_reader", parameters={}),
        _ctx_reader,
    )

    expected_ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.INTERACTIVE,
        agent_id="main",
        session_key="agent:main:ctxvar-test",
    )

    handler = build_tool_handler(registry, expected_ctx)
    # Start with contextvar unset (mimics normal agent loop entry)
    token = current_tool_context.set(None)
    try:
        result = await handler(
            ToolCall(tool_use_id="tc-ctxvar-during", tool_name="ctx_reader", arguments={})
        )
    finally:
        current_tool_context.reset(token)

    # Handler must have been called exactly once
    assert len(captured_during) == 1, (
        f"Expected handler to be called once, got {len(captured_during)} captured values"
    )
    # The value seen inside the handler must be the effective context, not None
    assert captured_during[0] is not None, (
        "current_tool_context.get() was None inside the handler — "
        "dispatch did not set the contextvar before calling the handler (line 343 contract)."
    )
    assert captured_during[0] is expected_ctx, (
        f"current_tool_context.get() inside handler was {captured_during[0]!r}, "
        f"expected {expected_ctx!r}. "
        "Dispatch must set current_tool_context to effective_ctx before invoking the handler."
    )
    # After dispatch the contextvar must be reset to None (finally-block contract)
    assert current_tool_context.get() is None, (
        "current_tool_context was not reset to None after dispatch — finally-block leak."
    )
    assert result.is_error is False
