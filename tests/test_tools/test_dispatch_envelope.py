from __future__ import annotations

import asyncio
import json

import pytest

from opensquilla.engine.types import ToolCall
from opensquilla.result_budget import (
    DEFAULT_TOOL_RUN_BUDGET_POLICY,
    ToolResultBudgetPolicy,
    ToolRunBudgetExceededError,
    ToolRunBudgetPolicy,
    build_webresearch_tool_run_budget_policy,
)
from opensquilla.tools import dispatch as dispatch_module
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


def _strict_preview_chars(content: str) -> int:
    payload = json.loads(content)
    assert payload["result_truncated"] is True
    assert "tool_result_budget_applied" not in payload
    assert "result_returned_chars" not in payload
    assert "budget_class" not in payload
    preview = payload.get("preview", "")
    assert isinstance(preview, str)
    return len(preview)


def test_webresearch_budget_profile_builder_preserves_unlimited_call_defaults() -> None:
    policy = build_webresearch_tool_run_budget_policy()

    assert policy.max_web_search_calls_per_turn is None
    assert policy.max_web_fetch_calls_per_turn is None
    assert policy.max_external_text_chars_per_turn is None
    assert policy.max_single_fetch_chars == 50_000
    assert policy.max_web_search_results == 10


def test_default_tool_run_budget_leaves_room_for_complex_turns() -> None:
    search_calls = DEFAULT_TOOL_RUN_BUDGET_POLICY.max_web_search_calls_per_turn
    fetch_calls = DEFAULT_TOOL_RUN_BUDGET_POLICY.max_web_fetch_calls_per_turn
    external_chars = DEFAULT_TOOL_RUN_BUDGET_POLICY.max_external_text_chars_per_turn
    single_fetch_chars = DEFAULT_TOOL_RUN_BUDGET_POLICY.max_single_fetch_chars
    search_results = DEFAULT_TOOL_RUN_BUDGET_POLICY.max_web_search_results

    assert search_calls is None
    assert fetch_calls is None
    assert external_chars is None
    assert single_fetch_chars is not None and single_fetch_chars >= 50_000
    assert search_results is not None and search_results >= 10


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
    assert "Do not retry unavailable tools" in payload["user_message"]


@pytest.mark.asyncio
async def test_dispatch_unknown_bash_tool_points_to_exec_command() -> None:
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
            tool_use_id="tc-bash",
            tool_name="bash",
            arguments={"cmd": "echo hi"},
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["error_class"] == "ToolNotFound"
    assert "Use exec_command with a command string instead" in payload["user_message"]
    assert "do not retry bash as a tool" in payload["user_message"]


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
    assert result.execution_status is not None
    assert result.execution_status["reason"] == "runtime_error"
    payload = json.loads(result.content)
    assert payload["tool"] == "echo"
    assert payload["error_class"] == "InvalidToolArgumentsError"
    assert payload["retry_allowed"] is False
    assert "valid JSON" in payload["user_message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker_key",
    ["_opensquilla_compacted_tool_arguments", "_opensquilla_compacted_tool_input"],
)
async def test_dispatch_rejects_provider_compacted_tool_arguments_before_handler(
    marker_key: str,
) -> None:
    handler = build_tool_handler(_build_registry())

    result = await handler(
        ToolCall(
            tool_use_id="tc-compacted",
            tool_name="echo",
            arguments={
                marker_key: True,
                "head": '{"value": "large',
                "tail": 'payload"}',
            },
        )
    )

    assert result.is_error is True
    assert result.execution_status is not None
    assert result.execution_status["reason"] == "provider_context_projection_reused"
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
async def test_dispatch_leaves_default_huge_tool_result_unchanged() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        return "x" * 1000

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    handler = build_tool_handler(registry)

    result = await handler(ToolCall(tool_use_id="tc-huge-default", tool_name="huge", arguments={}))

    assert result.content == "x" * 1000
    assert result.artifacts == []


