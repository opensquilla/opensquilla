"""Config-backed durable agent registry."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

from opensquilla.agents.config import AgentEntryConfig
from opensquilla.agents.scope import resolve_agent_workspace_dir
from opensquilla.agents.workspace_files import (
    list_workspace_agent_files,
    read_workspace_agent_file,
    write_workspace_agent_file,
)
from opensquilla.identity.bootstrap import ensure_agent_workspace
from opensquilla.session.keys import normalize_agent_id


class AgentRegistryConfig(Protocol):
    agents: list[AgentEntryConfig]
    config_path: str | None


AgentConfigPersister = Callable[..., Any]


class AgentRegistry:
    """Durable agent registry backed by a config object's ``agents`` list."""

    def __init__(
        self,
        config: AgentRegistryConfig,
        *,
        config_path: str | Path | None = None,
        config_persister: AgentConfigPersister | None = None,
        persist_changes: bool = True,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.config_persister = config_persister
        self.persist_changes = persist_changes

    async def list_agents(self, *, include_builtin: bool = True) -> list[dict[str, Any]]:
        agents: list[dict[str, Any]] = []
        if include_builtin:
            agents.append(self._main_agent_summary())
        agents.extend(self._entry_summary(entry) for entry in self.config.agents)
        return agents

    async def create_agent(
        self,
        *,
        agent_id: str,
        name: str | None = None,
        description: str | None = None,
        model: str | None = None,
        workspace: str | None = None,
        agent_dir: str | None = None,
        tools: dict[str, Any] | list[str] | str | None = None,
        enabled: bool = True,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_user_agent_id(agent_id)
        if self._find_index(normalized) >= 0:
            raise ValueError(f'Agent "{normalized}" already exists')
        entry = AgentEntryConfig(
            id=normalized,
            name=(name or normalized).strip() or normalized,
            description=description or None,
            model=model or None,
            workspace=workspace or None,
            agent_dir=agent_dir or None,
            tools=tools,
            enabled=enabled,
            system_prompt=system_prompt or None,
        )
        self.config.agents.append(entry)
        await self._persist()
        return self._entry_summary(entry)

    async def update_agent(self, agent_id: str, **fields: Any) -> dict[str, Any]:
        normalized = self._normalize_user_agent_id(agent_id)
        index = self._require_index(normalized)
        entry = self.config.agents[index]
        updates: dict[str, Any] = {}
        for field in (
            "name",
            "description",
            "model",
            "workspace",
            "agent_dir",
            "tools",
            "enabled",
            "system_prompt",
        ):
            if field in fields:
                updates[field] = fields[field]
        if "systemPrompt" in fields:
            updates["system_prompt"] = fields["systemPrompt"]
        if "agentDir" in fields:
            updates["agent_dir"] = fields["agentDir"]
        if not updates:
            raise ValueError("No fields to update")
        next_entry = entry.model_copy(update=updates)
        self.config.agents[index] = next_entry
        await self._persist()
        return self._entry_summary(next_entry)

    async def delete_agent(self, agent_id: str) -> None:
        normalized = self._normalize_user_agent_id(agent_id)
        index = self._require_index(normalized)
        del self.config.agents[index]
        await self._persist()

    def get_agent_model(self, agent_id: str) -> str | None:
        entry = self._find_entry(normalize_agent_id(agent_id))
        return entry.model if entry is not None and entry.enabled else None

    def get_agent_workspace(self, agent_id: str) -> Path:
        entry = self._find_entry(normalize_agent_id(agent_id))
        if entry is not None and entry.workspace:
            return Path(entry.workspace).expanduser()
        return resolve_agent_workspace_dir(agent_id, self.config)

    async def list_agent_files(self, agent_id: str) -> list[dict[str, Any]]:
        return list_workspace_agent_files(self._workspace_root(agent_id))

    async def get_agent_file(self, agent_id: str, name: str) -> dict[str, Any]:
        safe_name, content = read_workspace_agent_file(self._workspace_root(agent_id), name)
        return {"name": safe_name, "content": content}

    async def set_agent_file(self, agent_id: str, name: str, content: Any) -> dict[str, Any]:
        return write_workspace_agent_file(self._workspace_root(agent_id), name, content)

    def _find_index(self, agent_id: str) -> int:
        for index, entry in enumerate(self.config.agents):
            if normalize_agent_id(entry.id) == agent_id:
                return index
        return -1

    def _require_index(self, agent_id: str) -> int:
        index = self._find_index(agent_id)
        if index < 0:
            raise KeyError(f'Agent "{agent_id}" not found')
        return index

    def _find_entry(self, agent_id: str) -> AgentEntryConfig | None:
        index = self._find_index(agent_id)
        return self.config.agents[index] if index >= 0 else None

    @staticmethod
    def _normalize_user_agent_id(agent_id: str) -> str:
        normalized = normalize_agent_id(agent_id)
        if normalized == "main":
            raise ValueError("Cannot modify builtin agent: main")
        return normalized

    async def _persist(self) -> None:
        if not self.persist_changes:
            return
        if self.config_persister is None:
            raise RuntimeError("AgentRegistry persistence requires a config_persister")

        self.config_persister(
            cast(Any, self.config),
            path=self.config_path or self.config.config_path,
            restart_required=True,
        )

    def _main_agent_summary(self) -> dict[str, Any]:
        return {
            "id": "main",
            "name": "Main Agent",
            "description": "Primary OpenSquilla agent",
            "model": None,
            "workspace": str(resolve_agent_workspace_dir("main", self.config)),
            "enabled": True,
            "isBuiltin": True,
            "type": "builtin",
            "tools": [],
        }

    def _entry_summary(self, entry: AgentEntryConfig) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "id": entry.id,
            "name": entry.name or entry.id,
            "description": entry.description,
            "model": entry.model,
            "workspace": entry.workspace or str(resolve_agent_workspace_dir(entry.id, self.config)),
            "agentDir": entry.agent_dir,
            "enabled": entry.enabled,
            "isBuiltin": False,
            "type": "custom",
            "tools": self._tool_summary(entry.tools),
        }
        if entry.subagents is not None:
            summary["subagents"] = entry.subagents.model_dump(exclude_none=True)
        return summary

    @staticmethod
    def _tool_summary(tools: dict[str, Any] | list[str] | str | None) -> list[str]:
        if tools is None:
            return []
        if isinstance(tools, str):
            return [tools]
        if isinstance(tools, list):
            return [str(item) for item in tools if str(item).strip()]
        allow = tools.get("allow")
        if isinstance(allow, str):
            return [allow]
        if isinstance(allow, list):
            return [str(item) for item in allow if str(item).strip()]
        return []

    def _workspace_root(self, agent_id: str) -> Path:
        normalized = normalize_agent_id(agent_id)
        return ensure_agent_workspace(self.get_agent_workspace(normalized)).workspace_dir
