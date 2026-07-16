from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, get_args, get_origin, get_type_hints

import pytest

from opensquilla.engine.types import ToolResult, ToolResultEvent
from opensquilla.sandbox.operation_runtime import SandboxToolDescriptor
from opensquilla.tools import types as tool_types
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.rpc_payload import tools_catalog_payload, tools_effective_payload


async def _handler() -> str:
    return "ok"


def test_projection_callable_aliases_have_expected_shapes() -> None:
    model_projector = getattr(tool_types, "ModelResultProjector", None)
    sources_projector = getattr(tool_types, "ResultSourcesProjector", None)

    assert model_projector is not None
    assert get_origin(model_projector) is Callable
    assert get_args(model_projector) == ([str], str)
    assert sources_projector is not None
    assert get_origin(sources_projector) is Callable
    assert get_args(sources_projector) == ([str], list[dict[str, Any]])


def test_tool_spec_projection_carriers_are_default_off_and_positional_compatible() -> None:
    sandbox = SandboxToolDescriptor.custom(kind="probe")
    spec = tool_types.ToolSpec(
        "probe",
        "Probe tool",
        {"query": {"type": "string"}},
        ["query"],
        True,
        False,
        12.0,
        "timeout",
        1.5,
        "external",
        sandbox,
    )

    assert spec.sandbox is sandbox
    assert spec.model_result_projector is None
    assert spec.result_sources_projector is None

    def project_model(content: str) -> str:
        return content.upper()

    def project_sources(content: str) -> list[dict[str, Any]]:
        return [{"content": content}]

    configured = tool_types.ToolSpec(
        name="projected",
        description="Projected tool",
        parameters={},
        model_result_projector=project_model,
        result_sources_projector=project_sources,
    )
    hints = get_type_hints(tool_types.ToolSpec)

    assert configured.model_result_projector is project_model
    assert configured.result_sources_projector is project_sources
    assert hints["model_result_projector"] == tool_types.ModelResultProjector | None
    assert hints["result_sources_projector"] == tool_types.ResultSourcesProjector | None


@pytest.mark.asyncio
async def test_projection_callables_stay_internal_to_tool_descriptors() -> None:
    projector_calls: list[tuple[str, str]] = []

    def project_model(content: str) -> str:
        projector_calls.append(("model", content))
        return content.upper()

    def project_sources(content: str) -> list[dict[str, Any]]:
        projector_calls.append(("sources", content))
        return [{"content": content}]

    registry = ToolRegistry()
    registry.register(
        tool_types.ToolSpec(
            name="projected_probe",
            description="Projected probe",
            parameters={"query": {"type": "string"}},
            required=["query"],
            model_result_projector=project_model,
            result_sources_projector=project_sources,
        ),
        _handler,
    )

    model_definition = registry.to_tool_definitions()[0].model_dump(mode="json")
    catalog = await tools_catalog_payload({}, tool_registry=registry)
    effective = await tools_effective_payload({}, tool_registry=registry)

    assert model_definition == {
        "name": "projected_probe",
        "description": "Projected probe",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additional_properties": None,
        },
        "execution_timeout_seconds": None,
        "execution_timeout_argument": None,
        "execution_timeout_padding": 0.0,
    }
    assert catalog == {
        "tools": [
            {
                "name": "projected_probe",
                "description": "Projected probe",
                "schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "source": "builtin",
                "enabled": True,
            }
        ]
    }
    assert effective == {
        "tools": [
            {
                "name": "projected_probe",
                "description": "Projected probe",
                "schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ]
    }
    serialized = json.dumps(
        {"model": model_definition, "catalog": catalog, "effective": effective},
        sort_keys=True,
    )
    assert "model_result_projector" not in serialized
    assert "result_sources_projector" not in serialized
    assert projector_calls == []


@pytest.mark.parametrize(
    ("tool_name", "content"),
    [
        ("web_search", "search bytes: \x00\xff"),
        ("web_fetch", "fetch bytes: \n\t"),
        ("ordinary_probe", "ordinary bytes: unchanged"),
    ],
)
def test_unconfigured_tool_results_keep_content_and_empty_sources(
    tool_name: str,
    content: str,
) -> None:
    result = ToolResult("use-1", tool_name, content, False, [], None, False)

    assert result.content == content
    assert result.sources == []

    result.sources.append({"url": "https://example.test/source"})
    second = ToolResult("use-2", tool_name, content)
    assert second.sources == []


def test_tool_result_event_sources_are_default_empty_and_independent() -> None:
    event = ToolResultEvent(
        "use-1",
        "web_search",
        "unchanged result",
        False,
        {"query": "probe"},
        None,
    )

    assert event.result == "unchanged result"
    assert event.sources == []

    event.sources.append({"url": "https://example.test/source"})
    second = ToolResultEvent(tool_use_id="use-2", tool_name="web_search", result="ok")
    assert second.sources == []
