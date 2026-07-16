from __future__ import annotations

import json
from dataclasses import dataclass, fields

import pytest

from opensquilla.gateway.rag_provider_runtime import RagProviderRuntime, RagProviderState
from opensquilla.gateway.rag_provider_tools import rag_provider_tool_bindings
from opensquilla.rag_provider.projections import (
    project_get_response_for_model,
    project_get_response_for_sources,
    project_search_response_for_model,
    project_search_response_for_sources,
)
from opensquilla.rag_provider.protocol import CapabilitiesSnapshot, EffectiveLimits
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.rpc_payload import tools_catalog_payload, tools_effective_payload
from opensquilla.tools.types import ToolContext, ToolSpec


async def _handler(**_: object) -> str:
    return "ok"


def _spec(name: str, parameters: dict[str, object] | None = None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} tool",
        parameters=parameters or {},
    )


@dataclass
class _RuntimeConfig:
    enabled: bool = True
    probe_interval_seconds: float = 60
    unavailable_after_seconds: float = 300
    max_consecutive_failures: int = 3
    retrieval_profile_override: str | None = None
    collection_scope: list[str] | None = None
    legacy_knowledge_adapter: bool = False

    def __post_init__(self) -> None:
        if self.collection_scope is None:
            self.collection_scope = []


class _CapabilityClient:
    def __init__(self, *, supports_get: bool) -> None:
        self.supports_get = supports_get
        self.capability_calls = 0
        self.search_calls = 0
        self.get_calls = 0

    async def capabilities(self) -> CapabilitiesSnapshot:
        self.capability_calls += 1
        return CapabilitiesSnapshot(
            protocol_version="1.1",
            provider_name="provider",
            provider_version="1.0",
            instance_id="instance",
            supports_get=self.supports_get,
            limits=EffectiveLimits(
                max_search_results=20,
                max_snippet_chars=800,
                max_search_response_chars=12_000,
                max_get_content_chars=8_000,
                max_chunk_chars=8_000,
            ),
            supports_collection_scope=False,
            retrieval_profiles=(("hybrid", "Hybrid"),),
            default_retrieval_profile="hybrid",
            management_url=None,
        )

    async def search(self, **_: object) -> None:
        self.search_calls += 1

    async def get(self, **_: object) -> None:
        self.get_calls += 1

    async def close(self) -> None:
        return None


def test_tool_context_has_no_rag_provider_specific_state() -> None:
    assert "knowledge_capability_snapshot" not in {item.name for item in fields(ToolContext)}


@pytest.mark.asyncio
async def test_projected_knowledge_specs_stay_out_of_model_and_rpc_schemas() -> None:
    registry = ToolRegistry()
    for binding in rag_provider_tool_bindings(object()).values():
        registry.register(binding.spec, binding.handler)

    definitions = {
        item.name: item.model_dump(mode="json", by_alias=True)
        for item in registry.to_tool_definitions()
    }
    catalog = await tools_catalog_payload({}, tool_registry=registry)
    effective = await tools_effective_payload({}, tool_registry=registry)
    catalog_by_name = {item["name"]: item for item in catalog["tools"]}
    effective_by_name = {item["name"]: item for item in effective["tools"]}

    assert definitions["knowledge_search"]["input_schema"]["properties"] == {
        "query": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    }
    assert definitions["knowledge_get"]["input_schema"]["properties"] == {
        "evidence_id": {"type": "string", "minLength": 1},
        "cursor": {"type": "string", "minLength": 1},
    }
    assert catalog_by_name["knowledge_search"]["schema"] == {
        "type": "object",
        "properties": definitions["knowledge_search"]["input_schema"]["properties"],
        "required": ["query"],
    }
    assert effective_by_name["knowledge_get"]["schema"] == {
        "type": "object",
        "properties": definitions["knowledge_get"]["input_schema"]["properties"],
        "required": ["evidence_id"],
    }
    serialized = json.dumps(
        {"model": definitions, "catalog": catalog, "effective": effective},
        sort_keys=True,
    )
    assert "retrievalProfile" not in serialized
    assert "retrieval_profile" not in serialized
    assert "model_result_projector" not in serialized
    assert "result_sources_projector" not in serialized


@pytest.mark.asyncio
async def test_runtime_registers_projected_tools_only_when_enabled_and_supported() -> None:
    disabled_client = _CapabilityClient(supports_get=True)
    disabled_registry = ToolRegistry()
    disabled = RagProviderRuntime(
        _RuntimeConfig(enabled=False),
        disabled_client,
        disabled_registry,
    )

    await disabled.start(start_probe_loop=False)

    assert disabled.snapshot().state is RagProviderState.DISABLED
    assert disabled_registry.list_names() == []
    assert disabled_client.capability_calls == 0
    assert disabled_client.search_calls == 0
    assert disabled_client.get_calls == 0

    enabled_client = _CapabilityClient(supports_get=False)
    enabled_registry = ToolRegistry()
    enabled = RagProviderRuntime(_RuntimeConfig(), enabled_client, enabled_registry)

    await enabled.start(start_probe_loop=False)

    assert enabled_registry.list_names() == ["knowledge_search"]
    search = enabled_registry.get("knowledge_search")
    assert search is not None
    assert search.spec.model_result_projector is project_search_response_for_model
    assert search.spec.result_sources_projector is project_search_response_for_sources
    assert enabled_client.search_calls == 0
    assert enabled_client.get_calls == 0

    enabled_client.supports_get = True
    await enabled.refresh()

    get = enabled_registry.get("knowledge_get")
    assert get is not None
    assert get.spec.model_result_projector is project_get_response_for_model
    assert get.spec.result_sources_projector is project_get_response_for_sources

    await enabled.stop()
    assert enabled_registry.list_names() == []


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
