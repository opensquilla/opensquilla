"""Terminal renderer adapter backed by `StreamingRenderer`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

from opensquilla.cli.tui.terminal.stream import StreamingRenderer


class TerminalRenderer:
    """Thin async protocol adapter over the current streaming renderer."""

    def __init__(self, *, title: str = "squilla", output_handle: Any | None = None) -> None:
        self.output_handle = output_handle
        self._renderer = StreamingRenderer(title=title, output_handle=output_handle)

    async def _call_async_or_sync(
        self,
        async_name: str,
        sync_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        async_method = getattr(self._renderer, async_name, None)
        if callable(async_method):
            await cast(Callable[..., Awaitable[None]], async_method)(*args, **kwargs)
            return
        sync_method = getattr(self._renderer, sync_name, None)
        if callable(sync_method):
            cast(Callable[..., None], sync_method)(*args, **kwargs)
            return
        renderer_type = type(self._renderer).__name__
        msg = (
            f"{renderer_type} must provide {async_name}() or {sync_name}() "
            "for the terminal renderer adapter"
        )
        raise AttributeError(msg)

    @property
    def raw_renderer(self) -> Any:
        return self._renderer

    @property
    def buffer(self) -> str:
        return str(getattr(self._renderer, "buffer", ""))

    def __enter__(self) -> TerminalRenderer:
        self._renderer.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        self._renderer.__exit__(exc_type, exc, tb)
        return False

    def pulse(self) -> None:
        self._renderer.pulse()

    def stop(self) -> None:
        self._renderer.stop()

    def start(self) -> None:
        self._renderer.start()

    async def aappend_text(self, delta: str) -> None:
        await self._call_async_or_sync("aappend_text", "append_text", delta)

    def tool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        tool_start = getattr(self._renderer, "tool_start", None)
        if callable(tool_start):
            tool_start(name, args, tool_use_id)
            return
        tool_call = getattr(self._renderer, "tool_call", None)
        if callable(tool_call):
            tool_call(name, args)

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        await self._call_async_or_sync(
            "atool_start",
            "tool_start",
            name,
            args,
            tool_use_id,
        )

    def tool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> None:
        self._renderer.tool_finished(
            tool_use_id,
            success=success,
            elapsed=elapsed,
            error=error,
        )

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> None:
        await self._call_async_or_sync(
            "atool_finished",
            "tool_finished",
            tool_use_id,
            success=success,
            elapsed=elapsed,
            error=error,
        )

    def status(self, message: str, *, style: str = "dim") -> None:
        self._renderer.status(message, style=style)

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        await self._call_async_or_sync("astatus", "status", message, style=style)

    def error(self, message: str) -> None:
        self._renderer.error(message)

    async def aerror(self, message: str) -> None:
        await self._call_async_or_sync("aerror", "error", message)

    def finalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        self._renderer.finalize(usage, cancelled=cancelled)

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        await self._call_async_or_sync(
            "afinalize",
            "finalize",
            usage,
            cancelled=cancelled,
        )

    async def aclose(self) -> None:
        aclose = getattr(self._renderer, "aclose", None)
        if callable(aclose):
            await cast(Callable[[], Awaitable[None]], aclose)()
