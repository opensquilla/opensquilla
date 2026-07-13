from __future__ import annotations

import copy
import json

import pytest
import structlog.testing

from opensquilla.engine.types import ToolCall
from opensquilla.knowledge.runtime import (
    KnowledgeCapabilitySnapshot,
    KnowledgeConnectionState,
    RetrievalProfileCapability,
)
from opensquilla.tools.builtin.knowledge_tools import create_knowledge_tools
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.policy import ToolSurfaceCapabilities
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, InteractionMode, ToolContext, ToolSpec


async def _handler() -> str:
    return "ok"


def _knowledge_snapshot(
    state: KnowledgeConnectionState,
) -> KnowledgeCapabilitySnapshot:
    return KnowledgeCapabilitySnapshot(
        state=state,
        capabilities_version="0123456789abcdef",
        profiles=(
            RetrievalProfileCapability(
                id="lexical",
                label="Lexical",
                kind="lexical",
                available=True,
            ),
            RetrievalProfileCapability(
                id="vector-disabled",
                label="Vector disabled",
                kind="vector",
                available=False,
            ),
            RetrievalProfileCapability(
                id="hybrid",
                label="Hybrid",
                kind="hybrid",
                available=True,
            ),
        ),
        configured_default="lexical",
        effective_default="lexical",
        fallback_reason=None,
        fetched_at_ms=1,
        service_status={},
        stale=state is KnowledgeConnectionState.DEGRADED,
        legacy=state is KnowledgeConnectionState.LEGACY,
    )


def _spec(name: str, *, exposed_by_default: bool = True) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} tool",
        parameters={},
        exposed_by_default=exposed_by_default,
    )


def test_register_overwrite_warns() -> None:
    registry = ToolRegistry()
    registry.register(_spec("dup"), _handler)

    with structlog.testing.capture_logs() as captured:
        registry.register(_spec("dup"), _handler)

    assert any(
        event["event"] == "registry.tool_overwrite" and event["name"] == "dup"
        for event in captured
    )


def test_surfaced_tools_make_hidden_tools_visible() -> None:
    registry = ToolRegistry()
    registry.register(_spec("visible"), _handler)
    registry.register(_spec("hidden", exposed_by_default=False), _handler)
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        surfaced_tools={"hidden"},
    )

    names = {tool.name for tool in registry.to_tool_definitions(ctx)}

    assert names == {"visible", "hidden"}


def test_allowed_tools_remains_strict_when_tool_is_surfaced() -> None:
    registry = ToolRegistry()
    registry.register(_spec("visible"), _handler)
    registry.register(_spec("hidden", exposed_by_default=False), _handler)
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        allowed_tools={"visible"},
        surfaced_tools={"hidden"},
    )

    names = {tool.name for tool in registry.to_tool_definitions(ctx)}

    assert names == {"visible"}


def test_default_registry_removes_obsolete_wrapper_tools_but_keeps_canonical_tools() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registry = get_default_registry()

    assert registry.get("generate_image") is None
    assert registry.get("spawn_subagent") is None
    assert registry.get("send_message") is None

    assert registry.get("image_generate") is not None
    assert registry.get("sessions_spawn") is not None
    assert registry.get("sessions_send") is not None
    assert registry.get("subagents") is not None


def test_owner_schema_keeps_canonical_tools_and_subagents_stays_explicit_only() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registry = get_default_registry()
    owner_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)

    default_names = {tool.name for tool in registry.to_tool_definitions(owner_ctx)}
    assert {"image_generate", "sessions_spawn", "sessions_send"} <= default_names
    assert "subagents" not in default_names
    assert "create_pptx" not in default_names

    surfaced_ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        surfaced_tools={"create_pptx", "subagents"},
    )
    surfaced_names = {tool.name for tool in registry.to_tool_definitions(surfaced_ctx)}
    assert "subagents" in surfaced_names
    assert "create_pptx" in surfaced_names


def test_node_runtime_stubs_stay_hidden_until_explicitly_surfaced() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registry = get_default_registry()
    owner_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)

    default_tools = registry.to_tool_definitions(owner_ctx)
    assert {tool.name for tool in default_tools}.isdisjoint({"nodes", "canvas"})

    surfaced_ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        surfaced_tools={"nodes", "canvas"},
    )
    surfaced_tools = {
        tool.name: tool.description.lower()
        for tool in registry.to_tool_definitions(surfaced_ctx)
        if tool.name in {"nodes", "canvas"}
    }

    assert set(surfaced_tools) == {"nodes", "canvas"}
    assert "node runtime" in surfaced_tools["nodes"]
    assert "unavailable" in surfaced_tools["nodes"]
    assert "node runtime" in surfaced_tools["canvas"]
    assert "unavailable" in surfaced_tools["canvas"]


