"""ToolRegistry + @tool decorator."""

from __future__ import annotations

import copy
import functools
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import structlog

from opensquilla.provider.types import ToolDefinition, ToolInputSchema
from opensquilla.tools import visibility as visibility_policy
from opensquilla.tools.policy_runtime import ToolSurfaceCapabilities
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    RegisteredTool,
    ToolContext,
    ToolHandler,
    ToolSpec,
)

log = structlog.get_logger(__name__)

ToolProfile = visibility_policy.ToolProfile
_CHANNEL_DEFAULT_ALLOW = visibility_policy._CHANNEL_DEFAULT_ALLOW
_CHANNEL_HARD_DENY_NON_OWNER = visibility_policy._CHANNEL_HARD_DENY_NON_OWNER
filter_by_profile = visibility_policy.filter_by_profile
profile_allows_tool = visibility_policy.profile_allows_tool
resolve_profile = visibility_policy.resolve_profile


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
        return visibility_policy.visible_registered_tools(self._tools.values(), ctx, sort=sort)

    def _is_visible(self, rt: RegisteredTool, ctx: ToolContext | None = None) -> bool:
        return visibility_policy.is_tool_visible(rt, ctx)

    def _default_context(self) -> ToolContext:
        return visibility_policy.default_tool_context()

    def _context_for_profile(self, profile: str | None) -> ToolContext:
        return visibility_policy.tool_context_for_profile(profile)

    def _effective_context(
        self,
        session_key: str | None = None,
        agent_id: str | None = None,
        caller_kind: CallerKind | str | None = None,
        interaction_mode: InteractionMode | str | None = None,
        tool_surface_capabilities: ToolSurfaceCapabilities | None = None,
        is_owner: bool = True,
    ) -> ToolContext:
        return visibility_policy.effective_tool_context(
            session_key=session_key,
            agent_id=agent_id,
            caller_kind=caller_kind,
            interaction_mode=interaction_mode,
            tool_surface_capabilities=tool_surface_capabilities,
            is_owner=is_owner,
        )

    @staticmethod
    def _schema_for(rt: RegisteredTool) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": rt.spec.parameters,
            "required": rt.spec.required,
        }

    @staticmethod
    def _parameters_for(rt: RegisteredTool, ctx: ToolContext) -> dict[str, Any]:
        raw_parameters = rt.spec.parameters
        if (
            raw_parameters.get("type") == "object"
            and isinstance(raw_parameters.get("properties"), Mapping)
        ):
            raw_parameters = raw_parameters["properties"]
        parameters = copy.deepcopy(raw_parameters)
        if rt.spec.name != "router_control":
            return parameters
        router_cfg = getattr(ctx, "router_control_config", None)
        if router_cfg is None:
            return parameters
        try:
            from opensquilla.router_control import build_router_control_targets

            target_ids = [
                target.target_id
                for target in build_router_control_targets(router_cfg)
                if target.target_type == "tier"
            ]
        except Exception:  # noqa: BLE001 - schema enrichment must not hide the tool
            return parameters
        if target_ids and "target_id" in parameters:
            parameters["target_id"]["enum"] = target_ids
        return parameters

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
                    properties=self._parameters_for(rt, active_ctx),
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
                "schema": {
                    "type": "object",
                    "properties": self._parameters_for(rt, ctx),
                    "required": rt.spec.required,
                },
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
                "schema": {
                    "type": "object",
                    "properties": self._parameters_for(rt, ctx),
                    "required": rt.spec.required,
                },
            }
            for rt in self._iter_visible_tools(ctx, sort=True)
        ]


# Global default registry
_default_registry = ToolRegistry()


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
