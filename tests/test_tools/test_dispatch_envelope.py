from __future__ import annotations

import asyncio
import json

import pytest

from opensquilla.engine.types import ToolCall
from opensquilla.result_budget import ToolResultBudgetClass, ToolResultBudgetPolicy
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

    async def boom() -> str:
        raise ValueError("bad argument")

    async def echo(value: str = "") -> str:
        return value

    async def pending() -> str:
        return json.dumps(
            {
                "status": "approval_required",
                "approval_id": "abc123",
                "command": "rm secret",
                "warning": "destructive",
                "message": "Resolve this approval via exec.approval.resolve",
            }
        )

    registry.register(ToolSpec(name="boom", description="boom", parameters={}), boom)
    registry.register(
        ToolSpec(
            name="echo",
            description="echo",
            parameters={"value": {"type": "string"}},
        ),
        echo,
    )
    registry.register(ToolSpec(name="pending", description="pending", parameters={}), pending)
    return registry


@pytest.mark.asyncio
async def test_dispatch_missing_tool_returns_five_field_error_envelope() -> None:
    # Use a trusted CLI ctx so the descriptive ``ToolNotFound`` branch is
    # exercised. Anonymous/CHANNEL callers receive an opaque ``PolicyDenied``
    # envelope to prevent registry enumeration; that branch is covered in
    # ``test_dispatch_surface_hardening``.
    handler = build_tool_handler(
        _build_registry(),
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            agent_id="main",
            session_key="cli:main:envelope",
        ),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-1",
            tool_name="nope",
            arguments={},
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert set(payload.keys()) == {
        "status",
        "tool",
        "error_class",
        "user_message",
        "retry_allowed",
    }
    assert payload["status"] == "error"
    assert payload["tool"] == "nope"
    assert payload["error_class"] == "ToolNotFound"


@pytest.mark.asyncio
async def test_dispatch_tool_exception_envelope_is_canonical_five_key_shape() -> None:
    handler = build_tool_handler(_build_registry())

    result = await handler(
        ToolCall(
            tool_use_id="tc-2",
            tool_name="boom",
            arguments={},
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["tool"] == "boom"
    assert payload["error_class"] == "ValueError"
    assert set(payload.keys()) == {
        "status",
        "tool",
        "error_class",
        "user_message",
        "retry_allowed",
    }


@pytest.mark.asyncio
async def test_dispatch_rejects_unparsed_raw_tool_arguments_before_handler() -> None:
    handler = build_tool_handler(_build_registry())

    result = await handler(
        ToolCall(
            tool_use_id="tc-raw",
            tool_name="echo",
            arguments={"_raw": '{"value": "unescaped " quote"}'},
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["tool"] == "echo"
    assert payload["error_class"] == "InvalidToolArgumentsError"
    assert payload["retry_allowed"] is False
    assert "valid JSON" in payload["user_message"]


@pytest.mark.asyncio
async def test_dispatch_rejects_provider_compacted_tool_arguments_before_handler() -> None:
    handler = build_tool_handler(_build_registry())

    result = await handler(
        ToolCall(
            tool_use_id="tc-compacted",
            tool_name="echo",
            arguments={
                "_opensquilla_compacted_tool_arguments": True,
                "head": '{"value": "large',
                "tail": 'payload"}',
            },
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["tool"] == "echo"
    assert payload["error_class"] == "ProjectedToolArgumentsError"
    assert payload["retry_allowed"] is False
    assert "compacted" in payload["user_message"]


@pytest.mark.asyncio
async def test_dispatch_unsupported_surface_approval_payload_is_pending_status() -> None:
    handler = build_tool_handler(_build_registry())
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CHANNEL,
            interaction_mode=InteractionMode.UNATTENDED,
            session_key="agent:main:demo",
            agent_id="main",
        )
    )
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-3",
                tool_name="pending",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is False
    assert result.execution_status is not None
    assert result.execution_status["status"] == "unknown"
    assert result.execution_status["reason"] == "approval_pending"
    assert result.execution_status["preservation_class"] == "ephemeral"
    payload = json.loads(result.content)
    assert payload["status"] == "error"
    assert payload["tool"] == "pending"
    assert payload["error_class"] == "UnsupportedSurface"
    assert payload["retry_allowed"] is False


@pytest.mark.asyncio
async def test_dispatch_unattended_cli_approval_payload_is_pending_status() -> None:
    handler = build_tool_handler(_build_registry())
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            interaction_mode=InteractionMode.UNATTENDED,
            session_key="agent:main:demo",
            agent_id="main",
        )
    )
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-4",
                tool_name="pending",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is False
    assert result.execution_status is not None
    assert result.execution_status["status"] == "unknown"
    assert result.execution_status["reason"] == "approval_pending"
    payload = json.loads(result.content)
    assert set(payload.keys()) == {
        "status",
        "tool",
        "error_class",
        "user_message",
        "retry_allowed",
    }
    assert payload["status"] == "error"
    assert payload["tool"] == "pending"
    assert payload["error_class"] == "UnsupportedSurface"
    assert payload["retry_allowed"] is False


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_in_skill_name_context_raises_unsupported_surface() -> None:
    known_skill_names = {"shell"}
    # Use a trusted CLI ctx so the descriptive ``UnsupportedSurface`` skill
    # branch is exercised. CHANNEL/anonymous callers receive an opaque
    # ``PolicyDenied`` envelope to prevent skill-name enumeration; that
    # branch is covered in ``test_dispatch_surface_hardening``.
    handler = build_tool_handler(
        _build_registry(),
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            agent_id="main",
            session_key="cli:main:envelope",
        ),
        known_skill_names=known_skill_names,
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-4",
            tool_name="shell",
            arguments={},
        )
    )

    payload = json.loads(result.content)
    assert result.is_error is True
    assert payload["error_class"] == "UnsupportedSurface"
    assert payload["tool"] == "shell"
    assert "skill" in payload["user_message"].lower()