@pytest.mark.asyncio
async def test_dispatch_strict_policy_bounds_unknown_huge_tool_result() -> None:
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
    assert payload["result_truncated"] is True
    assert payload["result_original_chars"] == 1000
    assert len(payload["preview"]) <= 120
    assert "tool_result_budget_applied" not in payload
    assert "result_returned_chars" not in payload
    assert "budget_class" not in payload
    assert result.artifacts == []
    assert len(result.content) < 400


@pytest.mark.asyncio
async def test_dispatch_preserves_error_preview_after_turn_budget_is_exhausted() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        return "x" * 1000

    async def missing_capability() -> str:
        return json.dumps(
            {
                "status": "blocked",
                "message": "Skill not found: nano-banana",
            }
        )

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    registry.register(
        ToolSpec(name="missing_capability", description="missing", parameters={}),
        missing_capability,
    )
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=1000,
                max_tool_result_chars_per_turn=5,
            )
        ),
    )

    await handler(ToolCall(tool_use_id="tc-huge", tool_name="huge", arguments={}))
    result = await handler(
        ToolCall(
            tool_use_id="tc-missing",
            tool_name="missing_capability",
            arguments={},
        )
    )

    payload = json.loads(result.content)
    assert result.is_error is True
    assert payload["status"] == "blocked"
    assert payload["message"] == "Skill not found: nano-banana"


@pytest.mark.asyncio
async def test_dispatch_preserves_control_status_after_turn_budget_is_exhausted() -> None:
    registry = ToolRegistry()

    async def huge() -> str:
        return "x" * 1000

    async def control_error() -> str:
        return json.dumps(
            {
                "status": "error",
                "user_message": "Missing required path.",
                "retry_allowed": False,
            }
        )

    registry.register(ToolSpec(name="huge", description="huge", parameters={}), huge)
    registry.register(
        ToolSpec(
            name="control_error",
            description="control",
            parameters={},
            result_budget_class="control",
        ),
        control_error,
    )
    handler = build_tool_handler(
        registry,
        ToolContext(
            tool_result_budget_policy=ToolResultBudgetPolicy(
                max_single_tool_result_chars=1000,
                max_tool_result_chars_per_turn=5,
            )
        ),
    )

    await handler(ToolCall(tool_use_id="tc-huge", tool_name="huge", arguments={}))
    result = await handler(
        ToolCall(tool_use_id="tc-control", tool_name="control_error", arguments={})
    )

    payload = json.loads(result.content)
    assert payload["status"] == "error"
    assert payload["user_message"] == "Missing required path."
    assert payload["retry_allowed"] is False


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
            tool_run_budget_policy=ToolRunBudgetPolicy(max_single_fetch_chars=12_000)
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
            tool_run_budget_policy=ToolRunBudgetPolicy(max_web_search_results=10)
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
async def test_dispatch_run_budget_blocks_exhausted_external_call_before_handler() -> None:
    registry = ToolRegistry()
    calls = 0

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        nonlocal calls
        calls += 1
        return f"{url}:{max_chars}"

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
            tool_run_budget_key="dispatch-test-fetch-limit",
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_fetch_calls_per_turn=1,
                max_single_fetch_chars=500,
                max_external_text_chars_per_turn=1_000,
            ),
        ),
    )

    first = await handler(
        ToolCall(
            tool_use_id="tc-fetch-1",
            tool_name="web_fetch",
            arguments={"url": "https://example.com", "max_chars": 10_000},
        )
    )
    second = await handler(
        ToolCall(
            tool_use_id="tc-fetch-2",
            tool_name="web_fetch",
            arguments={"url": "https://example.com/again", "max_chars": 10_000},
        )
    )

    assert first.content == "https://example.com:500"
    assert calls == 1
    assert second.is_error is False
    assert second.execution_status is not None
    assert second.execution_status["status"] == "unknown"
    assert second.execution_status["reason"] == "tool_run_budget_exhausted"
    payload = json.loads(second.content)
    assert payload["status"] == "control"
    assert payload["reason"] == "tool_run_budget_exhausted"
    assert payload["retry_allowed"] is False
    assert "larger budget" not in payload["user_message"]
    assert "runtime resource guard" in payload["user_message"]


