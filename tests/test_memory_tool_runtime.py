from __future__ import annotations

import pytest

from opensquilla.memory.runtime import (
    MemoryToolRuntimeError,
    configure_memory_tools_runtime,
    current_memory_tools_runtime,
    memory_tools_available,
    reset_memory_tools_runtime,
    resolve_memory_agent,
)
from opensquilla.tools.builtin import memory_tools
from opensquilla.tools.builtin.memory_tools import create_memory_tools
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, ToolError, current_tool_context


@pytest.fixture(autouse=True)
def reset_runtime():
    reset_memory_tools_runtime()
    yield
    reset_memory_tools_runtime()


def test_configure_memory_runtime_keeps_single_store_compatibility(tmp_path) -> None:
    store = object()
    retriever = object()

    runtime = configure_memory_tools_runtime(
        store,
        retriever,
        memory_dir=str(tmp_path / "memory"),
    )

    assert runtime is current_memory_tools_runtime()
    assert memory_tools_available()
    resolved = resolve_memory_agent()
    assert resolved.agent_id == "main"
    assert resolved.store is store
    assert resolved.retriever is retriever
    assert resolved.memory_dir == str(tmp_path / "memory")
    assert resolved.workspace_dir == str(tmp_path / "memory")


def test_memory_runtime_resolves_agent_specific_state_dirs(tmp_path) -> None:
    main_store = object()
    ops_store = object()
    main_retriever = object()
    ops_retriever = object()

    configure_memory_tools_runtime(
        {"main": main_store, "ops": ops_store},
        {"main": main_retriever, "ops": ops_retriever},
        memory_base=str(tmp_path / "state"),
    )

    resolved = resolve_memory_agent(agent_id="ops")

    assert resolved.store is ops_store
    assert resolved.retriever is ops_retriever
    assert resolved.memory_dir == str(tmp_path / "state" / "agents" / "ops" / "memory")
    assert resolved.workspace_dir == str(tmp_path / "state" / "agents" / "ops")


def test_memory_runtime_resolves_workspace_source_from_context(tmp_path) -> None:
    configure_memory_tools_runtime(
        object(),
        object(),
        memory_source="workspace",
        workspace_base=str(tmp_path / "workspace-root"),
    )

    context_workspace = tmp_path / "active-workspace"
    resolved = resolve_memory_agent(agent_id="ops", workspace_dir=str(context_workspace))

    assert resolved.memory_dir == str(context_workspace.resolve() / "memory")
    assert resolved.workspace_dir == str(context_workspace.resolve())


def test_memory_runtime_falls_back_to_main_store() -> None:
    main_store = object()
    main_retriever = object()

    configure_memory_tools_runtime(
        {"main": main_store},
        {"main": main_retriever},
    )

    resolved = resolve_memory_agent(agent_id="unknown")

    assert resolved.store is main_store
    assert resolved.retriever is main_retriever


def test_memory_runtime_reports_invalid_source_on_resolution() -> None:
    configure_memory_tools_runtime(object(), object(), memory_source="elsewhere")

    with pytest.raises(MemoryToolRuntimeError, match="memory_source"):
        resolve_memory_agent()


@pytest.mark.asyncio
async def test_registered_memory_tools_resolve_through_memory_runtime(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    memory_file = workspace / "memory" / "note.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("remembered via runtime", encoding="utf-8")
    registry = ToolRegistry()

    create_memory_tools(
        object(),
        object(),
        registry=registry,
        memory_source="workspace",
    )

    tool = registry.get("memory_get")
    assert tool is not None

    token = current_tool_context.set(ToolContext(agent_id="ops", workspace_dir=str(workspace)))
    try:
        result = await tool.handler(path="memory/note.md")
    finally:
        current_tool_context.reset(token)

    assert result == "remembered via runtime"


@pytest.mark.asyncio
async def test_registered_memory_tools_surface_runtime_errors() -> None:
    registry = ToolRegistry()
    create_memory_tools(object(), object(), registry=registry, memory_source="invalid")
    tool = registry.get("memory_get")
    assert tool is not None

    with pytest.raises(ToolError, match="memory_source"):
        await tool.handler(path="MEMORY.md")


@pytest.mark.asyncio
async def test_registered_memory_tools_delegate_to_memory_tool_surface(monkeypatch) -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class FakeSurface:
        async def search(self, query: str, max_results: int) -> str:
            calls.append(("search", (query, max_results), {}))
            return "surface search"

        async def save(self, content: str, *, path: str = "", mode: str = "append") -> str:
            calls.append(("save", (content,), {"path": path, "mode": mode}))
            return "surface save"

        def get(
            self,
            path: str,
            *,
            from_line: int | None = None,
            lines: int | None = None,
            from_arg: object | None = None,
        ) -> str:
            calls.append(
                (
                    "get",
                    (path,),
                    {"from_line": from_line, "lines": lines, "from_arg": from_arg},
                )
            )
            return "surface get"

        async def delete(self, path: str) -> str:
            calls.append(("delete", (path,), {}))
            return "surface delete"

    def fake_create_memory_tool_surface(*args: object, **kwargs: object) -> FakeSurface:
        calls.append(("create", args, kwargs))
        return FakeSurface()

    monkeypatch.setattr(
        memory_tools,
        "create_memory_tool_surface",
        fake_create_memory_tool_surface,
        raising=False,
    )
    registry = ToolRegistry()
    store = object()
    retriever = object()

    memory_tools.create_memory_tools(
        store,
        retriever,
        registry=registry,
        memory_source="workspace",
        memory_base="/state",
        workspace_base="/workspace",
    )

    assert await registry.get("memory_search").handler(query="alpha", max_results=2) == (
        "surface search"
    )
    assert await registry.get("memory_save").handler(
        content="remember",
        path="memory/note.md",
        mode="replace",
    ) == "surface save"
    assert await registry.get("memory_get").handler(
        path="memory/note.md",
        from_line=3,
        **{"from": 2},
    ) == "surface get"
    assert await registry.get("memory_delete").handler(path="memory/note.md") == (
        "surface delete"
    )

    assert calls == [
        (
            "create",
            (store, retriever),
            {
                "memory_base": "/state",
                "memory_dir": None,
                "memory_config": None,
                "on_memory_write": None,
                "memory_source": "workspace",
                "workspace_base": "/workspace",
            },
        ),
        ("search", ("alpha", 2), {}),
        ("save", ("remember",), {"path": "memory/note.md", "mode": "replace"}),
        (
            "get",
            ("memory/note.md",),
            {"from_line": 3, "lines": None, "from_arg": 2},
        ),
        ("delete", ("memory/note.md",), {}),
    ]
