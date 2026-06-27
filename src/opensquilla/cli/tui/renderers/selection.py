"""Renderer backend registry for TUI evaluation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

OPENSQUILLA_TUI_BACKEND_ENV = "OPENSQUILLA_TUI_BACKEND"
DEFAULT_TUI_BACKEND_ID = "native"


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


def renderer_backends() -> dict[str, TuiRendererBackend]:
    from opensquilla.cli.tui.opentui.bridge import OpenTuiRendererBackend

    backends: list[TuiRendererBackend] = [
        NativeRendererBackend(),
        OpenTuiRendererBackend(),
    ]
    return {backend.backend_id: backend for backend in backends}


def _backend_choices(backends: Mapping[str, TuiRendererBackend]) -> str:
    return ", ".join(
        backend_id for backend_id in sorted(backends) if backend_id != DEFAULT_TUI_BACKEND_ID
    )


def get_renderer_backend(backend_id: str) -> TuiRendererBackend:
    backends = renderer_backends()
    try:
        return backends[backend_id]
    except KeyError as exc:
        raise RendererBackendSelectionError(
            f"Unsupported TUI backend '{backend_id}'. "
            f"Unset {OPENSQUILLA_TUI_BACKEND_ENV} for stable chat, "
            f"or set it to "
            f"{_backend_choices(backends)}."
        ) from exc


def select_renderer_backend(backend_id: str | None = None) -> TuiRendererBackend:
    selected_id = DEFAULT_TUI_BACKEND_ID if backend_id is None else backend_id.strip()
    if not selected_id:
        selected_id = DEFAULT_TUI_BACKEND_ID
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


@dataclass(frozen=True)
class NativeRendererBackend:
    backend_id: str = DEFAULT_TUI_BACKEND_ID
    supports_structured_ui: bool = True
    supports_streaming_fast_path: bool = True

    def is_available(self) -> RendererBackendAvailability:
        return RendererBackendAvailability(available=True)

    def create_renderer(self, **kwargs: Any) -> Any:
        from opensquilla.cli.tui.native.renderer import NativeStreamRenderer

        return NativeStreamRenderer(**kwargs)