@pytest.mark.asyncio
async def test_dispatch_run_budget_abort_releases_failed_external_reservation() -> None:
    registry = ToolRegistry()
    fail_next = True
    seen_max_chars: list[int | None] = []

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        nonlocal fail_next
        seen_max_chars.append(max_chars)
        if fail_next:
            fail_next = False
            raise RuntimeError("temporary failure")
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
            tool_run_budget_key="dispatch-test-fetch-abort",
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_fetch_calls_per_turn=1,
                max_single_fetch_chars=400,
                max_external_text_chars_per_turn=400,
            ),
        ),
    )

    failed = await handler(
        ToolCall(
            tool_use_id="tc-fetch-fail",
            tool_name="web_fetch",
            arguments={"url": "https://example.com", "max_chars": 10_000},
        )
    )
    retried = await handler(
        ToolCall(
            tool_use_id="tc-fetch-retry",
            tool_name="web_fetch",
            arguments={"url": "https://example.com", "max_chars": 10_000},
        )
    )

    assert failed.is_error is True
    assert retried.content == "ok"
    assert seen_max_chars == [400, 400]


@pytest.mark.asyncio
async def test_dispatch_run_budget_exception_after_reservation_is_control() -> None:
    registry = ToolRegistry()
    calls = 0

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        nonlocal calls
        del url, max_chars
        calls += 1
        raise ToolRunBudgetExceededError("web_fetch", "internal run budget")

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
            tool_run_budget_key="dispatch-test-fetch-internal-budget",
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_fetch_calls_per_turn=1,
                max_single_fetch_chars=400,
                max_external_text_chars_per_turn=400,
            ),
        ),
    )

    first = await handler(
        ToolCall(
            tool_use_id="tc-fetch-internal-budget-1",
            tool_name="web_fetch",
            arguments={"url": "https://example.com"},
        )
    )
    second = await handler(
        ToolCall(
            tool_use_id="tc-fetch-internal-budget-2",
            tool_name="web_fetch",
            arguments={"url": "https://example.com"},
        )
    )

    assert calls == 2
    for result in (first, second):
        assert result.is_error is False
        assert result.execution_status is not None
        assert result.execution_status["status"] == "unknown"
        assert result.execution_status["reason"] == "tool_run_budget_exhausted"
        assert json.loads(result.content)["status"] == "control"


@pytest.mark.asyncio
async def test_dispatch_run_budget_limits_concurrent_external_calls_atomically() -> None:
    registry = ToolRegistry()
    started = 0

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        nonlocal started
        started += 1
        await asyncio.sleep(0)
        return url

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
            tool_run_budget_key="dispatch-test-fetch-concurrent",
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_fetch_calls_per_turn=1,
                max_single_fetch_chars=400,
                max_external_text_chars_per_turn=1_000,
            ),
        ),
    )

    results = await asyncio.gather(
        handler(
            ToolCall(
                tool_use_id="tc-fetch-a",
                tool_name="web_fetch",
                arguments={"url": "https://example.com/a"},
            )
        ),
        handler(
            ToolCall(
                tool_use_id="tc-fetch-b",
                tool_name="web_fetch",
                arguments={"url": "https://example.com/b"},
            )
        ),
    )

    assert started == 1
    assert sum(result.is_error for result in results) == 0
    control_payloads = []
    for result in results:
        try:
            payload = json.loads(result.content)
        except ValueError:
            continue
        if payload.get("status") == "control":
            control_payloads.append(payload)
    assert len(control_payloads) == 1
    assert any(
        result.execution_status
        and result.execution_status["reason"] == "tool_run_budget_exhausted"
        for result in results
    )


@pytest.mark.asyncio
async def test_dispatch_run_budget_allows_oversized_result_then_controls_retry() -> None:
    registry = ToolRegistry()

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        return "x" * 250

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
            tool_run_budget_key="dispatch-test-fetch-result-budget",
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_fetch_calls_per_turn=2,
                max_single_fetch_chars=200,
                max_external_text_chars_per_turn=200,
            ),
        ),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-fetch-large",
            tool_name="web_fetch",
            arguments={"url": "https://example.com", "max_chars": 200},
        )
    )
    retry = await handler(
        ToolCall(
            tool_use_id="tc-fetch-after-large",
            tool_name="web_fetch",
            arguments={"url": "https://example.com", "max_chars": 200},
        )
    )

    assert result.is_error is False
    assert result.execution_status is None
    assert result.content == "x" * 250
    assert retry.is_error is False
    assert retry.execution_status is not None
    assert retry.execution_status["status"] == "unknown"
    assert retry.execution_status["reason"] == "tool_run_budget_exhausted"
    payload = json.loads(retry.content)
    assert payload["status"] == "control"
    assert payload["reason"] == "tool_run_budget_exhausted"
    assert "larger budget" not in payload["user_message"]


