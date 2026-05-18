"""Tool profile, context, and visibility policy helpers."""

from __future__ import annotations

import os
from collections.abc import Iterable
from enum import StrEnum

import structlog

from opensquilla.provider.types import ToolDefinition
from opensquilla.tools.policy_runtime import (
    ToolSurfaceCapabilities,
    resolve_runtime_tool_surface,
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

log = structlog.get_logger(__name__)


class ToolProfile(StrEnum):
    OWNER_FULL = "owner_full"
    CHANNEL_DEFAULT = "channel_default"


_CHANNEL_DEFAULT_ALLOW: frozenset[str] = frozenset(
    {
        "git_diff",
        "git_log",
        "git_status",
        "glob_search",
        "grep_search",
        "image",
        "image_generate",
        "list_dir",
        "memory_get",
        "memory_search",
        "pdf",
        "publish_artifact",
        "read_file",
        "session_status",
        "sessions_history",
        "sessions_list",
        "tts",
        "web_fetch",
        "web_search",
    }
)


def filter_by_profile(
    tools: list[ToolDefinition],
    profile: ToolProfile | str,
) -> list[ToolDefinition]:
    resolved = ToolProfile(profile)
    if resolved is ToolProfile.OWNER_FULL:
        return list(tools)
    return [tool for tool in tools if tool.name in _CHANNEL_DEFAULT_ALLOW]


def resolve_profile(ctx: ToolContext | None) -> ToolProfile:
    override = os.environ.get("OPENSQUILLA_TOOL_PROFILE", "").strip()
    if override:
        try:
            return ToolProfile(override)
        except ValueError:
            log.warning("tool_profile.invalid_env_override", value=override)
    if ctx and ctx.caller_kind is CallerKind.CHANNEL and not ctx.is_owner:
        return ToolProfile.CHANNEL_DEFAULT
    return ToolProfile.OWNER_FULL


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


def is_tool_visible(rt: RegisteredTool, ctx: ToolContext | None = None) -> bool:
    explicitly_allowed = (
        ctx is not None and ctx.allowed_tools is not None and rt.spec.name in ctx.allowed_tools
    )
    surfaced = (
        ctx is not None
        and ctx.surfaced_tools is not None
        and rt.spec.name in ctx.surfaced_tools
    )
    if not rt.spec.exposed_by_default and not explicitly_allowed and not surfaced:
        return False
    if ctx is not None:
        if rt.spec.owner_only and not ctx.is_owner:
            log.debug("tool_filtered", tool=rt.spec.name, reason="owner_only")
            return False
        if ctx.allowed_tools is not None and rt.spec.name not in ctx.allowed_tools:
            log.debug("tool_filtered", tool=rt.spec.name, reason="not_allowed")
            return False
        if rt.spec.name in ctx.denied_tools:
            log.debug("tool_filtered", tool=rt.spec.name, reason="denied")
            return False
    return True


def visible_registered_tools(
    tools: Iterable[RegisteredTool],
    ctx: ToolContext | None = None,
    *,
    sort: bool = False,
) -> list[RegisteredTool]:
    visible = [rt for rt in tools if is_tool_visible(rt, ctx)]
    if not sort:
        return visible
    return sorted(visible, key=lambda tool: tool.spec.name)
