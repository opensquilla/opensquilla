from __future__ import annotations

from opensquilla.engine import Agent
from opensquilla.engine.subagent import SubagentSpec
from opensquilla.knowledge.runtime import (
    KnowledgeCapabilitySnapshot,
    KnowledgeConnectionState,
)
from opensquilla.provider import ToolDefinition, ToolInputSchema
from opensquilla.tools.types import (
    SUBAGENT_TOOL_DENY,
    ToolContext,
    current_tool_context,
)


def _snapshot() -> KnowledgeCapabilitySnapshot:
    return KnowledgeCapabilitySnapshot(
        state=KnowledgeConnectionState.READY,
        capabilities_version="0123456789abcdef",
        profiles=(),
        configured_default=None,
        effective_default=None,
        fallback_reason=None,
        fetched_at_ms=1,
        service_status={},
    )


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} tool",
        input_schema=ToolInputSchema(properties={}, required=[]),
    )


def _agent(tool_context: ToolContext | None) -> Agent:
    return Agent(
        provider=object(),  # type: ignore[arg-type]
        tool_context=tool_context,
        tool_definitions=[_definition("read_file"), _definition("subagents")],
    )


def test_child_agent_keeps_parent_knowledge_snapshot_identity_only() -> None:
    snapshot = _snapshot()
    parent = _agent(
        ToolContext(
            is_owner=False,
            allowed_tools={"parent-only"},
            denied_tools={"parent-denied"},
            knowledge_capability_snapshot=snapshot,
        )
    )

    child = parent._make_child_agent(SubagentSpec(task="child task"), depth=1)

    assert child._tool_context is not None
    assert child._tool_context.knowledge_capability_snapshot is snapshot
    assert child._tool_context.is_owner is True
    assert child._tool_context.allowed_tools is None
    assert child._tool_context.denied_tools == set(SUBAGENT_TOOL_DENY)
    assert child._tool_context.tool_run_budget_key is not None
    assert child._tool_context.tool_run_budget_key.startswith("subagent:")
    assert [definition.name for definition in child.tool_definitions] == ["read_file"]


def test_child_agent_prefers_active_parent_knowledge_snapshot() -> None:
    stored_snapshot = _snapshot()
    active_snapshot = _snapshot()
    parent = _agent(
        ToolContext(knowledge_capability_snapshot=stored_snapshot)
    )
    token = current_tool_context.set(
        ToolContext(knowledge_capability_snapshot=active_snapshot)
    )
    try:
        child = parent._make_child_agent(SubagentSpec(task="child task"), depth=1)
    finally:
        current_tool_context.reset(token)

    assert child._tool_context is not None
    assert child._tool_context.knowledge_capability_snapshot is active_snapshot


def test_child_agent_keeps_none_knowledge_snapshot_behavior() -> None:
    parent = _agent(None)

    child = parent._make_child_agent(SubagentSpec(task="child task"), depth=1)

    assert child._tool_context is not None
    assert child._tool_context.knowledge_capability_snapshot is None