@pytest.mark.asyncio
async def test_dispatch_attaches_published_artifacts_to_tool_result() -> None:
    registry = ToolRegistry()
    artifact = {
        "id": "art-dispatch",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 4,
        "sha256": "1" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:demo",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-dispatch",
    }

    async def publish() -> str:
        ctx = current_tool_context.get()
        assert ctx is not None
        ctx.published_artifacts.append(artifact)
        return "published"

    registry.register(ToolSpec(name="publish", description="publish", parameters={}), publish)
    handler = build_tool_handler(registry)
    ctx = ToolContext(session_key="agent:main:demo")
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-5",
                tool_name="publish",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.content == "published"
    assert result.artifacts == [artifact]


@pytest.mark.asyncio
async def test_dispatch_does_not_rewrite_artifact_result_text_when_over_budget() -> None:
    registry = ToolRegistry()
    artifact = {
        "id": "art-large",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 4,
        "sha256": "2" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:demo",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-large",
    }

    async def publish() -> str:
        ctx = current_tool_context.get()
        assert ctx is not None
        ctx.published_artifacts.append(artifact)
        return "x" * 1000

    registry.register(ToolSpec(name="publish", description="publish", parameters={}), publish)
    handler = build_tool_handler(
        registry,
        ToolContext(
            session_key="agent:main:demo",
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=120,
            ),
        ),
    )

    result = await handler(
        ToolCall(tool_use_id="tc-art-large", tool_name="publish", arguments={})
    )

    assert result.content == "x" * 1000
    assert result.artifacts == [artifact]


@pytest.mark.asyncio
async def test_dispatch_leaves_under_budget_result_unchanged() -> None:
    registry = ToolRegistry()

    async def echo() -> str:
        return '{"status":"ok","value":"unchanged"}'

    registry.register(ToolSpec(name="echo", description="echo", parameters={}), echo)
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=10_000
            )
        ),
    )

    result = await handler(ToolCall(tool_use_id="tc-under", tool_name="echo", arguments={}))

    assert result.content == '{"status":"ok","value":"unchanged"}'
    assert result.is_error is False


@pytest.mark.asyncio
async def test_dispatch_bounds_unknown_huge_tool_result_without_artifact_side_effect() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        return "x" * 1000

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=120,
                max_tool_result_chars_per_turn=200,
            )
        ),
    )

    result = await handler(ToolCall(tool_use_id="tc-huge", tool_name="huge", arguments={}))

    payload = json.loads(result.content)
    assert payload["tool_result_budget_applied"] is True
    assert payload["budget_class"] == ToolResultBudgetClass.UNKNOWN.value
    assert payload["result_truncated"] is True
    assert payload["result_original_chars"] == 1000
    assert payload["result_returned_chars"] <= 120
    assert result.artifacts == []
    assert len(result.content) < 400


@pytest.mark.asyncio
async def test_dispatch_clamps_web_fetch_max_chars_before_handler() -> None:
    registry = ToolRegistry()
    seen: dict[str, object] = {}

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        seen["url"] = url
        seen["max_chars"] = max_chars
        return "ok"

    registry.register(
        ToolSpec(
            name="web_fetch",
            description="fetch",
            parameters={"url": {"type": "string"}, "max_chars": {"type": "integer"}},
            result_budget_class="external",
        ),
        web_fetch,
    )
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(max_web_fetch_chars=12_000)
        ),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-fetch",
            tool_name="web_fetch",
            arguments={"url": "https://example.com", "max_chars": 1_000_000},
        )
    )

    assert result.content == "ok"
    assert seen == {"url": "https://example.com", "max_chars": 12_000}


