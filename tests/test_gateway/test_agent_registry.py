from __future__ import annotations

import pytest

from opensquilla.agents.registry import AgentRegistry
from opensquilla.agents.scope import resolve_agent_workspace_dir
from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig


@pytest.mark.asyncio
async def test_registry_lists_builtin_and_configured_agents() -> None:
    cfg = GatewayConfig(agents=[AgentEntryConfig(id="ops", model="openai/test")])
    registry = AgentRegistry(cfg, persist_changes=False)

    agents = await registry.list_agents()

    assert [agent["id"] for agent in agents] == ["main", "ops"]
    assert agents[0]["isBuiltin"] is True
    assert agents[1]["model"] == "openai/test"


@pytest.mark.asyncio
async def test_registry_create_and_delete_mutates_config_without_persisting() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)

    created = await registry.create_agent(agent_id="Ops Team", model="openai/test")
    await registry.delete_agent("ops-team")

    assert created["id"] == "ops-team"
    assert cfg.agents == []


@pytest.mark.asyncio
async def test_registry_persists_through_injected_persister(tmp_path) -> None:
    cfg = GatewayConfig()
    calls = []

    def persist_config(config, **kwargs):
        calls.append((config, kwargs))

    registry = AgentRegistry(
        cfg,
        config_path=tmp_path / "config.toml",
        config_persister=persist_config,
    )

    await registry.create_agent(agent_id="Ops Team", model="openai/test")

    assert calls == [
        (
            cfg,
            {
                "path": tmp_path / "config.toml",
                "restart_required": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_registry_requires_persister_when_persistence_enabled() -> None:
    registry = AgentRegistry(GatewayConfig())

    with pytest.raises(RuntimeError, match="config_persister"):
        await registry.create_agent(agent_id="ops")


@pytest.mark.asyncio
async def test_registry_rejects_builtin_main_mutation() -> None:
    registry = AgentRegistry(GatewayConfig(), persist_changes=False)

    with pytest.raises(ValueError, match="builtin agent"):
        await registry.create_agent(agent_id="main")


def test_resolve_agent_workspace_dir_uses_configured_agent_workspace(tmp_path) -> None:
    root = tmp_path / "root"
    agent_workspace = tmp_path / "ops-workspace"
    cfg = GatewayConfig(
        workspace_dir=str(root),
        agents=[AgentEntryConfig(id="ops", workspace=str(agent_workspace))],
    )

    assert resolve_agent_workspace_dir("ops", cfg) == agent_workspace
    assert resolve_agent_workspace_dir("main", cfg) == root
