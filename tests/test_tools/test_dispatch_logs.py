from __future__ import annotations

import pytest
import structlog.testing

from opensquilla.engine.types import ToolCall
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    ToolSpec,
    current_tool_context,
)


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def denied() -> str:
        raise ValueError("bad argument")

    async def pending() -> str:
        return (
            '{\"status\": \"approval_required\", \"approval_id\": \"abc123\",'
            ' \"command\": \"rm /tmp/secret\", \"warning\": \"destructive\"}'
        )

    async def required_echo(value: str) -> str:
        return value

    registry.register(ToolSpec(name="denied", description="denied", parameters={}), denied)
    registry.register(ToolSpec(name="pending", description="pending", parameters={}), pending)
    registry.register(
        ToolSpec(
            name="required_echo",
            description="required echo",
            parameters={"value": {"type": "string"}},
            required=["value"],
        ),
        required_echo,
    )
    return registry


@pytest.mark.asyncio
async def test_dispatch_tool_failed_log_includes_surface_context() -> None:
    handler = build_tool_handler(_build_registry())
    token = current_tool_context.set(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.WEB,
            session_key="agent:main:demo",
            agent_id="main",
        )
    )
    try:
        with structlog.testing.capture_logs() as captured:
            result = await handler(
                ToolCall(tool_use_id="tc-1", tool_name="denied", arguments={})
            )

        assert result.is_error is True
        assert any(event["event"] == "dispatch.tool_failed" for event in captured)
        event = next(event for event in captured if event["event"] == "dispatch.tool_failed")
        assert event["tool"] == "denied"
        assert event["tool_use_id"] == "tc-1"
        assert event["agent_id"] == "main"
        assert event["session_key"] == "agent:main:demo"
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_dispatch_missing_required_log_records_shape_guidance_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_MISSING_REQUIRED_ARGUMENT_SHAPE_GUIDANCE", "1")
    handler = build_tool_handler(_build_registry())
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            session_key="agent:main:shape-guidance",
            agent_id="main",
        )
    )
    try:
        with structlog.testing.capture_logs() as captured:
            result = await handler(
                ToolCall(
                    tool_use_id="tc-shape",
                    tool_name="required_echo",
                    arguments={},
                )
            )

        assert result.is_error is True
        event = next(
            event
            for event in captured
            if event["event"] == "dispatch.invalid_tool_arguments"
        )
        assert event["shape_guidance_enabled"] is True
        assert event["argument_keys"] == []
        assert event["missing"] == ["value"]
        assert event["session_key"] == "agent:main:shape-guidance"
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_dispatch_unsupported_surface_log_includes_approval_id() -> None:
    handler = build_tool_handler(_build_registry())
    token = current_tool_context.set(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CRON,
            interaction_mode=InteractionMode.UNATTENDED,
            session_key="cron:system",
            agent_id="cron",
        )
    )
    try:
        with structlog.testing.capture_logs() as captured:
            result = await handler(
                ToolCall(tool_use_id="tc-2", tool_name="pending", arguments={}),
            )

        assert result.is_error is False
        assert result.execution_status is not None
        assert result.execution_status["status"] == "unknown"
        assert result.execution_status["reason"] == "approval_pending"
        assert any(
            event["event"] == "dispatch.approval_required_unsupported_surface"
            for event in captured
        )
        event = next(
            event
            for event in captured
            if event["event"] == "dispatch.approval_required_unsupported_surface"
        )
        assert event["tool"] == "pending"
        assert event["surface"] == "cron"
        assert event["approval_id"] == "abc123"
        assert event["tool_use_id"] == "tc-2"
        assert event["agent_id"] == "cron"
        assert event["session_key"] == "cron:system"
    finally:
        current_tool_context.reset(token)
