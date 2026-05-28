"""Shared turn streaming adapter for chat surfaces.

This module owns the bridge from gateway/runtime turn events to renderer
updates. It is deliberately independent of concrete terminal input apps:
callers pass typed output handles, renderers, and session/tool dependencies.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from opensquilla.cli.chat.output import ChatOutputHandle
from opensquilla.cli.chat.turn import TurnResult, UsageSummary
from opensquilla.execution_status import derive_is_error
from opensquilla.session.terminal_reply import build_terminal_reply

_DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15.0
_DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 600.0

ApprovalSurfaceResolver = Callable[
    [ChatOutputHandle | None, object | None],
    object | None,
]


class GatewayStreamingClient(Protocol):
    def send_message(
        self,
        session_key: str,
        message: str,
        attachments: list[dict] | None = None,
        elevated: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        *,
        allow_always: bool = False,
    ) -> Any: ...

    async def abort_session(self, key: str) -> Any: ...


@dataclass(frozen=True)
class TurnStreamDependencies:
    renderer_factory: Callable[..., Any]
    stream_wrapper: Callable[[Any, Any], Any]
    approval_handler: Callable[..., Awaitable[None]]
    cancel_clearer: Callable[[], None]
    image_attachment_builder: Callable[[str], tuple[str, list[dict[str, str]]]]
    output_console: Any
    error_panel_factory: Callable[[str], Any]
    gateway_approval_surface: object | None = None
    standalone_approval_surface: object | None = None
    approval_surface_resolver: ApprovalSurfaceResolver | None = None


class _BackendFallbackRenderer:
    def __init__(self, **_kwargs: Any) -> None:
        self.buffer = ""

    def __enter__(self) -> _BackendFallbackRenderer:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> Literal[False]:
        return False

    async def aappend_text(self, delta: str) -> None:
        self.buffer += delta

    def pulse(self) -> None:
        return None

    def tool_start(
        self,
        _name: str,
        _args: dict | None,
        _tool_use_id: str | None,
    ) -> None:
        return None

    def tool_finished(self, _tool_use_id: str | None, **_kwargs: Any) -> None:
        return None

    def status(self, _message: str, **_kwargs: Any) -> None:
        return None

    def error(self, _message: str) -> None:
        return None

    def finalize(
        self,
        _usage: UsageSummary | None = None,
        **_kwargs: Any,
    ) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _NoopConsole:
    def print(self, *_objects: Any, **_kwargs: Any) -> None:
        return None


async def _noop_approval_handler(*_args: Any, **_kwargs: Any) -> None:
    return None


def _noop_cancel_clearer() -> None:
    return None


def _plain_error_panel(message: str) -> str:
    return message


def image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
    raise ValueError("Image attachments are not configured.")


def default_turn_stream_dependencies(
    *,
    renderer_factory: Callable[..., Any] | None = None,
    stream_wrapper: Callable[[Any, Any], Any] | None = None,
    approval_handler: Callable[..., Awaitable[None]] | None = None,
    cancel_clearer: Callable[[], None] | None = None,
    image_attachment_builder: Callable[[str], tuple[str, list[dict[str, str]]]] | None = None,
    output_console: Any | None = None,
    error_panel_factory: Callable[[str], Any] | None = None,
    gateway_approval_surface: object | None = None,
    standalone_approval_surface: object | None = None,
    approval_surface_resolver: ApprovalSurfaceResolver | None = None,
) -> TurnStreamDependencies:
    return TurnStreamDependencies(
        renderer_factory=(
            _BackendFallbackRenderer if renderer_factory is None else renderer_factory
        ),
        stream_wrapper=wrap_cli_turn_stream if stream_wrapper is None else stream_wrapper,
        approval_handler=(
            _noop_approval_handler if approval_handler is None else approval_handler
        ),
        cancel_clearer=_noop_cancel_clearer if cancel_clearer is None else cancel_clearer,
        image_attachment_builder=(
            image_prompt_and_attachments
            if image_attachment_builder is None
            else image_attachment_builder
        ),
        output_console=_NoopConsole() if output_console is None else output_console,
        error_panel_factory=(
            _plain_error_panel if error_panel_factory is None else error_panel_factory
        ),
        gateway_approval_surface=gateway_approval_surface,
        standalone_approval_surface=standalone_approval_surface,
        approval_surface_resolver=approval_surface_resolver,
    )


def _resolve_deps(deps: TurnStreamDependencies | None) -> TurnStreamDependencies:
    if deps is not None:
        return deps
    return default_turn_stream_dependencies()


def _async_renderer_method(method: object) -> Callable[..., Awaitable[None]]:
    return cast(Callable[..., Awaitable[None]], method)


def _tool_result_success_from_status(status: Any, *, legacy_is_error: bool) -> bool:
    if isinstance(status, dict):
        return status.get("status") == "success" and not derive_is_error(status)
    return not legacy_is_error


def turn_stream_error_message(event: Any) -> str:
    message = getattr(event, "message", "")
    code = str(getattr(event, "code", "") or "").lower()
    message_text = str(message)
    if "timeout" in code or "stream idle" in message_text.lower():
        return build_terminal_reply(
            {
                "status": "timeout",
                "terminal_reason": "timeout",
                "error_class": getattr(event, "code", None),
                "error_message": message_text,
            }
        )
    return message_text


def timeout_exception_message(exc: BaseException) -> str:
    return build_terminal_reply(
        {
            "status": "timeout",
            "terminal_reason": "timeout",
            "error_class": exc.__class__.__name__,
            "error_message": str(exc),
        }
    )


def optional_positive_config_float(config_source: Any, attr: str, default: float) -> float | None:
    config = getattr(config_source, "config", config_source)
    raw = getattr(config, attr, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return value if value > 0 else None


def wrap_cli_turn_stream(stream: Any, config_source: Any) -> Any:
    from opensquilla.engine.stream_wrappers import wrap_stream

    return wrap_stream(
        stream,
        idle_timeout=optional_positive_config_float(
            config_source,
            "agent_stream_idle_timeout_seconds",
            _DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS,
        ),
        heartbeat_interval=optional_positive_config_float(
            config_source,
            "agent_stream_heartbeat_interval_seconds",
            _DEFAULT_STREAM_HEARTBEAT_INTERVAL_SECONDS,
        ),
        heartbeat_phase="cli",
        heartbeat_message="Still working",
    )


def is_approval_or_blocked_result(result: Any) -> bool:
    """Return True when a tool_result payload is an approval/block envelope."""
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return False
        if not isinstance(parsed, dict):
            return False
        payload = parsed
    elif isinstance(result, dict):
        payload = result
    else:
        return False
    return payload.get("status") in {"approval_required", "approval_pending", "blocked"}


def approval_surface_for_tui_output(
    tui_output: ChatOutputHandle | None,
    default: object | None,
) -> object | None:
    if tui_output is None:
        return default
    approval_surface: object | None = getattr(tui_output, "approval_surface", None)
    if approval_surface is not None:
        return approval_surface
    return default


def _resolve_approval_surface(
    tui_output: ChatOutputHandle | None,
    default: object | None,
    deps: TurnStreamDependencies,
) -> object | None:
    resolver = deps.approval_surface_resolver or approval_surface_for_tui_output
    return resolver(tui_output, default)


def render_gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
    renderer: Any,
    *,
    deps: TurnStreamDependencies | None = None,
) -> None:
    stream_deps = _resolve_deps(deps)
    status_item = gateway_task_group_status(event_name, event)
    if status_item is None:
        return
    message, style = status_item
    status = getattr(renderer, "status", None)
    if callable(status):
        status(message, style=style)
    else:
        stream_deps.output_console.print(f"[{style}]{message}[/]")


def gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
) -> tuple[str, str] | None:
    phase = event_name.rsplit(".", 1)[-1]
    style = "dim"
    if phase == "waiting":
        pending = event.get("pending_count")
        suffix = f" ({pending} pending)" if isinstance(pending, int) and pending >= 0 else ""
        message = f"subagents waiting{suffix}"
    elif phase == "synthesizing":
        child_count = event.get("child_count")
        suffix = f" from {child_count} children" if isinstance(child_count, int) else ""
        message = f"subagents complete; synthesizing final answer{suffix}"
    elif phase == "done":
        delivery_status = event.get("delivery_status")
        suffix = f" (delivery: {delivery_status})" if isinstance(delivery_status, str) else ""
        message = f"background synthesis complete{suffix}"
    elif phase == "failed":
        error_message = event.get("error_message")
        suffix = f": {error_message}" if isinstance(error_message, str) and error_message else ""
        message = f"background synthesis failed{suffix}"
        style = "yellow"
    else:
        return None
    return message, style


async def arender_gateway_task_group_status(
    event_name: str,
    event: dict[str, Any],
    renderer: Any,
    *,
    deps: TurnStreamDependencies | None = None,
) -> None:
    status_item = gateway_task_group_status(event_name, event)
    if status_item is None:
        return
    message, style = status_item
    await renderer_status(renderer, message, style=style, deps=deps)


async def renderer_status(
    renderer: Any,
    message: str,
    *,
    style: str = "dim",
    deps: TurnStreamDependencies | None = None,
) -> None:
    stream_deps = _resolve_deps(deps)
    astatus = getattr(renderer, "astatus", None)
    if callable(astatus):
        await _async_renderer_method(astatus)(message, style=style)
        return
    status = getattr(renderer, "status", None)
    if callable(status):
        status(message, style=style)
    else:
        stream_deps.output_console.print(f"[{style}]{message}[/]")


async def renderer_tool_start(
    renderer: Any,
    name: str,
    args: dict | None,
    tool_use_id: str | None,
) -> None:
    atool_start = getattr(renderer, "atool_start", None)
    if callable(atool_start):
        await _async_renderer_method(atool_start)(name, args, tool_use_id)
        return
    renderer.tool_start(name, args, tool_use_id)


async def renderer_tool_finished(
    renderer: Any,
    tool_use_id: str | None,
    *,
    success: bool,
) -> None:
    atool_finished = getattr(renderer, "atool_finished", None)
    if callable(atool_finished):
        await _async_renderer_method(atool_finished)(tool_use_id, success=success)
        return
    renderer.tool_finished(tool_use_id, success=success)


async def renderer_error(renderer: Any, message: str) -> None:
    aerror = getattr(renderer, "aerror", None)
    if callable(aerror):
        await _async_renderer_method(aerror)(message)
        return
    renderer.error(message)


async def renderer_finalize(
    renderer: Any,
    usage: UsageSummary | None = None,
    *,
    cancelled: bool = False,
) -> None:
    afinalize = getattr(renderer, "afinalize", None)
    if callable(afinalize):
        await _async_renderer_method(afinalize)(usage, cancelled=cancelled)
        return
    renderer.finalize(usage, cancelled=cancelled)


async def renderer_close(renderer: Any) -> None:
    aclose = getattr(renderer, "aclose", None)
    if callable(aclose):
        await _async_renderer_method(aclose)()


def artifact_event_payload(event: Any) -> dict[str, Any]:
    from opensquilla.artifacts import artifact_payload

    if isinstance(event, dict):
        return artifact_payload(
            {key: value for key, value in event.items() if key not in {"event", "payload"}}
        )

    return artifact_payload(event)


def artifact_status_line(artifact: dict[str, Any]) -> str:
    name = artifact.get("name") if isinstance(artifact.get("name"), str) else "artifact"
    target = artifact.get("download_url") if isinstance(artifact.get("download_url"), str) else ""
    return f"Generated file: {name} -> {target or artifact.get('id', '')}"


async def dispatch_gateway_stream(
    client: GatewayStreamingClient,
    session_key: str,
    message: str,
    elevated_state: dict[str, str | None] | None = None,
    attachments: list[dict] | None = None,
    *,
    tui_output: ChatOutputHandle | None = None,
    deps: TurnStreamDependencies | None = None,
) -> TurnResult:
    kwargs: dict[str, Any] = {"tui_output": tui_output}
    if deps is not None:
        kwargs["deps"] = deps
    return await stream_response_gateway(
        client, session_key, message, elevated_state, attachments=attachments, **kwargs
    )


async def stream_response_gateway(
    client: GatewayStreamingClient,
    session_key: str,
    message: str,
    elevated_state: dict[str, str | None] | None = None,
    attachments: list[dict] | None = None,
    *,
    tui_output: ChatOutputHandle | None = None,
    deps: TurnStreamDependencies | None = None,
) -> TurnResult:
    """Stream a response from the gateway into a renderer."""
    stream_deps = _resolve_deps(deps)
    elevated = elevated_state["mode"] if elevated_state else None
    usage: UsageSummary | None = None
    cancelled = False
    artifacts: list[dict[str, Any]] = []
    model_after: str | None = None

    approval_surface = _resolve_approval_surface(
        tui_output,
        stream_deps.gateway_approval_surface,
        stream_deps,
    )

    with stream_deps.renderer_factory(output_handle=tui_output) as renderer:
        try:
            try:
                async for event in client.send_message(
                    session_key, message, attachments=attachments, elevated=elevated
                ):
                    event_name = event.get("event", "")
                    if event_name == "session.event.text_delta":
                        await renderer.aappend_text(event.get("text", ""))
                    elif event_name == "session.event.tool_use_start":
                        await renderer_tool_start(
                            renderer,
                            event.get("tool_name") or event.get("toolName") or "tool",
                            event.get("input") or event.get("arguments"),
                            event.get("tool_use_id") or event.get("toolUseId"),
                        )
                    elif event_name == "session.event.tool_result":
                        await stream_deps.approval_handler(
                            event.get("result"),
                            renderer,
                            client.resolve_approval,
                            elevated_state=elevated_state,
                            surface=approval_surface,
                        )
                        if not is_approval_or_blocked_result(event.get("result")):
                            await renderer_tool_finished(
                                renderer,
                                event.get("tool_use_id") or event.get("toolUseId"),
                                success=_tool_result_success_from_status(
                                    event.get("execution_status") or event.get("executionStatus"),
                                    legacy_is_error=bool(
                                        event.get("is_error") or event.get("isError")
                                    ),
                                ),
                            )
                    elif event_name == "session.event.artifact":
                        artifact = artifact_event_payload(event)
                        artifacts.append(artifact)
                        await renderer_status(
                            renderer,
                            artifact_status_line(artifact),
                            deps=stream_deps,
                        )
                    elif event_name.startswith("session.event.task_group."):
                        await arender_gateway_task_group_status(
                            event_name,
                            event,
                            renderer,
                            deps=stream_deps,
                        )
                    elif event_name == "session.event.error":
                        message_text = event.get("message", "unknown")
                        await renderer_error(renderer, message_text)
                        return TurnResult(
                            text=renderer.buffer,
                            usage=usage,
                            error=message_text,
                            artifacts=artifacts,
                        )
                    elif event_name == "session.event.done":
                        usage = UsageSummary.from_gateway_payload(event)
                        cancelled = event.get("reason") == "aborted"
                        model_after = event.get("routed_model") or event.get("model") or None
            except (KeyboardInterrupt, asyncio.CancelledError):
                stream_deps.cancel_clearer()
                await client.abort_session(session_key)
                cancelled = True
            await renderer_finalize(renderer, usage, cancelled=cancelled)
        finally:
            await renderer_close(renderer)
    return TurnResult(
        text=renderer.buffer,
        usage=usage,
        cancelled=cancelled,
        artifacts=artifacts,
        model_after=model_after,
    )


def local_approval_resolver() -> Callable[..., Awaitable[None]]:
    """Return a resolver that talks directly to the in-process approval queue."""

    async def _resolve(approval_id: str, approved: bool, *, allow_always: bool = False) -> None:
        from opensquilla.gateway.approval_queue import get_approval_queue

        get_approval_queue().resolve(approval_id, approved, allow_always=allow_always)

    return _resolve


async def stream_response_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_ctx: object,
    message: str,
    model: str | None = None,
    svc: object = None,
    timeout: float | None = None,
    *,
    tui_output: ChatOutputHandle | None = None,
    deps: TurnStreamDependencies | None = None,
) -> TurnResult:
    """Stream a TurnRunner response into a renderer."""
    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.engine.types import (
        ArtifactEvent,
        DoneEvent,
        ErrorEvent,
        RunHeartbeatEvent,
        TextDeltaEvent,
        ToolResultEvent,
        ToolUseStartEvent,
        WarningEvent,
    )
    from opensquilla.tools.types import ToolContext

    assert isinstance(turn_runner, TurnRunner)
    assert isinstance(tool_ctx, ToolContext)

    stream_deps = _resolve_deps(deps)
    session_manager = getattr(svc, "session_manager", None) if svc is not None else None
    if session_manager is not None:
        _persisted = await session_manager.append_message(session_key, role="user", content=message)
        if _persisted is not None and isinstance(_persisted.content, str):
            message = _persisted.content

    resolver = local_approval_resolver()
    usage: UsageSummary | None = None
    cancelled = False
    artifacts: list[dict[str, Any]] = []
    model_after: str | None = None

    approval_surface = _resolve_approval_surface(
        tui_output,
        stream_deps.standalone_approval_surface,
        stream_deps,
    )

    with stream_deps.renderer_factory(output_handle=tui_output) as renderer:
        try:
            try:
                stream = turn_runner.run(
                    message, session_key, tool_context=tool_ctx, model=model, timeout=timeout
                )
                async for event in stream_deps.stream_wrapper(stream, svc):
                    if isinstance(event, TextDeltaEvent):
                        await renderer.aappend_text(event.text)
                    elif isinstance(event, RunHeartbeatEvent):
                        renderer.pulse()
                    elif isinstance(event, ToolUseStartEvent):
                        await renderer_tool_start(
                            renderer,
                            event.tool_name,
                            None,
                            event.tool_use_id,
                        )
                    elif isinstance(event, ToolResultEvent):
                        await stream_deps.approval_handler(
                            event.result,
                            renderer,
                            resolver,
                            surface=approval_surface,
                        )
                        if not is_approval_or_blocked_result(event.result):
                            await renderer_tool_finished(
                                renderer,
                                event.tool_use_id,
                                success=_tool_result_success_from_status(
                                    event.execution_status,
                                    legacy_is_error=event.is_error,
                                ),
                            )
                    elif isinstance(event, ArtifactEvent):
                        artifact = artifact_event_payload(event)
                        artifacts.append(artifact)
                        await renderer_status(
                            renderer,
                            artifact_status_line(artifact),
                            deps=stream_deps,
                        )
                    elif isinstance(event, WarningEvent):
                        await renderer_status(
                            renderer,
                            event.message,
                            style="yellow",
                            deps=stream_deps,
                        )
                    elif isinstance(event, ErrorEvent):
                        message_text = turn_stream_error_message(event)
                        await renderer_error(renderer, message_text)
                        return TurnResult(
                            text=renderer.buffer,
                            usage=usage,
                            error=message_text,
                            artifacts=artifacts,
                        )
                    elif isinstance(event, DoneEvent):
                        usage = UsageSummary.from_done_event(event)
                        model_after = usage.model or None
            except (KeyboardInterrupt, asyncio.CancelledError):
                stream_deps.cancel_clearer()
                cancelled = True
            except TimeoutError as exc:
                message_text = timeout_exception_message(exc)
                await renderer_error(renderer, message_text)
                return TurnResult(text=renderer.buffer, error=message_text)
            await renderer_finalize(renderer, usage, cancelled=cancelled)
        finally:
            await renderer_close(renderer)
    return TurnResult(
        text=renderer.buffer,
        usage=usage,
        cancelled=cancelled,
        artifacts=artifacts,
        model_after=model_after,
    )


async def handle_image_command_turnrunner(
    turn_runner: object,
    session_key: str,
    tool_ctx: object,
    command: str,
    model: str | None = None,
    svc: object = None,
    timeout: float | None = None,
    *,
    tui_output: ChatOutputHandle | None = None,
    deps: TurnStreamDependencies | None = None,
) -> TurnResult:
    """Handle /image <path> [prompt] via TurnRunner attachments."""
    from opensquilla.engine.runtime import TurnRunner
    from opensquilla.engine.types import (
        DoneEvent,
        ErrorEvent,
        RunHeartbeatEvent,
        TextDeltaEvent,
        ToolUseStartEvent,
    )
    from opensquilla.tools.types import ToolContext

    assert isinstance(turn_runner, TurnRunner)
    assert isinstance(tool_ctx, ToolContext)

    stream_deps = _resolve_deps(deps)
    try:
        prompt, attachments = stream_deps.image_attachment_builder(command)
    except ValueError as exc:
        stream_deps.output_console.print(stream_deps.error_panel_factory(str(exc)))
        return TurnResult(error=str(exc))

    session_manager = getattr(svc, "session_manager", None) if svc is not None else None
    if session_manager is not None:
        _persisted = await session_manager.append_message(session_key, role="user", content=prompt)
        if _persisted is not None and isinstance(_persisted.content, str):
            prompt = _persisted.content

    usage: UsageSummary | None = None
    with stream_deps.renderer_factory(output_handle=tui_output) as renderer:
        try:
            try:
                stream = turn_runner.run(
                    prompt,
                    session_key,
                    tool_context=tool_ctx,
                    model=model,
                    attachments=attachments,
                    timeout=timeout,
                )
                async for event in stream_deps.stream_wrapper(stream, svc):
                    if isinstance(event, TextDeltaEvent):
                        await renderer.aappend_text(event.text)
                    elif isinstance(event, RunHeartbeatEvent):
                        renderer.pulse()
                    elif isinstance(event, ToolUseStartEvent):
                        await renderer_tool_start(
                            renderer,
                            event.tool_name,
                            None,
                            event.tool_use_id,
                        )
                    elif isinstance(event, ErrorEvent):
                        message_text = turn_stream_error_message(event)
                        await renderer_error(renderer, message_text)
                        return TurnResult(text=renderer.buffer, usage=usage, error=message_text)
                    elif isinstance(event, DoneEvent):
                        usage = UsageSummary.from_done_event(event)
            except TimeoutError as exc:
                message_text = timeout_exception_message(exc)
                await renderer_error(renderer, message_text)
                return TurnResult(text=renderer.buffer, error=message_text)
            await renderer_finalize(renderer, usage)
        finally:
            await renderer_close(renderer)
    return TurnResult(text=renderer.buffer, usage=usage)
