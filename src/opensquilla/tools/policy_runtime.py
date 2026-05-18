"""Runtime tool-surface capability detection and denylist resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace

from opensquilla.tools.types import InteractionMode, ToolContext

_IMAGE_GENERATION_TOOL_NAMES: frozenset[str] = frozenset({"image_generate"})
_SESSION_READ_TOOL_NAMES: frozenset[str] = frozenset(
    {"session_status", "sessions_history", "sessions_list"}
)
_SESSION_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset(
    {"sessions_send", "sessions_spawn", "sessions_yield"}
)
_CHANNEL_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"message"})
_ADMIN_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"agents_list", "subagents"})
_GATEWAY_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"gateway"})
_SCHEDULER_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"cron"})


@dataclass(frozen=True)
class ToolSurfaceCapabilities:
    """Runtime dependencies that determine whether registered tools can work."""

    session_manager: bool = False
    task_runtime: bool = False
    scheduler: bool = False
    gateway_config: bool = False
    channel_backing: bool = False
    image_generation: bool = True


def _detect_image_generation_capability() -> bool:
    try:
        from opensquilla.provider.image_generation_runtime import image_generation_available

        return image_generation_available()
    except Exception:
        return False


def tool_surface_capabilities_from_runtime(
    *,
    session_manager: object | None = None,
    task_runtime: object | None = None,
    scheduler: object | None = None,
    gateway_config: object | None = None,
    channel_manager: object | None = None,
    originating_envelope: object | None = None,
    image_generation: bool | None = None,
) -> ToolSurfaceCapabilities:
    """Build tool-surface capabilities from injected runtime dependencies."""

    return ToolSurfaceCapabilities(
        session_manager=session_manager is not None,
        task_runtime=task_runtime is not None,
        scheduler=scheduler is not None,
        gateway_config=gateway_config is not None,
        channel_backing=channel_manager is not None or originating_envelope is not None,
        image_generation=(
            _detect_image_generation_capability()
            if image_generation is None
            else image_generation
        ),
    )


def _remove_denied_from_allowed(
    allowed_tools: set[str] | None,
    denied_tools: set[str],
) -> set[str] | None:
    if allowed_tools is not None:
        allowed_tools -= denied_tools
    return allowed_tools


def resolve_runtime_tool_surface(
    ctx: ToolContext,
    *,
    capabilities: ToolSurfaceCapabilities | None = None,
) -> ToolContext:
    """Resolve runtime-capability tool visibility into the context denylist."""

    caps = capabilities or ToolSurfaceCapabilities()
    denied_tools = set(ctx.denied_tools)
    allowed_tools = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None

    if not caps.image_generation:
        denied_tools |= set(_IMAGE_GENERATION_TOOL_NAMES)
    if not caps.session_manager:
        denied_tools |= set(_SESSION_READ_TOOL_NAMES | _SESSION_RUNTIME_TOOL_NAMES)
    if not caps.task_runtime:
        denied_tools |= set(_SESSION_RUNTIME_TOOL_NAMES)
    if not caps.scheduler:
        denied_tools |= set(_SCHEDULER_RUNTIME_TOOL_NAMES)
    if not caps.gateway_config:
        denied_tools |= set(_GATEWAY_RUNTIME_TOOL_NAMES)

    if ctx.interaction_mode is InteractionMode.UNATTENDED:
        if not caps.channel_backing:
            denied_tools |= set(_CHANNEL_RUNTIME_TOOL_NAMES)
        denied_tools |= set(_ADMIN_RUNTIME_TOOL_NAMES)

    allowed_tools = _remove_denied_from_allowed(allowed_tools, denied_tools)
    return replace(ctx, allowed_tools=allowed_tools, denied_tools=denied_tools)


def detect_runtime_tool_surface_capabilities(
    *,
    channel_backing: bool = False,
) -> ToolSurfaceCapabilities:
    """Detect tool runtime dependencies from the currently wired built-ins."""

    session_manager = False
    task_runtime = False
    scheduler = False
    gateway_config = False
    image_generation = True
    try:
        from opensquilla.tools.builtin import sessions

        session_manager = sessions.session_manager_available()
        task_runtime = sessions.task_runtime_available()
    except Exception:
        pass
    try:
        from opensquilla.tools.builtin import admin

        scheduler = admin.scheduler_available()
        gateway_config = admin.gateway_config_available()
    except Exception:
        pass
    try:
        image_generation = _detect_image_generation_capability()
    except Exception:
        image_generation = False
    return ToolSurfaceCapabilities(
        session_manager=session_manager,
        task_runtime=task_runtime,
        scheduler=scheduler,
        gateway_config=gateway_config,
        channel_backing=channel_backing,
        image_generation=image_generation,
    )