@pytest.mark.asyncio
async def test_dispatch_logs_webresearch_run_diagnostics_without_default_call_caps(
    monkeypatch,
) -> None:
    registry = ToolRegistry()

    async def web_search(query: str, max_results: int | None = None) -> str:
        return json.dumps({"query": query, "results": ["one", "two"]})

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
        ToolContext(tool_run_budget_key="dispatch-test-search-diagnostics"),
    )

    log_events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        dispatch_module.log,
        "debug",
        lambda event, **payload: log_events.append((event, payload)),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-search-diagnostics",
            tool_name="web_search",
            arguments={"query": "test", "max_results": 3},
        )
    )

    assert result.is_error is False
    assert json.loads(result.content)["results"] == ["one", "two"]
    event = next(
        payload
        for name, payload in log_events
        if name == "dispatch.webresearch_tool_run_diagnostics"
    )
    assert event["tool"] == "web_search"
    assert event["tool_use_id"] == "tc-search-diagnostics"
    assert event["web_search_calls_used"] == 1
    assert event["web_fetch_calls_used"] == 0
    assert event["external_text_chars_used"] >= len(result.content)
    assert event["tool_wall_time_ms"] >= 0


@pytest.mark.asyncio
async def test_dispatch_run_budget_charges_web_search_external_text() -> None:
    registry = ToolRegistry()

    async def web_search(query: str, max_results: int | None = None) -> str:
        return json.dumps({"query": query, "results": ["x" * 250]})

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
            tool_run_budget_key="dispatch-test-search-result-budget",
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_search_calls_per_turn=2,
                max_external_text_chars_per_turn=200,
            ),
        ),
    )

    result = await handler(
        ToolCall(
            tool_use_id="tc-search-large",
            tool_name="web_search",
            arguments={"query": "test", "max_results": 10},
        )
    )
    retry = await handler(
        ToolCall(
            tool_use_id="tc-search-after-large",
            tool_name="web_search",
            arguments={"query": "test", "max_results": 10},
        )
    )

    assert result.is_error is False
    assert result.execution_status is None
    assert json.loads(result.content)["results"] == ["x" * 250]
    assert retry.is_error is False
    assert retry.execution_status is not None
    assert retry.execution_status["status"] == "unknown"
    assert retry.execution_status["reason"] == "tool_run_budget_exhausted"
    payload = json.loads(retry.content)
    assert payload["status"] == "control"
    assert payload["reason"] == "tool_run_budget_exhausted"
    assert "larger budget" not in payload["user_message"]


@pytest.mark.asyncio
async def test_dispatch_run_budget_is_fresh_for_separate_current_contexts() -> None:
    registry = ToolRegistry()

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        return f"{url}:{max_chars}"

    registry.register(
        ToolSpec(
            name="web_fetch",
            description="fetch",
            parameters={"url": {"type": "string"}, "max_chars": {"type": "integer"}},
            result_budget_class="external",
        ),
        web_fetch,
    )
    handler = build_tool_handler(registry)

    async def call_with_new_turn(turn_id: str) -> str:
        token = current_tool_context.set(
            ToolContext(
                session_key=f"agent:main:{turn_id}",
                tool_run_budget_key=f"agent:main:{turn_id}:turn-budget",
                tool_run_budget_policy=ToolRunBudgetPolicy(
                    max_web_fetch_calls_per_turn=1,
                    max_single_fetch_chars=300,
                    max_external_text_chars_per_turn=500,
                ),
            )
        )
        try:
            first = await handler(
                ToolCall(
                    tool_use_id=f"tc-{turn_id}-1",
                    tool_name="web_fetch",
                    arguments={"url": f"https://example.com/{turn_id}/first"},
                )
            )
            second = await handler(
                ToolCall(
                    tool_use_id=f"tc-{turn_id}-2",
                    tool_name="web_fetch",
                    arguments={"url": f"https://example.com/{turn_id}/second"},
                )
            )
        finally:
            current_tool_context.reset(token)

        assert first.is_error is False
        assert second.is_error is False
        assert second.execution_status is not None
        assert second.execution_status["status"] == "unknown"
        assert second.execution_status["reason"] == "tool_run_budget_exhausted"
        return first.content

    first_turn = await call_with_new_turn("turn-a")
    second_turn = await call_with_new_turn("turn-b")

    assert first_turn == "https://example.com/turn-a/first:300"
    assert second_turn == "https://example.com/turn-b/first:300"


