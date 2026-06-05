"""Plain terminal stream renderer for the stable chat backend."""

from __future__ import annotations

from typing import Any, Literal


class NativeStreamRenderer:
    """Async renderer that writes assistant output directly to the terminal."""

    def __init__(self, *, title: str = "squilla", output_handle: Any | None = None) -> None:
        del title
        self.output_handle = output_handle
        self.buffer = ""
        self._saw_output = False

    def __enter__(self) -> NativeStreamRenderer:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    async def _write(self, payload: str) -> None:
        if not payload:
            return
        handle = self.output_handle
        if handle is None:
            return
        await handle.write_through(payload)

    async def aappend_text(self, delta: str, *, presentation: str = "answer") -> None:
        del presentation
        if not delta:
            return
        self.buffer += delta
        self._saw_output = True
        await self._write(delta)

    async def aappend_reasoning(self, delta: str) -> None:
        del delta
        return None

    async def atool_start(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        del args, tool_use_id
        await self._write(f"\n[tool] {name}\n")

    async def atool_finished(
        self,
        tool_use_id: str | None,
        *,
        success: bool,
        elapsed: float | None = None,
        error: str | None = None,
        result: object | None = None,
    ) -> None:
        del tool_use_id, elapsed, result
        if success:
            return
        await self._write(f"[tool error] {error or 'failed'}\n")

    async def astatus(self, message: str, *, style: str = "dim") -> None:
        del message, style
        return None

    async def aerror(self, message: str) -> None:
        await self._write(f"\n[error] {message}\n")

    async def afinalize(self, usage: Any | None = None, *, cancelled: bool = False) -> None:
        del usage
        if cancelled:
            await self._write("\n[cancelled]\n")
            return
        if self._saw_output:
            await self._write("\n")

    async def aclose(self) -> None:
        return None