def test_web_owner_schema_hides_basic_pptx_fallback_by_default() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registry = get_default_registry()
    web_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.WEB)

    names = {tool.name for tool in registry.to_tool_definitions(web_ctx)}

    assert "create_pptx" not in names
    assert "execute_code" in names


def test_channel_runtime_profile_exposes_publish_artifact() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import filter_by_profile, get_default_registry, resolve_profile

    registry = get_default_registry()
    channel_ctx = ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL)

    names = {
        tool.name
        for tool in filter_by_profile(
            registry.to_tool_definitions(channel_ctx),
            resolve_profile(channel_ctx),
        )
    }

    assert "publish_artifact" in names


def test_channel_runtime_profile_exposes_safe_structured_file_tools() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import filter_by_profile, get_default_registry, resolve_profile

    registry = get_default_registry()
    channel_ctx = ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL)

    names = {
        tool.name
        for tool in filter_by_profile(
            registry.to_tool_definitions(channel_ctx),
            resolve_profile(channel_ctx),
            channel_ctx,
        )
    }

    assert {"create_csv", "create_xlsx", "create_pdf_report", "create_pptx"} <= names
    assert "write_file" not in names
    assert "execute_code" not in names


def test_channel_media_policy_surfaces_basic_pptx_fallback_explicitly() -> None:
    from opensquilla.tools.policy import apply_tool_policy_from_config

    registry = ToolRegistry()
    registry.register(_spec("session_status"), _handler)
    registry.register(_spec("create_pptx", exposed_by_default=False), _handler)
    ctx = apply_tool_policy_from_config(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CHANNEL,
            channel_kind="feishu",
            channel_id="oc_demo",
        ),
        available_tools=registry.list_names(),
        config={
            "channels": {
                "feishu": {
                    "groups": {
                        "oc_demo": {
                            "tools": {"profile": "minimal", "also_allow": ["channel:media"]}
                        }
                    }
                }
            }
        },
    )

    names = {tool.name for tool in registry.to_tool_definitions(ctx)}

    assert names == {"session_status", "create_pptx"}


def test_channel_runtime_profile_exposes_explicit_category_tools_not_host_mutation() -> None:
    from opensquilla.tools.registry import filter_by_profile, resolve_profile

    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.CHANNEL,
        allowed_tools={"feishu_drive_upload_artifact", "write_file"},
    )
    tools = [
        _spec("feishu_drive_upload_artifact"),
        _spec("write_file"),
        _spec("create_pptx"),
    ]

    names = {tool.name for tool in filter_by_profile(tools, resolve_profile(ctx), ctx)}

    assert "feishu_drive_upload_artifact" in names
    assert "create_pptx" in names
    assert "write_file" not in names


def test_channel_hidden_tool_visibility_stays_on_channel_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_TOOL_PROFILE", "owner_full")
    registry = ToolRegistry()
    registry.register(_spec("create_pptx", exposed_by_default=False), _handler)
    registry.register(_spec("hidden_authoring", exposed_by_default=False), _handler)
    channel_ctx = ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL)

    names = {tool.name for tool in registry.to_tool_definitions(channel_ctx)}

    assert "create_pptx" in names
    assert "hidden_authoring" not in names


def test_shared_channel_context_hides_private_memory_read_tools_even_when_allowed() -> None:
    from opensquilla.tools.policy import resolve_runtime_tool_surface
    from opensquilla.tools.registry import filter_by_profile, resolve_profile

    registry = ToolRegistry()
    registry.register(_spec("memory_get"), _handler)
    registry.register(_spec("memory_search"), _handler)
    registry.register(_spec("session_search"), _handler)
    registry.register(_spec("read_file"), _handler)
    channel_ctx = resolve_runtime_tool_surface(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CHANNEL,
            session_key="agent:main:slack:group:g1",
            allowed_tools={"memory_get", "memory_search", "read_file"},
        ),
        capabilities=ToolSurfaceCapabilities(session_manager=True),
    )

    names = {
        tool.name
        for tool in filter_by_profile(
            registry.to_tool_definitions(channel_ctx),
            resolve_profile(channel_ctx),
            channel_ctx,
        )
    }

    assert "memory_get" not in names
    assert "memory_search" not in names
    assert "session_search" not in names
    assert "read_file" in names


