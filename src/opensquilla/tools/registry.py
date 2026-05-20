"""ToolRegistry + @tool decorator."""

from __future__ import annotations

import functools
import os
from collections.abc import Mapping
from dataclasses import replace
from enum import StrEnum
from typing import Any

import structlog

from opensquilla.provider.types import ToolDefinition, ToolInputSchema
from opensquilla.tools.policy import (
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
    ToolHandler,
    ToolSpec,
)

log = structlog.get_logger(__name__)


class ToolProfile(StrEnum):
    OWNER_FULL = "owner_full"
    CHANNEL_DEFAULT = "channel_default"


_CHANNEL_DEFAULT_ALLOW: frozenset[str] = frozenset(
    {
        "cron",  # channel-safe reminders; cron tool enforces caller-scoped quotas
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
        "create_csv",
        "create_pdf_report",
        "create_pptx",
        "create_xlsx",
        "feishu_doc_create",
        "feishu_doc_list_blocks",
        "feishu_doc_read_raw",
        "feishu_drive_meta",
        "feishu_drive_search",
        "feishu_drive_upload_artifact",
        "feishu_media_upload_artifact",
        "feishu_scopes_status",
        "feishu_wiki_get_node",
        "feishu_wiki_list_nodes",
        "feishu_wiki_list_spaces",
        "read_file",
        "session_status",
        "sessions_history",
        "sessions_list",
        "tts",
        "web_fetch",
        "web_search",
    }
)

_CHANNEL_HARD_DENY_NON_OWNER: frozenset[str] = frozenset(
    {
        "apply_patch",
        "background_process",
        "edit_file",
        "exec_command",
        "execute_code",
        "git_commit",
        "write_file",
    }
)


def filter_by_profile(
    tools: list[ToolDefinition],
    profile: ToolProfile | str,
    ctx: ToolContext | None = None,
) -> list[ToolDefinition]:
    resolved = ToolProfile(profile)
    if resolved is ToolProfile.OWNER_FULL:
        return list(tools)
    explicit = ctx.allowed_tools if ctx is not None else None
    return [
        tool
        for tool in tools
        if profile_allows_tool(tool.name, resolved, explicitly_allowed=explicit)
    ]


def profile_allows_tool(
    tool_name: str,
    profile: ToolProfile | str,
    *,
    explicitly_allowed: set[str] | frozenset[str] | None = None,
) -> bool:
    resolved = ToolProfile(profile)
    if resolved is ToolProfile.OWNER_FULL:
        return True
    if tool_name in _CHANNEL_DEFAULT_ALLOW:
        return True
    if tool_name in _CHANNEL_HARD_DENY_NON_OWNER:
        return False
    return bool(explicitly_allowed and tool_name in explicitly_allowed)


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


