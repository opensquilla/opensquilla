"""Structural contracts for interactive terminal UI backends."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TuiApplication(Protocol):
    """Small application surface the backend runtime needs from a TUI app."""

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None: ...

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None: ...


@runtime_checkable
class TuiSurface(Protocol):
    """Submitted-line and output surface used by the backend runtime."""

    async def next_line(self) -> str | None: ...

    def set_cancel_callback(self, cb: Callable[[], None] | None) -> None: ...

    def set_shutdown_callback(self, cb: Callable[[], None] | None) -> None: ...

    def emit_eof(self) -> None: ...

    async def write_through(self, payload: str) -> None: ...

    @property
    def redraw_callback(self) -> Callable[[], None]: ...


@runtime_checkable
class TuiOutputHandle(Protocol):
    """Typed output handle passed from TUI adapters into chat streaming code."""

    @property
    def approval_surface(self) -> object: ...

    async def write_through(self, payload: str) -> None: ...

    def stream_output(self) -> AbstractAsyncContextManager[Callable[[str], None]]: ...


@runtime_checkable
class TuiRenderer(Protocol):
    """Async renderer API a future full-screen renderer can implement."""

    async def aappend_text(self, delta: str) -> None: ...

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None: ...

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> None: ...

    async def astatus(self, message: str, *, style: str = "dim") -> None: ...

    async def aerror(self, message: str) -> None: ...

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None: ...

    async def aclose(self) -> None: ...


class TuiInputKind(Enum):
    """Runtime-owned categories for submitted TUI input."""

    NORMAL = "normal"
    DESTRUCTIVE = "destructive"
    EXIT = "exit"


def _default_classify_input(_user_input: str) -> TuiInputKind:
    return TuiInputKind.NORMAL


type TuiDispatch = Callable[[str], Awaitable[bool]]
type TuiSurfaceFactory = Callable[
    ...,
    AbstractAsyncContextManager[TuiSurface],
]


class TuiSignalInstaller(Protocol):
    def __call__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        on_resize: Callable[[], None],
        is_turn_in_flight: Callable[[], bool],
    ) -> Callable[[], None]: ...


async def _noop_user_input_echo(_surface: TuiSurface, _text: str) -> None:
    return None


async def _noop_queued_turn_start(_surface: TuiSurface) -> None:
    return None


def _noop_clear_current_cancel() -> None:
    return None


def _noop_install_signal_handlers(
    *,
    loop: asyncio.AbstractEventLoop,
    on_resize: Callable[[], None],
    is_turn_in_flight: Callable[[], bool],
) -> Callable[[], None]:
    del loop, on_resize, is_turn_in_flight
    return lambda: None


async def _noop_cancel_active_turn() -> None:
    return None


@dataclass(frozen=True)
class TuiRuntimeHooks:
    """Adapter-provided hooks for runtime side effects."""

    on_user_input_echo: Callable[
        [TuiSurface, str],
        Awaitable[None],
    ] = _noop_user_input_echo
    on_queued_turn_start: Callable[[TuiSurface], Awaitable[None]] = _noop_queued_turn_start
    clear_current_cancel: Callable[[], None] = _noop_clear_current_cancel
    notice: Callable[[str], None] | None = None
    on_cancel_active_turn: Callable[[], Awaitable[None]] = _noop_cancel_active_turn
    expose_surface: Callable[[TuiSurface], None] | None = None
    clear_exposed_surface: Callable[[], None] | None = None


@dataclass(frozen=True)
class TuiRuntimeConfig:
    """Configuration for the backend TUI state machine."""

    task_name: str
    queue_max_size: int = 8
    classify_input: Callable[[str], TuiInputKind] = _default_classify_input
    install_signal_handlers: TuiSignalInstaller = _noop_install_signal_handlers
    event_sink: Any | None = None
    state: Any | None = None