def test_direct_channel_context_keeps_private_memory_read_tools() -> None:
    from opensquilla.tools.policy import resolve_runtime_tool_surface
    from opensquilla.tools.registry import filter_by_profile, resolve_profile

    registry = ToolRegistry()
    registry.register(_spec("memory_get"), _handler)
    registry.register(_spec("memory_search"), _handler)
    channel_ctx = resolve_runtime_tool_surface(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CHANNEL,
            session_key="agent:main:slack:dm:u1",
        ),
        capabilities=ToolSurfaceCapabilities(session_manager=True),
    )

    names = {
        tool.name
        for tool in filter_by_profile(
            registry.to_tool_definitions(channel_ctx),
            resolve_profile(channel_ctx),
            channel_ctx,
        )
    }

    assert "memory_get" in names
    assert "memory_search" in names


@pytest.mark.asyncio
async def test_effective_tools_hide_private_memory_reads_for_cron_and_subagents() -> None:
    registry = ToolRegistry()
    registry.register(_spec("memory_get"), _handler)
    registry.register(_spec("memory_search"), _handler)
    registry.register(_spec("session_search"), _handler)
    registry.register(_spec("read_file"), _handler)

    cron_names = {
        tool["name"]
        for tool in await registry.effective_tools(
            session_key="cron:dream:run:1",
            agent_id="main",
            caller_kind=CallerKind.CRON,
            interaction_mode=InteractionMode.UNATTENDED,
            tool_surface_capabilities=ToolSurfaceCapabilities(session_manager=True),
            is_owner=False,
        )
    }
    subagent_names = {
        tool["name"]
        for tool in await registry.effective_tools(
            session_key="agent:main:subagent:run-1",
            agent_id="main",
            caller_kind=CallerKind.SUBAGENT,
            interaction_mode=InteractionMode.UNATTENDED,
            tool_surface_capabilities=ToolSurfaceCapabilities(session_manager=True),
        )
    }

    assert cron_names == {"read_file"}
    assert subagent_names == {"read_file"}


@pytest.mark.asyncio
async def test_effective_tools_keep_private_memory_reads_for_owner_cron() -> None:
    registry = ToolRegistry()
    registry.register(_spec("memory_get"), _handler)
    registry.register(_spec("memory_search"), _handler)
    registry.register(_spec("session_search"), _handler)
    registry.register(_spec("read_file"), _handler)

    cron_names = {
        tool["name"]
        for tool in await registry.effective_tools(
            session_key="cron:owner:run:1",
            agent_id="main",
            caller_kind=CallerKind.CRON,
            interaction_mode=InteractionMode.UNATTENDED,
            tool_surface_capabilities=ToolSurfaceCapabilities(session_manager=True),
            is_owner=True,
        )
    }

    assert "memory_get" in cron_names
    assert "memory_search" in cron_names
    assert "session_search" in cron_names


def test_subagent_schema_hides_publish_artifact_without_artifact_context() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import get_default_registry
    from opensquilla.tools.types import SUBAGENT_TOOL_DENY

    registry = get_default_registry()
    subagent_ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.SUBAGENT,
        interaction_mode=InteractionMode.UNATTENDED,
        denied_tools=set(SUBAGENT_TOOL_DENY),
    )

    names = {tool.name for tool in registry.to_tool_definitions(subagent_ctx)}

    assert "publish_artifact" not in names


def test_owner_only_tools_are_hidden_from_non_owner_schema() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registry = get_default_registry()
    owner_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)
    non_owner_ctx = ToolContext(is_owner=False, caller_kind=CallerKind.AGENT)

    owner_names = {tool.name for tool in registry.to_tool_definitions(owner_ctx)}
    non_owner_names = {tool.name for tool in registry.to_tool_definitions(non_owner_ctx)}

    assert {"http_request", "git_commit"} <= owner_names
    assert "http_request" not in non_owner_names
    assert "git_commit" not in non_owner_names