class ToolRegistry:
    """Central registry for all tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            log.warning("registry.tool_overwrite", name=spec.name, source="tools")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if it existed."""
        return self._tools.pop(name, None) is not None

    def all_tools(self) -> list[RegisteredTool]:
        return list(self._tools.values())

    def _iter_visible_tools(
        self,
        ctx: ToolContext | None = None,
        *,
        sort: bool = False,
    ) -> list[RegisteredTool]:
        visible = [rt for rt in self._tools.values() if self._is_visible(rt, ctx)]
        if not sort:
            return visible
        return sorted(visible, key=lambda tool: tool.spec.name)

    def _is_visible(self, rt: RegisteredTool, ctx: ToolContext | None = None) -> bool:
        explicitly_allowed = (
            ctx is not None and ctx.allowed_tools is not None and rt.spec.name in ctx.allowed_tools
        )
        surfaced = (
            ctx is not None
            and ctx.surfaced_tools is not None
            and rt.spec.name in ctx.surfaced_tools
        )
        channel_profile_visible = (
            ctx is not None
            and ctx.caller_kind is CallerKind.CHANNEL
            and not ctx.is_owner
            and profile_allows_tool(
                rt.spec.name,
                ToolProfile.CHANNEL_DEFAULT,
                explicitly_allowed=ctx.allowed_tools,
            )
        )
        if (
            not rt.spec.exposed_by_default
            and not explicitly_allowed
            and not surfaced
            and not channel_profile_visible
        ):
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

    def _default_context(self) -> ToolContext:
        return ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)

    def _context_for_profile(self, profile: str | None) -> ToolContext:
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
        return self._default_context()

    def _effective_context(
        self,
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
        explicit_interaction = _parse_interaction_mode(interaction_mode)

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
            if is_owner:
                ctx = ToolContext(
                    is_owner=True,
                    caller_kind=CallerKind.CRON,
                    interaction_mode=mode,
                    agent_id=agent_id or "main",
                )
                return resolve_runtime_tool_surface(
                    ctx,
                    capabilities=tool_surface_capabilities,
                )
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
        if explicit_kind is CallerKind.CHANNEL:
            mode = explicit_interaction or InteractionMode.INTERACTIVE
            ctx = ToolContext(
                is_owner=is_owner,
                caller_kind=CallerKind.CHANNEL,
                interaction_mode=mode,
                agent_id=agent_id or "main",
                allowed_tools=None if is_owner else set(_CHANNEL_DEFAULT_ALLOW),
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

    @staticmethod
    def _schema_for(rt: RegisteredTool) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": rt.spec.parameters,
            "required": rt.spec.required,
        }

    @staticmethod
    def _description_for(rt: RegisteredTool, ctx: ToolContext) -> str:
        description = rt.spec.description
        scratch_dir = getattr(ctx, "scratch_dir", None)
        if scratch_dir and rt.spec.name in {
            "exec_command",
            "write_file",
            "edit_file",
            "apply_patch",
            "execute_code",
        }:
            description = (
                f"{description} For temporary scripts, logs, debug output, and "
                f"candidate patches, use the configured scratch directory: {scratch_dir}."
            )
        return description

    def to_tool_definitions(self, ctx: ToolContext | None = None) -> list[ToolDefinition]:
        """Export tools as MCP-compatible ToolDefinition list.

        When *ctx* is provided, tools are filtered based on:
        - ``owner_only``: hidden when ``ctx.is_owner`` is False
        - ``denied_tools``: hidden when the tool name is in ``ctx.denied_tools``

        When *ctx* is None, all tools are returned (backward compat for tests).
        """
        active_ctx = ctx if ctx is not None else self._default_context()
        return [
            ToolDefinition(
                name=rt.spec.name,
                description=self._description_for(rt, active_ctx),
                input_schema=ToolInputSchema(
                    type="object",
                    properties=rt.spec.parameters,
                    required=rt.spec.required,
                ),
                execution_timeout_seconds=rt.spec.execution_timeout_seconds,
                execution_timeout_argument=rt.spec.execution_timeout_argument,
                execution_timeout_padding=rt.spec.execution_timeout_padding,
            )
            for rt in self._iter_visible_tools(active_ctx, sort=True)
        ]

    async def list_tools(
        self,
        profile: str | None = None,
        *,
        session_key: str | None = None,
        agent_id: str | None = None,
        caller_kind: CallerKind | str | None = None,
        interaction_mode: InteractionMode | str | None = None,
        tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
        is_owner: bool = True,
    ) -> list[dict[str, Any]]:
        has_runtime_context = any(
            value is not None
            for value in (session_key, agent_id, caller_kind, interaction_mode)
        )
        if has_runtime_context:
            ctx = self._effective_context(
                session_key=session_key,
                agent_id=agent_id,
                caller_kind=caller_kind,
                interaction_mode=interaction_mode,
                tool_surface_capabilities=tool_surface_capabilities,
                is_owner=is_owner,
            )
        else:
            ctx = self._context_for_profile(profile)
            if not is_owner:
                ctx = replace(ctx, is_owner=False)
        return [
            {
                "name": rt.spec.name,
                "description": self._description_for(rt, ctx),
                "schema": self._schema_for(rt),
                "source": "plugin" if "." in rt.spec.name else "builtin",
                "enabled": True,
            }
            for rt in self._iter_visible_tools(ctx, sort=True)
        ]

    async def effective_tools(
        self,
        session_key: str | None = None,
        agent_id: str | None = None,
        caller_kind: CallerKind | str | None = None,
        interaction_mode: InteractionMode | str | None = None,
        tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
        is_owner: bool = True,
    ) -> list[dict[str, Any]]:
        ctx = self._effective_context(
            session_key=session_key,
            agent_id=agent_id,
            caller_kind=caller_kind,
            interaction_mode=interaction_mode,
            tool_surface_capabilities=tool_surface_capabilities,
            is_owner=is_owner,
        )
        return [
            {
                "name": rt.spec.name,
                "description": self._description_for(rt, ctx),
                "schema": self._schema_for(rt),
            }
            for rt in self._iter_visible_tools(ctx, sort=True)
        ]


# Global default registry
_default_registry = ToolRegistry()


def _parse_interaction_mode(value: InteractionMode | str | None) -> InteractionMode | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, InteractionMode) else InteractionMode(str(value))
    except ValueError:
        return None


