from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.sandbox.types import SandboxBackendError
from opensquilla.tools.builtin import filesystem as fs
from opensquilla.tools.builtin import patch as patch_tool
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


class _InlineExecutorLoop:
    async def run_in_executor(self, executor: object, func: object, *args: object) -> object:
        return func(*args)  # type: ignore[operator]


@contextmanager
def _tool_context(workspace: Path) -> Iterator[ToolContext]:
    ctx = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.CLI,
        workspace_dir=str(workspace),
        run_mode="trusted",
        session_key="s1",
    )
    token = current_tool_context.set(ctx)
    try:
        yield ctx
    finally:
        current_tool_context.reset(token)


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    try:
        yield
    finally:
        reset_runtime()


def _configure_with_backend(workspace: Path, backend: object) -> None:
    runtime = configure_runtime(
        SandboxSettings(run_mode="trusted", backend="noop", allow_legacy_mode=True),
        workspace=workspace,
    )
    runtime.backend = backend  # type: ignore[misc]


class _UnsupportedWindowsBackend:
    name = "windows_default"

    def operation_domains_supported(self) -> frozenset[str]:
        return frozenset()


def test_linux_backend_supports_filesystem_operations() -> None:
    from opensquilla.sandbox.backend.bubblewrap import BubblewrapBackend
    from opensquilla.sandbox.backend.seatbelt import SeatbeltBackend

    assert "filesystem" in BubblewrapBackend().operation_domains_supported()
    assert "filesystem" not in SeatbeltBackend().operation_domains_supported()


