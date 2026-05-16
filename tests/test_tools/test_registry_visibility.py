from __future__ import annotations

import json

import pytest
import structlog.testing

from opensquilla.engine.types import ToolCall
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.policy import ToolSurfaceCapabilities
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, InteractionMode, ToolContext, ToolSpec


async def _handler() -> str:
    return "ok"


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

    surfaced_ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        surfaced_tools={"subagents"},
    )
    surfaced_names = {tool.name for tool in registry.to_tool_definitions(surfaced_ctx)}
    assert "subagents" in surfaced_names


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

    assert {"web_search", "web_fetch", "http_request"} <= owner_names
    assert "http_request" not in non_owner_names


def test_tool_surface_capabilities_can_be_built_from_runtime_dependencies() -> None:
    from opensquilla.tools.policy import tool_surface_capabilities_from_runtime

    caps = tool_surface_capabilities_from_runtime(
        session_manager=object(),
        task_runtime=None,
        scheduler=object(),
        gateway_config=object(),
        channel_manager=None,
        originating_envelope=object(),
        image_generation=False,
    )

    assert caps.session_manager is True
    assert caps.task_runtime is False
    assert caps.scheduler is True
    assert caps.gateway_config is True
    assert caps.channel_backing is True
    assert caps.image_generation is False


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
