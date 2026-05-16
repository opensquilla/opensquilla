"""Process-wide memory tool runtime configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opensquilla.memory.retrieval import MemoryRetriever
    from opensquilla.memory.store import LongTermMemoryStore

MemoryWriteCallback = Callable[[str], object]


class MemoryToolRuntimeError(RuntimeError):
    """Raised when memory tools cannot resolve their configured runtime."""


@dataclass(frozen=True, slots=True)
class ResolvedMemoryAgent:
    agent_id: str
    store: LongTermMemoryStore
    retriever: MemoryRetriever
    memory_dir: str | None
    workspace_dir: str | None


@dataclass(frozen=True, slots=True)
class MemoryToolRuntime:
    stores: Mapping[str, LongTermMemoryStore]
    retrievers: Mapping[str, MemoryRetriever]
    memory_base: str | None = None
    memory_dir: str | None = None
    memory_config: Any | None = None
    on_memory_write: MemoryWriteCallback | None = None
    memory_source: str = "state"
    workspace_base: str | None = None

    def resolve(
        self,
        *,
        agent_id: str | None = None,
        workspace_dir: str | None = None,
    ) -> ResolvedMemoryAgent:
        """Resolve store, retriever, and file roots for an agent."""
        from opensquilla.agents.scope import normalize_agent_id

        resolved_agent_id = normalize_agent_id(agent_id or "main")
        store = _select_agent_value(self.stores, resolved_agent_id, "memory stores")
        retriever = _select_agent_value(
            self.retrievers,
            resolved_agent_id,
            "memory retrievers",
        )

        if self.memory_source not in {"state", "workspace"}:
            raise MemoryToolRuntimeError("memory_source must be 'state' or 'workspace'.")

        if self.memory_source == "workspace":
            memory_dir, resolved_workspace_dir = self._resolve_workspace_source(
                resolved_agent_id,
                workspace_dir,
            )
        elif self.memory_base:
            from opensquilla.agents.scope import resolve_agent_data_dir, resolve_agent_memory_dir

            memory_dir = str(resolve_agent_memory_dir(resolved_agent_id, self.memory_base))
            resolved_workspace_dir = str(
                resolve_agent_data_dir(resolved_agent_id, self.memory_base)
            )
        else:
            memory_dir = self.memory_dir
            resolved_workspace_dir = self.memory_dir

        return ResolvedMemoryAgent(
            agent_id=resolved_agent_id,
            store=store,
            retriever=retriever,
            memory_dir=memory_dir,
            workspace_dir=resolved_workspace_dir,
        )

    def notify_memory_write(self, agent_id: str) -> None:
        if self.on_memory_write is not None:
            self.on_memory_write(agent_id)

    def _resolve_workspace_source(
        self,
        agent_id: str,
        workspace_dir: str | None,
    ) -> tuple[str | None, str | None]:
        from opensquilla.agents.scope import resolve_agent_workspace_dir

        if workspace_dir:
            resolved_workspace_dir: str | None = str(Path(workspace_dir).expanduser().resolve())
        elif self.workspace_base:
            resolved_workspace_dir = str(
                resolve_agent_workspace_dir(
                    agent_id,
                    SimpleNamespace(workspace_dir=self.workspace_base),
                )
            )
        elif self.memory_base:
            resolved_workspace_dir = str(resolve_agent_workspace_dir(agent_id))
        else:
            resolved_workspace_dir = self.memory_dir
        memory_dir = (
            str(Path(resolved_workspace_dir) / "memory")
            if resolved_workspace_dir
            else self.memory_dir
        )
        return memory_dir, resolved_workspace_dir


_runtime: MemoryToolRuntime | None = None


def configure_memory_tools_runtime(
    stores: dict[str, LongTermMemoryStore] | LongTermMemoryStore,
    retrievers: dict[str, MemoryRetriever] | MemoryRetriever,
    *,
    memory_base: str | None = None,
    memory_dir: str | None = None,
    memory_config: Any | None = None,
    on_memory_write: MemoryWriteCallback | None = None,
    memory_source: str = "state",
    workspace_base: str | None = None,
) -> MemoryToolRuntime:
    """Configure the process-wide runtime used by memory tools."""
    global _runtime
    _runtime = MemoryToolRuntime(
        stores=_normalize_agent_mapping(stores),
        retrievers=_normalize_agent_mapping(retrievers),
        memory_base=memory_base,
        memory_dir=memory_dir,
        memory_config=memory_config,
        on_memory_write=on_memory_write,
        memory_source=memory_source,
        workspace_base=workspace_base,
    )
    return _runtime


def reset_memory_tools_runtime() -> None:
    global _runtime
    _runtime = None


def current_memory_tools_runtime() -> MemoryToolRuntime | None:
    return _runtime


def memory_tools_available() -> bool:
    return _runtime is not None


def resolve_memory_agent(
    *,
    agent_id: str | None = None,
    workspace_dir: str | None = None,
) -> ResolvedMemoryAgent:
    runtime = current_memory_tools_runtime()
    if runtime is None:
        raise MemoryToolRuntimeError("memory tools runtime not configured.")
    return runtime.resolve(agent_id=agent_id, workspace_dir=workspace_dir)


def _normalize_agent_mapping[T](value: dict[str, T] | T) -> dict[str, T]:
    if isinstance(value, dict):
        return dict(value)
    return {"main": value}


def _select_agent_value[T](values: Mapping[str, T], agent_id: str, name: str) -> T:
    if not values:
        raise MemoryToolRuntimeError(f"{name} not configured.")
    if agent_id in values:
        return values[agent_id]
    if "main" in values:
        return values["main"]
    return next(iter(values.values()))