@pytest.mark.asyncio
async def test_write_file_uses_backend_filesystem_operation_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    calls: list[object] = []

    class _Backend:
        name = "windows_default"

        def operation_domains_supported(self) -> frozenset[str]:
            return frozenset({"filesystem"})

        async def run_operation(self, operation: object) -> object:
            calls.append(operation)
            return SimpleNamespace(message=f"Written 5 bytes to {target}", created=True)

    _configure_with_backend(workspace, _Backend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        result = await fs.write_file(str(target), "hello")

    assert result == f"Written 5 bytes to {target}"
    assert not target.exists()
    assert len(calls) == 1
    operation = calls[0]
    assert getattr(operation, "kind") == "write_text"
    assert getattr(operation, "request").path == target
    assert getattr(operation, "request").content == "hello"


@pytest.mark.asyncio
async def test_write_file_uses_linux_backend_filesystem_worker_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    calls: list[object] = []

    class _Backend:
        name = "bubblewrap"

        def operation_domains_supported(self) -> frozenset[str]:
            return frozenset({"filesystem"})

        async def run_operation(self, operation: object) -> object:
            calls.append(operation)
            return SimpleNamespace(message=f"Written 5 bytes to {target}", created=True)

    _configure_with_backend(workspace, _Backend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        result = await fs.write_file(str(target), "hello")

    assert result == f"Written 5 bytes to {target}"
    assert not target.exists()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_write_file_refuses_host_fallback_for_windows_sandbox_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"

    _configure_with_backend(workspace, _UnsupportedWindowsBackend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        with pytest.raises(SandboxBackendError, match="filesystem operations"):
            await fs.write_file(str(target), "hello")

    assert not target.exists()


@pytest.mark.asyncio
async def test_write_file_full_host_access_keeps_host_path_for_windows_backend_without_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"

    _configure_with_backend(workspace, _UnsupportedWindowsBackend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace) as ctx:
        ctx.run_mode = "full"
        result = await fs.write_file(str(target), "hello")

    assert "Written 5 bytes" in result
    assert target.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_read_file_uses_backend_filesystem_operation_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("host text\n", encoding="utf-8")
    calls: list[object] = []

    class _Backend:
        name = "windows_default"

        def operation_domains_supported(self) -> frozenset[str]:
            return frozenset({"filesystem"})

        async def run_operation(self, operation: object) -> object:
            calls.append(operation)
            return SimpleNamespace(message="1: backend text")

    _configure_with_backend(workspace, _Backend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        result = await fs.read_file(str(target))

    assert result == "1: backend text"
    assert len(calls) == 1
    operation = calls[0]
    assert getattr(operation, "kind") == "read_file"
    assert getattr(operation, "request").path == target


@pytest.mark.asyncio
async def test_read_file_refuses_host_fallback_for_windows_sandbox_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("host text\n", encoding="utf-8")

    _configure_with_backend(workspace, _UnsupportedWindowsBackend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        with pytest.raises(SandboxBackendError, match="filesystem operations"):
            await fs.read_file(str(target))


@pytest.mark.asyncio
async def test_list_dir_uses_backend_filesystem_operation_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "host.txt").write_text("host", encoding="utf-8")
    calls: list[object] = []

    class _Backend:
        name = "windows_default"

        def operation_domains_supported(self) -> frozenset[str]:
            return frozenset({"filesystem"})

        async def run_operation(self, operation: object) -> object:
            calls.append(operation)
            return SimpleNamespace(message="[file] backend.txt (7 bytes)")

    _configure_with_backend(workspace, _Backend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        result = await fs.list_dir(str(workspace))

    assert result == "[file] backend.txt (7 bytes)"
    assert len(calls) == 1
    operation = calls[0]
    assert getattr(operation, "kind") == "list_dir"
    assert getattr(operation, "request").path == workspace


@pytest.mark.asyncio
async def test_glob_search_uses_backend_filesystem_operation_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "host.py").write_text("host", encoding="utf-8")
    calls: list[object] = []

    class _Backend:
        name = "windows_default"

        def operation_domains_supported(self) -> frozenset[str]:
            return frozenset({"filesystem"})

        async def run_operation(self, operation: object) -> object:
            calls.append(operation)
            return SimpleNamespace(message=str(workspace / "backend.py"))

    _configure_with_backend(workspace, _Backend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        result = await fs.glob_search("*.py", str(workspace))

    assert result == str(workspace / "backend.py")
    assert len(calls) == 1
    operation = calls[0]
    assert getattr(operation, "kind") == "glob_search"
    assert getattr(operation, "request").path == workspace
    assert getattr(operation, "request").pattern == "*.py"


@pytest.mark.asyncio
async def test_grep_search_uses_backend_filesystem_operation_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "host.py").write_text("needle host\n", encoding="utf-8")
    calls: list[object] = []

    class _Backend:
        name = "windows_default"

        def operation_domains_supported(self) -> frozenset[str]:
            return frozenset({"filesystem"})

        async def run_operation(self, operation: object) -> object:
            calls.append(operation)
            return SimpleNamespace(message=f"{workspace / 'backend.py'}:1: needle backend")

    _configure_with_backend(workspace, _Backend())
    monkeypatch.setattr(fs.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    with _tool_context(workspace):
        result = await fs.grep_search("needle", str(workspace), "*.py")

    assert result == f"{workspace / 'backend.py'}:1: needle backend"
    assert len(calls) == 1
    operation = calls[0]
    assert getattr(operation, "kind") == "grep_search"
    assert getattr(operation, "request").path == workspace
    assert getattr(operation, "request").pattern == "needle"
    assert getattr(operation, "request").include == "*.py"


@pytest.mark.asyncio
async def test_apply_patch_uses_backend_filesystem_operation_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "created.txt"
    calls: list[object] = []

    class _Backend:
        name = "windows_default"

        def operation_domains_supported(self) -> frozenset[str]:
            return frozenset({"filesystem"})

        async def run_operation(self, operation: object) -> object:
            calls.append(operation)
            return SimpleNamespace(message="Applied patch: 1 file(s) added", created=True)

    _configure_with_backend(workspace, _Backend())
    monkeypatch.setattr(patch_tool.asyncio, "get_event_loop", lambda: _InlineExecutorLoop())

    patch = """*** Begin Patch
*** Add File: created.txt
+hello
*** End Patch"""

    with _tool_context(workspace):
        result = await patch_tool.apply_patch(patch)

    assert result == "Applied patch: 1 file(s) added"
    assert not target.exists()
    assert len(calls) == 1
    operation = calls[0]
    assert getattr(operation, "kind") == "apply_patch"
    assert getattr(operation, "request").root == workspace
    assert getattr(operation, "request").paths == (target,)