def get_default_registry() -> ToolRegistry:
    return _default_registry


def _tool_rpc_params(params: Mapping[str, Any] | None) -> Mapping[str, Any]:
    from opensquilla.tools.rpc_payload import tool_rpc_params

    return tool_rpc_params(params)


def _tool_surface_capabilities_for_runtime(
    *,
    tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
    session_manager: object | None = None,
    task_runtime: object | None = None,
    scheduler: object | None = None,
    gateway_config: object | None = None,
    channel_manager: object | None = None,
    originating_envelope: object | None = None,
) -> ToolSurfaceCapabilities:
    from opensquilla.tools.rpc_payload import tool_surface_capabilities_for_runtime

    return tool_surface_capabilities_for_runtime(
        tool_surface_capabilities=tool_surface_capabilities,
        session_manager=session_manager,
        task_runtime=task_runtime,
        scheduler=scheduler,
        gateway_config=gateway_config,
        channel_manager=channel_manager,
        originating_envelope=originating_envelope,
    )


async def tools_catalog_payload(
    params: Mapping[str, Any] | None,
    *,
    tool_registry: ToolRegistry | None = None,
    is_owner: bool = True,
    tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
    session_manager: object | None = None,
    task_runtime: object | None = None,
    scheduler: object | None = None,
    gateway_config: object | None = None,
    channel_manager: object | None = None,
    originating_envelope: object | None = None,
) -> dict[str, list[dict[str, Any]]]:
    from opensquilla.tools.rpc_payload import tools_catalog_payload as build_payload

    return await build_payload(
        params,
        tool_registry=tool_registry,
        is_owner=is_owner,
        tool_surface_capabilities=tool_surface_capabilities,
        session_manager=session_manager,
        task_runtime=task_runtime,
        scheduler=scheduler,
        gateway_config=gateway_config,
        channel_manager=channel_manager,
        originating_envelope=originating_envelope,
    )


async def tools_effective_payload(
    params: Mapping[str, Any] | None,
    *,
    tool_registry: ToolRegistry | None = None,
    is_owner: bool = True,
    tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
    session_manager: object | None = None,
    task_runtime: object | None = None,
    scheduler: object | None = None,
    gateway_config: object | None = None,
    channel_manager: object | None = None,
    originating_envelope: object | None = None,
) -> dict[str, list[dict[str, Any]]]:
    from opensquilla.tools.rpc_payload import tools_effective_payload as build_payload

    return await build_payload(
        params,
        tool_registry=tool_registry,
        is_owner=is_owner,
        tool_surface_capabilities=tool_surface_capabilities,
        session_manager=session_manager,
        task_runtime=task_runtime,
        scheduler=scheduler,
        gateway_config=gateway_config,
        channel_manager=channel_manager,
        originating_envelope=originating_envelope,
    )


def tool(
    name: str,
    description: str,
    params: dict[str, Any] | None = None,
    required: list[str] | None = None,
    owner_only: bool = False,
    exposed_by_default: bool = True,
    execution_timeout_seconds: float | None = None,
    execution_timeout_argument: str | None = None,
    execution_timeout_padding: float = 0.0,
    result_budget_class: str | None = None,
    registry: ToolRegistry | None = None,
) -> Any:
    """Decorator to register an async function as a tool.

    Usage::

        @tool(name="read_file", description="Read a file", params={...}, required=["path"])
        async def read_file(path: str) -> str: ...
    """

    def decorator(fn: ToolHandler) -> ToolHandler:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=params or {},
            required=required or [],
            owner_only=owner_only,
            exposed_by_default=exposed_by_default,
            execution_timeout_seconds=execution_timeout_seconds,
            execution_timeout_argument=execution_timeout_argument,
            execution_timeout_padding=execution_timeout_padding,
            result_budget_class=result_budget_class,
        )
        target = registry if registry is not None else _default_registry
        target.register(spec, fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