@pytest.mark.asyncio
async def test_dispatch_clamps_web_search_results_before_handler() -> None:
    registry = ToolRegistry()
    seen: dict[str, object] = {}

    async def web_search(query: str, max_results: int | None = None) -> str:
        seen["query"] = query
        seen["max_results"] = max_results
        return json.dumps({"results": []})

    registry.register(
        ToolSpec(
            name="web_search",
            description="search",
            parameters={"query": {"type": "string"}, "max_results": {"type": "integer"}},
            result_budget_class="external",
        ),
        web_search,
    )
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(max_web_search_results=10)
        ),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-search",
            tool_name="web_search",
            arguments={"query": "test", "max_results": 1000},
        )
    )

    assert json.loads(result.content) == {"results": []}
    assert seen == {"query": "test", "max_results": 10}


@pytest.mark.asyncio
async def test_dispatch_preserves_sessions_yield_control_json_when_bounding() -> None:
    registry = ToolRegistry()

    async def sessions_yield() -> str:
        return json.dumps(
            {
                "status": "yielded",
                "waited": False,
                "message": "Current turn yielded; wait for pushed session events.",
                "yield_message": "y" * 1000,
            }
        )

    registry.register(
        ToolSpec(
            name="sessions_yield",
            description="yield",
            parameters={},
            result_budget_class="control",
        ),
        sessions_yield,
    )
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=160
            )
        ),
    )

    result = await handler(
        ToolCall(tool_use_id="tc-yield", tool_name="sessions_yield", arguments={})
    )

    payload = json.loads(result.content)
    assert payload["status"] == "yielded"
    assert payload["waited"] is False
    assert payload["tool_result_budget_applied"] is True
    assert payload["result_truncated"] is True
    assert len(result.content) < 500


@pytest.mark.asyncio
async def test_dispatch_tracker_budget_is_fresh_for_reused_tool_context() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        return "x" * 1000

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    ctx = ToolContext(
        tool_result_budget_policy=ToolResultBudgetPolicy(
            max_single_tool_result_chars=120,
            max_tool_result_chars_per_turn=140,
        )
    )

    first_handler = build_tool_handler(registry, ctx)
    first = await first_handler(
        ToolCall(tool_use_id="tc-first", tool_name="huge", arguments={})
    )

    second_handler = build_tool_handler(registry, ctx)
    second = await second_handler(
        ToolCall(tool_use_id="tc-second", tool_name="huge", arguments={})
    )

    first_payload = json.loads(first.content)
    second_payload = json.loads(second.content)
    assert first_payload["result_returned_chars"] == second_payload["result_returned_chars"]
    assert first_payload["result_returned_chars"] > 0


@pytest.mark.asyncio
async def test_dispatch_uses_current_tool_context_budget_for_handler_without_static_ctx() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        return "x" * 1000

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    handler = build_tool_handler(registry)
    ctx = ToolContext(
        tool_result_budget_policy=ToolResultBudgetPolicy(
            max_single_tool_result_chars=120,
            max_tool_result_chars_per_turn=140,
        )
    )
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(tool_use_id="tc-current-ctx", tool_name="huge", arguments={})
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result.content)
    assert payload["tool_result_budget_applied"] is True
    assert payload["result_returned_chars"] <= 120


@pytest.mark.asyncio
async def test_dispatch_reused_handler_gets_fresh_budget_for_separate_current_contexts() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        return "x" * 1000

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    handler = build_tool_handler(registry)

    async def call_with_context() -> int:
        ctx = ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=120,
                max_tool_result_chars_per_turn=140,
            )
        )
        token = current_tool_context.set(ctx)
        try:
            result = await handler(
                ToolCall(tool_use_id="tc-current-ctx", tool_name="huge", arguments={})
            )
        finally:
            current_tool_context.reset(token)
        return int(json.loads(result.content)["result_returned_chars"])

    first = await call_with_context()
    second = await call_with_context()

    assert first == second
    assert first > 0


@pytest.mark.asyncio
async def test_dispatch_tracker_limits_concurrent_tool_results_per_turn() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        await asyncio.sleep(0)
        return "x" * 1000

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=120,
                max_tool_result_chars_per_turn=180,
            )
        ),
    )

    results = await asyncio.gather(
        *[
            handler(ToolCall(tool_use_id=f"tc-{idx}", tool_name="huge", arguments={}))
            for idx in range(3)
        ]
    )

    returned_total = sum(
        json.loads(result.content)["result_returned_chars"] for result in results
    )
    assert returned_total <= 180
