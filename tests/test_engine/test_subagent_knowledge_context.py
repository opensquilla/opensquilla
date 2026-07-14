from __future__ import annotations

from dataclasses import fields

from opensquilla.engine import Agent
from opensquilla.engine.subagent import SubagentSpec
from opensquilla.provider import ToolDefinition, ToolInputSchema
from opensquilla.tools.types import SUBAGENT_TOOL_DENY, ToolContext


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


def test_tool_context_has_no_rag_provider_specific_state() -> None:
    assert "knowledge_capability_snapshot" not in {
        item.name for item in fields(ToolContext)
    }


def test_child_agent_uses_generic_context_and_existing_safety_rules() -> None:
    parent = _agent(
        ToolContext(
            is_owner=False,
            allowed_tools={"parent-only"},
            denied_tools={"parent-denied"},
        )
    )

    child = parent._make_child_agent(SubagentSpec(task="child task"), depth=1)

    assert child._tool_context is not None
    assert child._tool_context.is_owner is True
    assert child._tool_context.allowed_tools is None
    assert child._tool_context.denied_tools == set(SUBAGENT_TOOL_DENY)
    assert child._tool_context.tool_run_budget_key is not None
    assert child._tool_context.tool_run_budget_key.startswith("subagent:")
    assert [definition.name for definition in child.tool_definitions] == ["read_file"]
