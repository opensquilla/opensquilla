from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.memory.runtime import ResolvedMemoryAgent, reset_memory_tools_runtime
from opensquilla.memory.source_paths import private_archive_error
from opensquilla.memory.tool_sources import (
    MemorySourceError,
    delete_memory_source,
    memory_delete_tool_result,
    memory_get_tool_result,
    read_memory_source,
)
from opensquilla.tools.builtin.memory_tools import create_memory_tools
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, current_tool_context


class FakeStore:
    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove_file(self, path: str) -> None:
        self.removed.append(path)


@pytest.fixture(autouse=True)
def reset_runtime():
    reset_memory_tools_runtime()
    yield
    reset_memory_tools_runtime()


def _agent(workspace: Path, store: FakeStore | None = None) -> ResolvedMemoryAgent:
    return ResolvedMemoryAgent(
        agent_id="main",
        store=store or FakeStore(),
        retriever=object(),
        memory_dir=str(workspace / "memory"),
        workspace_dir=str(workspace),
    )


def test_read_memory_source_reads_slices_and_truncates(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "memory" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert read_memory_source(_agent(workspace), "memory/note.md", from_line=2, lines=1) == "two"

    source.write_text("x" * 9001, encoding="utf-8")
    result = read_memory_source(_agent(workspace), "memory/note.md")
    assert len(result.split("\n\n...")[0]) == 8000
    assert "truncated: showing 8000/9001 chars" in result


def test_read_memory_source_returns_tool_facing_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    archive = workspace / "memory" / "archive" / "turn.md"
    archive.parent.mkdir(parents=True)
    archive.write_text("private", encoding="utf-8")

    with pytest.raises(MemorySourceError, match="path traversal"):
        read_memory_source(_agent(workspace), "../secret.md")
    with pytest.raises(MemorySourceError, match="private turn-capture storage"):
        read_memory_source(_agent(workspace), "memory/archive/turn.md")
    with pytest.raises(MemorySourceError, match="not found"):
        read_memory_source(_agent(workspace), "memory/missing.md")


def test_memory_tool_source_boundary_owns_tool_results() -> None:
    import ast

    root = Path(__file__).resolve().parents[1]
    memory_tools_path = root / "src/opensquilla/tools/builtin/memory_tools.py"
    tool_surface_path = root / "src/opensquilla/memory/tool_surface.py"
    tree = ast.parse(memory_tools_path.read_text(encoding="utf-8"))
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }

    assert tool_surface_path.exists()
    assert ("opensquilla.memory.tool_surface", "create_memory_tool_surface") in imports
    assert (
        "opensquilla.memory.tool_sources",
        "memory_get_tool_result",
    ) not in imports
    assert (
        "opensquilla.memory.tool_sources",
        "memory_delete_tool_result",
    ) not in imports
    assert ("opensquilla.memory.tool_sources", "read_memory_source") not in imports
    assert ("opensquilla.memory.tool_sources", "delete_memory_source") not in imports


def test_memory_get_tool_result_preserves_from_alias_and_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "memory" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("one\ntwo\n", encoding="utf-8")

    assert (
        memory_get_tool_result(
            _agent(workspace),
            "memory/note.md",
            from_line=None,
            lines=None,
            from_arg=2,
        )
        == "two"
    )
    assert (
        memory_get_tool_result(
            _agent(workspace),
            "memory/note.md",
            from_line=None,
            lines=None,
            from_arg="2",
        )
        == "Error: from must be an integer."
    )
    assert (
        memory_get_tool_result(
            _agent(workspace),
            "memory/missing.md",
            from_line=None,
            lines=None,
        )
        == "Error: memory/missing.md not found."
    )


@pytest.mark.asyncio
async def test_delete_memory_source_removes_disk_and_index(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "memory" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("forget", encoding="utf-8")
    store = FakeStore()

    index_path = await delete_memory_source(_agent(workspace, store), "memory/note.md")

    assert index_path == "memory/note.md"
    assert not source.exists()
    assert store.removed == ["memory/note.md"]


@pytest.mark.asyncio
async def test_memory_delete_tool_result_preserves_success_and_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "memory" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("forget", encoding="utf-8")
    store = FakeStore()

    assert (
        await memory_delete_tool_result(_agent(workspace, store), "memory/note.md")
        == "Deleted memory/note.md and removed from index."
    )
    assert not source.exists()
    assert store.removed == ["memory/note.md"]
    assert (
        await memory_delete_tool_result(_agent(workspace, store), "memory/note.md")
        == "Error: memory/note.md not found."
    )


@pytest.mark.asyncio
async def test_registered_memory_get_and_delete_delegate_to_memory_sources(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "memory" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("one\ntwo\n", encoding="utf-8")
    store = FakeStore()
    registry = ToolRegistry()
    create_memory_tools(store, object(), registry=registry, memory_source="workspace")
    memory_get = registry.get("memory_get")
    memory_delete = registry.get("memory_delete")
    assert memory_get is not None
    assert memory_delete is not None

    token = current_tool_context.set(ToolContext(agent_id="main", workspace_dir=str(workspace)))
    try:
        assert await memory_get.handler(path="memory/note.md", from_line=2) == "two"
        assert (
            await memory_delete.handler(path="memory/note.md")
            == "Deleted memory/note.md and removed from index."
        )
        assert await memory_get.handler(path="memory/note.md") == "Error: memory/note.md not found."
    finally:
        current_tool_context.reset(token)

    assert store.removed == ["memory/note.md"]


@pytest.mark.asyncio
async def test_registered_memory_get_archive_policy_preserves_private_errors(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    archive = workspace / "memory" / "archive" / "turn.md"
    archive.parent.mkdir(parents=True)
    archive.write_text("private turn", encoding="utf-8")
    registry = ToolRegistry()
    create_memory_tools(
        FakeStore(),
        object(),
        registry=registry,
        memory_source="workspace",
        memory_config=type("MemoryConfig", (), {"index_captured_turns": False})(),
    )
    memory_get = registry.get("memory_get")
    assert memory_get is not None

    token = current_tool_context.set(ToolContext(agent_id="main", workspace_dir=str(workspace)))
    try:
        assert (
            await memory_get.handler(path="memory/archive/turn.md")
            == private_archive_error()
        )
    finally:
        current_tool_context.reset(token)

    registry = ToolRegistry()
    create_memory_tools(
        FakeStore(),
        object(),
        registry=registry,
        memory_source="workspace",
        memory_config=type("MemoryConfig", (), {"index_captured_turns": True})(),
    )
    memory_get = registry.get("memory_get")
    assert memory_get is not None

    token = current_tool_context.set(ToolContext(agent_id="main", workspace_dir=str(workspace)))
    try:
        assert await memory_get.handler(path="memory/archive/turn.md") == "private turn"
    finally:
        current_tool_context.reset(token)
