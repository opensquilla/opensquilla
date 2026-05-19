"""Tool profile, context, and visibility policy helpers."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import structlog

from opensquilla.provider.types import ToolDefinition
from opensquilla.tools import surface as surface_policy
from opensquilla.tools.types import (
    CallerKind,
    RegisteredTool,
    ToolContext,
)

log = structlog.get_logger(__name__)


class ToolProfile(StrEnum):
    OWNER_FULL = "owner_full"
    CHANNEL_DEFAULT = "channel_default"


@dataclass(frozen=True)
class ToolDispatchBlock:
    reason: str
    exception: Exception
    error_class: str
    user_message: str


default_tool_context = surface_policy.default_tool_context
tool_context_for_profile = surface_policy.tool_context_for_profile
parse_interaction_mode = surface_policy.parse_interaction_mode
effective_tool_context = surface_policy.effective_tool_context


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


def tool_dispatch_block(
    rt: RegisteredTool,
    ctx: ToolContext | None = None,
) -> ToolDispatchBlock | None:
    """Return a dispatch denial when request context forbids this tool."""
    if ctx is None:
        return None
    if rt.spec.owner_only and not ctx.is_owner:
        return ToolDispatchBlock(
            reason="owner_only",
            exception=PermissionError("owner-only tool"),
            error_class="OwnerOnly",
            user_message=f"Tool '{rt.spec.name}' restricted to owner.",
        )
    if rt.spec.name in ctx.denied_tools:
        return ToolDispatchBlock(
            reason="denied",
            exception=PermissionError("tool blocked"),
            error_class="PolicyDenied",
            user_message=f"Tool '{rt.spec.name}' not available in this context.",
        )
    if ctx.allowed_tools is not None and rt.spec.name not in ctx.allowed_tools:
        return ToolDispatchBlock(
            reason="not_allowed",
            exception=PermissionError("tool blocked"),
            error_class="PolicyDenied",
            user_message=f"Tool '{rt.spec.name}' not available in this context.",
        )
    return None


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
