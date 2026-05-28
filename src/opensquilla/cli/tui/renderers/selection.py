"""Renderer backend registry for TUI evaluation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from opensquilla.cli.tui.terminal.renderer import TerminalRenderer

OPENSQUILLA_TUI_BACKEND_ENV = "OPENSQUILLA_TUI_BACKEND"


@dataclass(frozen=True)
class RendererBackendAvailability:
    available: bool
    reason: str | None = None


class RendererBackendSelectionError(ValueError):
    """Raised when a selected renderer backend id is invalid."""


class RendererBackendUnavailableError(RuntimeError):
    """Raised when a selected renderer backend cannot be constructed."""


class TuiRendererBackend(Protocol):
    @property
    def backend_id(self) -> str: ...

    @property
    def supports_structured_ui(self) -> bool: ...

    @property
    def supports_streaming_fast_path(self) -> bool: ...

    def is_available(self) -> RendererBackendAvailability: ...

    def create_renderer(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class TerminalRendererBackend:
    backend_id: str = "terminal"
    supports_structured_ui: bool = False
    supports_streaming_fast_path: bool = True

    def is_available(self) -> RendererBackendAvailability:
        return RendererBackendAvailability(available=True)

    def create_renderer(self, **kwargs: Any) -> TerminalRenderer:
        return TerminalRenderer(**kwargs)


def renderer_backends() -> dict[str, TuiRendererBackend]:
    from opensquilla.cli.tui.renderers.textual_backend import TextualRendererBackend

    backends: list[TuiRendererBackend] = [
        TerminalRendererBackend(),
        TextualRendererBackend(),
    ]
    return {backend.backend_id: backend for backend in backends}


def _backend_choices(backends: Mapping[str, TuiRendererBackend]) -> str:
    return ", ".join(sorted(backends))


def get_renderer_backend(backend_id: str) -> TuiRendererBackend:
    backends = renderer_backends()
    try:
        return backends[backend_id]
    except KeyError as exc:
        raise RendererBackendSelectionError(
            f"Unknown TUI backend '{backend_id}'. "
            f"Expected one of: {_backend_choices(backends)}."
        ) from exc


def select_renderer_backend(backend_id: str | None = None) -> TuiRendererBackend:
    selected_id = "terminal" if backend_id is None else backend_id.strip()
    if not selected_id:
        selected_id = "terminal"
    backend = get_renderer_backend(selected_id)
    availability = backend.is_available()
    if not availability.available:
        raise RendererBackendUnavailableError(
            f"TUI backend '{backend.backend_id}' is unavailable: "
            f"{availability.reason or 'no reason provided'}."
        )
    return backend


def select_renderer_backend_from_env(
    env: Mapping[str, str] | None = None,
) -> TuiRendererBackend:
    source = os.environ if env is None else env
    return select_renderer_backend(source.get(OPENSQUILLA_TUI_BACKEND_ENV))
