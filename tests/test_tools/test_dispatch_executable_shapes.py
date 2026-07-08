from __future__ import annotations

import json

import pytest

from opensquilla.engine.types import ToolCall
from opensquilla.tools.dispatch import build_tool_handler, preflight_tool_call
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, ToolSpec


def _payload(result) -> dict[str, object]:
    assert result is not None
    return json.loads(result.content)


def _assert_invalid_execution_status(result, reason_code: str) -> None:
    assert result is not None
    assert result.execution_status is not None
    assert result.execution_status["status"] == "error"
    assert result.execution_status["reason"] == "invalid_tool_arguments"
    assert result.execution_status["preflight_rejected"] is True
    assert result.execution_status["reason_code"] == reason_code


def _registry_with_edit_file() -> ToolRegistry:
    registry = ToolRegistry()

    async def _edit_file(
        path: str,
        old_text: str | None = None,
        new_text: str | None = None,
        edits: list[dict[str, object]] | None = None,
    ) -> str:
        raise AssertionError("preflight should not execute edit_file handler")

    registry.register(
        ToolSpec(
            name="edit_file",
            description="edit file",
            parameters={
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                        },
                    },
                },
            },
            required=["path"],
        ),
        _edit_file,
    )
    return registry


def _registry_with_apply_patch() -> ToolRegistry:
    registry = ToolRegistry()

    async def _apply_patch(patch: str | None = None, path: str | None = None) -> str:
        raise AssertionError("preflight should not execute apply_patch handler")

    registry.register(
        ToolSpec(
            name="apply_patch",
            description="apply patch",
            parameters={
                "patch": {"type": "string"},
                "path": {"type": "string"},
            },
            required=[],
        ),
        _apply_patch,
    )
    return registry


@pytest.mark.asyncio
async def test_edit_file_path_only_is_rejected_before_handler() -> None:
    events: list[dict[str, object]] = []
    result = await preflight_tool_call(
        registry=_registry_with_edit_file(),
        ctx=ToolContext(on_runtime_event=events.append, session_key="agent:test"),
        tool_call=ToolCall(
            tool_use_id="u1",
            tool_name="edit_file",
            arguments={"path": "src/a.py"},
        ),
    )

    _assert_invalid_execution_status(result, "missing_executable_shape")
    payload = _payload(result)
    assert payload["status"] == "rejected"
    assert payload["reason_code"] == "missing_executable_shape"
    assert payload["tool"] == "edit_file"
    assert payload["received_keys"] == ["path"]
    assert payload["retry_allowed"] is True
    assert payload["error_class"] == "InvalidToolArgumentsError"
    assert "old_text" in payload["user_message"]
    matching = [
        event
        for event in events
        if event["name"] == "dispatch.invalid_tool_arguments"
    ]
    assert len(matching) == 1
    event = matching[0]
    assert event["reason"] == "missing_executable_shape"
    assert event["tool"] == "edit_file"
    assert event["executed"] is False


@pytest.mark.asyncio
async def test_edit_file_path_only_handler_path_emits_one_invalid_event() -> None:
    events: list[dict[str, object]] = []
    handler = build_tool_handler(
        _registry_with_edit_file(),
        ToolContext(on_runtime_event=events.append, session_key="agent:test"),
    )

    result = await handler(
        ToolCall(
            tool_use_id="u1-handler",
            tool_name="edit_file",
            arguments={"path": "src/a.py"},
        )
    )

    _assert_invalid_execution_status(result, "missing_executable_shape")
    payload = _payload(result)
    assert payload["error_class"] == "InvalidToolArgumentsError"
    matching = [
        event
        for event in events
        if event["name"] == "dispatch.invalid_tool_arguments"
    ]
    assert len(matching) == 1
    assert matching[0]["reason"] == "missing_executable_shape"
    assert matching[0]["tool"] == "edit_file"
    assert matching[0]["executed"] is False


@pytest.mark.asyncio
async def test_edit_file_single_replacement_shape_passes() -> None:
    result = await preflight_tool_call(
        registry=_registry_with_edit_file(),
        ctx=ToolContext(),
        tool_call=ToolCall(
            tool_use_id="u2",
            tool_name="edit_file",
            arguments={
                "path": "src/a.py",
                "old_text": "before",
                "new_text": "after",
            },
        ),
    )

    assert result is None


@pytest.mark.asyncio
async def test_edit_file_whitespace_old_text_shape_passes() -> None:
    result = await preflight_tool_call(
        registry=_registry_with_edit_file(),
        ctx=ToolContext(),
        tool_call=ToolCall(
            tool_use_id="u2-whitespace",
            tool_name="edit_file",
            arguments={
                "path": "src/a.py",
                "old_text": "    ",
                "new_text": "x",
            },
        ),
    )

    assert result is None


@pytest.mark.asyncio
async def test_edit_file_multi_replacement_shape_passes() -> None:
    result = await preflight_tool_call(
        registry=_registry_with_edit_file(),
        ctx=ToolContext(),
        tool_call=ToolCall(
            tool_use_id="u3",
            tool_name="edit_file",
            arguments={
                "path": "src/a.py",
                "edits": [{"old_text": "before", "new_text": "after"}],
            },
        ),
    )

    assert result is None


@pytest.mark.asyncio
async def test_edit_file_multi_replacement_alias_shape_passes() -> None:
    result = await preflight_tool_call(
        registry=_registry_with_edit_file(),
        ctx=ToolContext(),
        tool_call=ToolCall(
            tool_use_id="u3-alias",
            tool_name="edit_file",
            arguments={
                "path": "src/a.py",
                "edits": [{"oldText": "before", "newText": "after"}],
            },
        ),
    )

    assert result is None


@pytest.mark.asyncio
async def test_apply_patch_empty_arguments_are_rejected_before_handler() -> None:
    events: list[dict[str, object]] = []
    result = await preflight_tool_call(
        registry=_registry_with_apply_patch(),
        ctx=ToolContext(on_runtime_event=events.append, session_key="agent:test"),
        tool_call=ToolCall(
            tool_use_id="u4",
            tool_name="apply_patch",
            arguments={},
        ),
    )

    _assert_invalid_execution_status(result, "missing_executable_shape")
    payload = _payload(result)
    assert payload["status"] == "rejected"
    assert payload["reason_code"] == "missing_executable_shape"
    assert payload["tool"] == "apply_patch"
    assert payload["received_keys"] == []
    assert payload["retry_allowed"] is True
    assert payload["error_class"] == "InvalidToolArgumentsError"
    assert "patch" in payload["user_message"]
    matching = [
        event
        for event in events
        if event["name"] == "dispatch.invalid_tool_arguments"
    ]
    assert len(matching) == 1
    event = matching[0]
    assert event["reason"] == "missing_executable_shape"
    assert event["tool"] == "apply_patch"
    assert event["executed"] is False


@pytest.mark.asyncio
async def test_apply_patch_inline_patch_shape_passes() -> None:
    result = await preflight_tool_call(
        registry=_registry_with_apply_patch(),
        ctx=ToolContext(),
        tool_call=ToolCall(
            tool_use_id="u5",
            tool_name="apply_patch",
            arguments={"patch": "*** Begin Patch\n*** End Patch"},
        ),
    )

    assert result is None
