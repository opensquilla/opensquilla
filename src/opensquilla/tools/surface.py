"""Shared tools surface request, context, and row helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from opensquilla.tools.policy_runtime import (
    ToolSurfaceCapabilities,
    resolve_runtime_tool_surface,
    tool_surface_capabilities_from_runtime,
)
from opensquilla.tools.types import (
    CRON_AGENT_ALLOW,
    CRON_AGENT_DENY,
    SUBAGENT_TOOL_DENY,
    CallerKind,
    InteractionMode,
    RegisteredTool,
    ToolContext,
)


@dataclass(frozen=True)
class ToolSurfaceRequest:
    profile: str | None = None
    session_key: str | None = None
    agent_id: str | None = None
    caller_kind: CallerKind | str | None = None
    interaction_mode: InteractionMode | str | None = None
    tool_surface_capabilities: ToolSurfaceCapabilities | None = None
    is_owner: bool = True

    def has_runtime_context(self) -> bool:
        return any(
            value is not None
            for value in (self.session_key, self.agent_id, self.caller_kind, self.interaction_mode)
        )


def default_tool_context() -> ToolContext:
    return ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)


def tool_context_for_profile(profile: str | None) -> ToolContext:
    if profile == "subagent":
        return ToolContext(
            is_owner=True,
            caller_kind=CallerKind.SUBAGENT,
            interaction_mode=InteractionMode.UNATTENDED,
            denied_tools=set(SUBAGENT_TOOL_DENY),
        )
    if profile == "cron":
        return ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CRON,
            interaction_mode=InteractionMode.UNATTENDED,
            allowed_tools=set(CRON_AGENT_ALLOW),
            denied_tools=set(CRON_AGENT_DENY),
        )
    return default_tool_context()


def parse_interaction_mode(value: InteractionMode | str | None) -> InteractionMode | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, InteractionMode) else InteractionMode(str(value))
    except ValueError:
        return None


def effective_tool_context(
    *,
    session_key: str | None = None,
    agent_id: str | None = None,
    caller_kind: CallerKind | str | None = None,
    interaction_mode: InteractionMode | str | None = None,
    tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
    is_owner: bool = True,
) -> ToolContext:
    try:
        explicit_kind = CallerKind(caller_kind) if caller_kind else None
    except ValueError:
        explicit_kind = None
    explicit_interaction = parse_interaction_mode(interaction_mode)

    if explicit_kind is CallerKind.SUBAGENT or (
        session_key and session_key.startswith("subagent:")
    ):
        mode = explicit_interaction or InteractionMode.UNATTENDED
        ctx = ToolContext(
            is_owner=is_owner,
            caller_kind=CallerKind.SUBAGENT,
            interaction_mode=mode,
            agent_id=agent_id or "main",
            denied_tools=set(SUBAGENT_TOOL_DENY),
        )
        return resolve_runtime_tool_surface(
            ctx,
            capabilities=tool_surface_capabilities,
        )
    if explicit_kind is CallerKind.CRON or (session_key and session_key.startswith("cron:")):
        mode = explicit_interaction or InteractionMode.UNATTENDED
        ctx = ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CRON,
            interaction_mode=mode,
            agent_id=agent_id or "main",
            allowed_tools=set(CRON_AGENT_ALLOW),
            denied_tools=set(CRON_AGENT_DENY),
        )
        return resolve_runtime_tool_surface(
            ctx,
            capabilities=tool_surface_capabilities,
        )
    mode = explicit_interaction or InteractionMode.INTERACTIVE
    ctx = ToolContext(
        is_owner=is_owner,
        caller_kind=CallerKind.AGENT,
        interaction_mode=mode,
        agent_id=agent_id or "main",
    )
    return resolve_runtime_tool_surface(
        ctx,
        capabilities=tool_surface_capabilities,
    )


def tool_context_for_surface_request(request: ToolSurfaceRequest) -> ToolContext:
    if request.has_runtime_context():
        return effective_tool_context(
            session_key=request.session_key,
            agent_id=request.agent_id,
            caller_kind=request.caller_kind,
            interaction_mode=request.interaction_mode,
            tool_surface_capabilities=request.tool_surface_capabilities,
            is_owner=request.is_owner,
        )
    ctx = tool_context_for_profile(request.profile)
    if not request.is_owner:
        ctx = replace(ctx, is_owner=False)
    return ctx


def tool_schema(rt: RegisteredTool) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": rt.spec.parameters,
        "required": rt.spec.required,
    }


def tool_source_kind(rt: RegisteredTool) -> str:
    return "plugin" if "." in rt.spec.name else "builtin"


def catalog_tool_row(rt: RegisteredTool) -> dict[str, Any]:
    row = {
        "name": rt.spec.name,
        "description": rt.spec.description,
        "schema": tool_schema(rt),
        "source": tool_source_kind(rt),
        "enabled": True,
    }
    return row


def effective_tool_row(rt: RegisteredTool) -> dict[str, Any]:
    return {
        "name": rt.spec.name,
        "description": rt.spec.description,
        "schema": tool_schema(rt),
    }


def tool_surface_capabilities_for_runtime(
    *,
    tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
    session_manager: object | None = None,
    task_runtime: object | None = None,
    scheduler: object | None = None,
    gateway_config: object | None = None,
    channel_manager: object | None = None,
    originating_envelope: object | None = None,
) -> ToolSurfaceCapabilities:
    if tool_surface_capabilities is not None:
        return tool_surface_capabilities
    return tool_surface_capabilities_from_runtime(
        session_manager=session_manager,
        task_runtime=task_runtime,
        scheduler=scheduler,
        gateway_config=gateway_config,
        channel_manager=channel_manager,
        originating_envelope=originating_envelope,
    )