def test_web_group_can_surface_owner_only_http_request_for_owner_only() -> None:
    import opensquilla.tools.builtin  # noqa: F401
    from opensquilla.gateway.config import GatewayConfig, ToolsConfig
    from opensquilla.tools.policy import apply_tool_policy_from_config
    from opensquilla.tools.registry import get_default_registry

    registry = get_default_registry()
    available = registry.list_names()
    config = GatewayConfig(
        tools=ToolsConfig(profile="minimal", also_allow=["group:web"])
    )

    owner_ctx = apply_tool_policy_from_config(
        ToolContext(is_owner=True, caller_kind=CallerKind.AGENT),
        available_tools=available,
        config=config,
    )
    non_owner_ctx = apply_tool_policy_from_config(
        ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL),
        available_tools=available,
        config=config,
    )

    owner_names = {tool.name for tool in registry.to_tool_definitions(owner_ctx)}
    non_owner_names = {tool.name for tool in registry.to_tool_definitions(non_owner_ctx)}

    assert {
        "web_search",
        "web_discover",
        "web_fetch",
        "http_request",
    } <= owner_names
    assert "research_search" not in owner_names
    assert "research_search" not in non_owner_names
    assert "web_search" in non_owner_names
    assert "web_discover" in non_owner_names
    assert "http_request" not in non_owner_names


@pytest.mark.asyncio
async def test_list_tools_uses_visible_helper_and_stable_sorting() -> None:
    registry = ToolRegistry()
    registry.register(_spec("zeta"), _handler)
    registry.register(_spec("alpha"), _handler)
    registry.register(_spec("hidden", exposed_by_default=False), _handler)

    tools = await registry.list_tools()

    assert [tool["name"] for tool in tools] == ["alpha", "zeta"]


@pytest.mark.asyncio
async def test_schema_visibility_and_dispatch_denial_use_same_context() -> None:
    registry = ToolRegistry()
    registry.register(_spec("allowed"), _handler)
    registry.register(_spec("denied"), _handler)
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        denied_tools={"denied"},
    )

    schema_names = {tool.name for tool in registry.to_tool_definitions(ctx)}
    handler = build_tool_handler(registry, ctx)
    forced_result = await handler(
        ToolCall(
            tool_use_id="tc-denied",
            tool_name="denied",
            arguments={},
        )
    )

    assert schema_names == {"allowed"}
    assert forced_result.is_error is True
    payload = json.loads(forced_result.content)
    assert payload["error_class"] == "PolicyDenied"


@pytest.mark.asyncio
async def test_channel_profile_blocks_forced_tool_calls_outside_safe_allowlist() -> None:
    registry = ToolRegistry()
    registry.register(_spec("create_csv"), _handler)
    registry.register(_spec("execute_code"), _handler)
    ctx = ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL)
    handler = build_tool_handler(registry, ctx)

    allowed = await handler(
        ToolCall(
            tool_use_id="tc-safe",
            tool_name="create_csv",
            arguments={},
        )
    )
    forced = await handler(
        ToolCall(
            tool_use_id="tc-forced",
            tool_name="execute_code",
            arguments={},
        )
    )

    assert allowed.is_error is False
    assert forced.is_error is True
    payload = json.loads(forced.content)
    assert payload["error_class"] == "PolicyDenied"


@pytest.mark.asyncio
async def test_channel_profile_allows_explicit_category_tools_not_host_mutation() -> None:
    registry = ToolRegistry()
    registry.register(_spec("create_pptx"), _handler)
    registry.register(_spec("feishu_drive_upload_artifact"), _handler)
    registry.register(_spec("write_file"), _handler)
    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.CHANNEL,
        allowed_tools={"create_pptx", "feishu_drive_upload_artifact", "write_file"},
    )
    handler = build_tool_handler(registry, ctx)

    category_tool = await handler(
        ToolCall(
            tool_use_id="tc-drive",
            tool_name="feishu_drive_upload_artifact",
            arguments={},
        )
    )
    host_mutation = await handler(
        ToolCall(
            tool_use_id="tc-write",
            tool_name="write_file",
            arguments={},
        )
    )

    assert category_tool.is_error is False
    assert host_mutation.is_error is True
    payload = json.loads(host_mutation.content)
    assert payload["error_class"] == "PolicyDenied"


@pytest.mark.asyncio
async def test_dispatch_denies_private_memory_reads_for_shared_sessions() -> None:
    registry = ToolRegistry()
    registry.register(_spec("memory_search"), _handler)
    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.CHANNEL,
        session_key="agent:main:slack:group:g1",
    )

    handler = build_tool_handler(registry, ctx)
    forced_result = await handler(
        ToolCall(
            tool_use_id="tc-memory-search",
            tool_name="memory_search",
            arguments={},
        )
    )

    assert forced_result.is_error is True
    payload = json.loads(forced_result.content)
    assert payload["error_class"] == "PolicyDenied"


