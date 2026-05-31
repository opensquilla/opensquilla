from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from opensquilla.cli.tui.contracts import TuiOutputHandle
from opensquilla.engine.commands import Surface


class _OutputHandle:
    approval_surface = Surface.CLI_GATEWAY

    async def write_through(self, payload: str) -> None:
        return None

    def stream_output(self):
        @asynccontextmanager
        async def _cm() -> AsyncIterator[Callable[[str], None]]:
            yield lambda _payload: None

        return _cm()


class _SurfaceWithOutput:
    def __init__(self, output_handle: TuiOutputHandle) -> None:
        self.output_handle = output_handle


class _SurfaceWithoutOutput:
    output_handle = object()


def test_tui_output_binding_owns_scope_storage() -> None:
    from opensquilla.cli.tui.output_binding import TuiOutputBinding

    scope: dict[str, object] = {}
    output_handle = _OutputHandle()
    binding = TuiOutputBinding(scope)

    assert binding.get() is None

    binding.expose(output_handle)

    assert binding.get() is output_handle

    binding.clear()

    assert binding.get() is None
    assert "tui_output" not in scope


def test_tui_output_binding_exposes_typed_surface_handle_only() -> None:
    from opensquilla.cli.tui.output_binding import TuiOutputBinding

    scope: dict[str, object] = {}
    output_handle = _OutputHandle()
    binding = TuiOutputBinding(scope)

    binding.expose_from_surface(_SurfaceWithoutOutput())
    assert binding.get() is None

    binding.expose_from_surface(_SurfaceWithOutput(output_handle))

    assert binding.get() is output_handle
