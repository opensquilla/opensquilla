from __future__ import annotations

from dataclasses import fields

from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, ToolSpec


async def _handler(**_: object) -> str:
    return "ok"


def _spec(name: str, parameters: dict[str, object] | None = None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} tool",
        parameters=parameters or {},
    )


def test_tool_context_has_no_rag_provider_specific_state() -> None:
    assert "knowledge_capability_snapshot" not in {item.name for item in fields(ToolContext)}


def test_registry_treats_knowledge_tool_name_as_ordinary_registration() -> None:
    registry = ToolRegistry()
    parameters = {
        "query": {"type": "string"},
        "retrieval_profile": {"type": "string"},
    }
    registry.register(_spec("knowledge_search", parameters), _handler)

    definitions = {item.name: item for item in registry.to_tool_definitions(ToolContext())}

    assert definitions["knowledge_search"].input_schema.properties == parameters
    assert registry.unregister("knowledge_search") is True
    assert "knowledge_search" not in {item.name for item in registry.to_tool_definitions()}


def test_dynamic_rag_registration_does_not_change_non_rag_tools() -> None:
    registry = ToolRegistry()
    for name in ("web_search", "web_fetch", "read_file"):
        registry.register(_spec(name, {"value": {"type": "string"}}), _handler)
    before = {
        item.name: item.model_dump(mode="json", by_alias=True)
        for item in registry.to_tool_definitions()
    }

    registry.register(_spec("knowledge_search", {"query": {"type": "string"}}), _handler)
    registry.unregister("knowledge_search")
    after = {
        item.name: item.model_dump(mode="json", by_alias=True)
        for item in registry.to_tool_definitions()
    }

    assert after == before