@pytest.mark.asyncio
async def test_catalog_and_effective_names_agree_for_unattended_cli_context() -> None:
    registry = ToolRegistry()
    registry.register(_spec("sessions_spawn"), _handler)
    registry.register(_spec("sessions_list"), _handler)
    registry.register(_spec("read_file"), _handler)

    catalog = await registry.list_tools(
        session_key="agent:main:auto",
        agent_id="main",
        caller_kind=CallerKind.CLI,
        interaction_mode=InteractionMode.UNATTENDED,
        tool_surface_capabilities=ToolSurfaceCapabilities(session_manager=True),
    )
    effective = await registry.effective_tools(
        session_key="agent:main:auto",
        agent_id="main",
        caller_kind=CallerKind.CLI,
        interaction_mode=InteractionMode.UNATTENDED,
        tool_surface_capabilities=ToolSurfaceCapabilities(session_manager=True),
    )

    catalog_names = {tool["name"] for tool in catalog}
    effective_names = {tool["name"] for tool in effective}
    assert catalog_names == effective_names == {"read_file", "sessions_list"}


@pytest.mark.parametrize(
    ("state", "search_visible", "profile_parameter"),
    [
        (KnowledgeConnectionState.READY, True, True),
        (KnowledgeConnectionState.DEGRADED, True, False),
        (KnowledgeConnectionState.LEGACY, True, False),
        (KnowledgeConnectionState.DISCOVERING, False, False),
        (KnowledgeConnectionState.UNAVAILABLE, False, False),
        (None, False, False),
    ],
)
def test_knowledge_definitions_follow_capability_snapshot(
    state: KnowledgeConnectionState | None,
    search_visible: bool,
    profile_parameter: bool,
) -> None:
    registry = ToolRegistry()
    create_knowledge_tools(manager=object(), registry=registry)  # type: ignore[arg-type]
    snapshot = _knowledge_snapshot(state) if state is not None else None

    definitions = {
        definition.name: definition
        for definition in registry.to_tool_definitions(
            ToolContext(knowledge_capability_snapshot=snapshot)
        )
    }

    assert "knowledge_status" in definitions
    assert ("knowledge_search" in definitions) is search_visible
    if not search_visible:
        return

    properties = definitions["knowledge_search"].input_schema.properties
    assert ("retrieval_profile" in properties) is profile_parameter
    assert properties.keys().isdisjoint(
        {
            "embedding_model",
            "embedding_dimensions",
        }
    )
    if state is KnowledgeConnectionState.READY:
        assert properties["retrieval_profile"]["enum"] == ["lexical", "hybrid"]


def test_knowledge_definition_enrichment_does_not_mutate_registered_spec() -> None:
    registry = ToolRegistry()
    create_knowledge_tools(manager=object(), registry=registry)  # type: ignore[arg-type]
    registered = registry.get("knowledge_search")
    assert registered is not None
    original_parameters = copy.deepcopy(registered.spec.parameters)

    ready = registry.to_tool_definitions(
        ToolContext(
            knowledge_capability_snapshot=_knowledge_snapshot(
                KnowledgeConnectionState.READY
            )
        )
    )
    registry.to_tool_definitions(
        ToolContext(
            knowledge_capability_snapshot=_knowledge_snapshot(
                KnowledgeConnectionState.DEGRADED
            )
        )
    )

    assert registered.spec.parameters == original_parameters
    ready_search = next(item for item in ready if item.name == "knowledge_search")
    ready_search.input_schema.properties["retrieval_profile"]["enum"].append(
        "caller-mutation"
    )
    assert registered.spec.parameters == original_parameters


def test_non_knowledge_definitions_are_identical_for_every_knowledge_snapshot() -> None:
    registry = ToolRegistry()
    create_knowledge_tools(manager=object(), registry=registry)  # type: ignore[arg-type]
    registry.register(
        ToolSpec(
            name="plain",
            description="Plain non-Knowledge tool.",
            parameters={
                "nested": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                }
            },
        ),
        _handler,
    )
    knowledge_names = {"knowledge_status", "knowledge_search", "knowledge_get"}

    def serialized(snapshot: KnowledgeCapabilitySnapshot | None) -> list[dict[str, object]]:
        return [
            definition.model_dump(mode="json", by_alias=True)
            for definition in registry.to_tool_definitions(
                ToolContext(knowledge_capability_snapshot=snapshot)
            )
            if definition.name not in knowledge_names
        ]

    baseline = serialized(None)
    for state in (
        KnowledgeConnectionState.READY,
        KnowledgeConnectionState.DEGRADED,
        KnowledgeConnectionState.LEGACY,
        KnowledgeConnectionState.DISCOVERING,
        KnowledgeConnectionState.UNAVAILABLE,
    ):
        assert serialized(_knowledge_snapshot(state)) == baseline