@pytest.mark.asyncio
async def test_dispatch_run_budget_without_key_does_not_leak_across_handler_reuse() -> None:
    registry = ToolRegistry()

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        return f"{url}:{max_chars}"

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
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_fetch_calls_per_turn=1,
                max_single_fetch_chars=300,
                max_external_text_chars_per_turn=500,
            )
        ),
    )

    first = await handler(
        ToolCall(
            tool_use_id="tc-reuse-a",
            tool_name="web_fetch",
            arguments={"url": "https://example.com/a"},
        )
    )
    second = await handler(
        ToolCall(
            tool_use_id="tc-reuse-b",
            tool_name="web_fetch",
            arguments={"url": "https://example.com/b"},
        )
    )

    assert first.content == "https://example.com/a:300"
    assert second.content == "https://example.com/b:300"


@pytest.mark.asyncio
async def test_dispatch_run_budget_applies_to_subagent_current_context() -> None:
    registry = ToolRegistry()
    calls = 0

    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        nonlocal calls
        calls += 1
        return f"{url}:{max_chars}"

    registry.register(
        ToolSpec(
            name="web_fetch",
            description="fetch",
            parameters={"url": {"type": "string"}, "max_chars": {"type": "integer"}},
            result_budget_class="external",
        ),
        web_fetch,
    )
    handler = build_tool_handler(registry)
    token = current_tool_context.set(
        ToolContext(
            session_key="subagent:agent:main:webchat:demo",
            caller_kind=CallerKind.SUBAGENT,
            tool_run_budget_key="subagent:agent:main:webchat:demo:worker:1",
            tool_run_budget_policy=ToolRunBudgetPolicy(
                max_web_fetch_calls_per_turn=1,
                max_single_fetch_chars=300,
                max_external_text_chars_per_turn=500,
            ),
        )
    )
    try:
        first = await handler(
            ToolCall(
                tool_use_id="tc-subagent-a",
                tool_name="web_fetch",
                arguments={"url": "https://example.com/a"},
            )
        )
        second = await handler(
            ToolCall(
                tool_use_id="tc-subagent-b",
                tool_name="web_fetch",
                arguments={"url": "https://example.com/b"},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert first.content == "https://example.com/a:300"
    assert calls == 1
    assert second.is_error is False
    assert second.execution_status is not None
    assert second.execution_status["status"] == "unknown"
    assert second.execution_status["reason"] == "tool_run_budget_exhausted"


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
            tool_result_budget_policy=ToolResultBudgetPolicy(max_single_tool_result_chars=160)
        ),
    )

    result = await handler(
        ToolCall(tool_use_id="tc-yield", tool_name="sessions_yield", arguments={})
    )

    payload = json.loads(result.content)
    assert payload["status"] == "yielded"
    assert payload["waited"] is False
    assert payload["result_truncated"] is True
    assert "tool_result_budget_applied" not in payload
    assert "result_returned_chars" not in payload
    assert "budget_class" not in payload
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

    assert _strict_preview_chars(first.content) == _strict_preview_chars(second.content)
    assert _strict_preview_chars(first.content) > 0


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

    assert _strict_preview_chars(result.content) <= 120


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
        return _strict_preview_chars(result.content)

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

    returned_total = sum(_strict_preview_chars(result.content) for result in results)
    assert returned_total <= 180
