from __future__ import annotations

import pytest

from opensquilla.agents.registry import AgentRegistry
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc import RpcContext, get_dispatcher


class _FailingModelSelector:
    async def list_models(self) -> list[dict]:
        raise RuntimeError("provider unavailable")


def _ctx(config: GatewayConfig, registry: AgentRegistry) -> RpcContext:
    return RpcContext(conn_id="test", config=config, agent_registry=registry)


@pytest.mark.asyncio
async def test_agents_rpc_list_uses_config_backed_registry() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)
    await registry.create_agent(agent_id="ops", model="openai/test")

    result = await get_dispatcher().dispatch("r1", "agents.list", {}, _ctx(cfg, registry))

    assert result.error is None, result.error
    assert [agent["id"] for agent in result.payload["agents"]] == ["main", "ops"]
    assert result.payload["agents"][1]["model"] == "openai/test"


@pytest.mark.asyncio
async def test_agents_rpc_list_without_registry_returns_empty() -> None:
    result = await get_dispatcher().dispatch(
        "r1",
        "agents.list",
        {},
        RpcContext(conn_id="test", config=GatewayConfig()),
    )

    assert result.error is None, result.error
    assert result.payload == {"agents": []}


@pytest.mark.asyncio
async def test_models_rpc_list_without_provider_selector_returns_empty() -> None:
    result = await get_dispatcher().dispatch(
        "r1",
        "models.list",
        {},
        RpcContext(conn_id="test"),
    )

    assert result.error is None, result.error
    assert result.payload == []


@pytest.mark.asyncio
async def test_models_rpc_list_provider_failure_returns_empty() -> None:
    result = await get_dispatcher().dispatch(
        "r1",
        "models.list",
        {},
        RpcContext(conn_id="test", provider_selector=_FailingModelSelector()),
    )

    assert result.error is None, result.error
    assert result.payload == []


@pytest.mark.asyncio
async def test_agents_rpc_create_accepts_explicit_id() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.create",
        {"id": "ops", "name": "Operations", "model": "openai/test"},
        _ctx(cfg, registry),
    )

    assert result.error is None, result.error
    assert result.payload["id"] == "ops"
    assert result.payload["name"] == "Operations"
    assert cfg.agents[0].model == "openai/test"


@pytest.mark.asyncio
async def test_agents_rpc_delete_removes_config_entry() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)
    await registry.create_agent(agent_id="ops")

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.delete",
        {"id": "ops"},
        _ctx(cfg, registry),
    )

    assert result.error is None, result.error
    assert result.payload is None
    assert cfg.agents == []


@pytest.mark.asyncio
async def test_agents_rpc_create_duplicate_returns_agent_exists_code() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)
    await registry.create_agent(agent_id="ops")

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.create",
        {"id": "ops"},
        _ctx(cfg, registry),
    )

    assert result.error is not None
    assert result.error.code == "agent.exists"
    assert result.error.details == {"agentId": "ops"}


@pytest.mark.asyncio
async def test_agents_rpc_delete_main_returns_builtin_immutable() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.delete",
        {"id": "main"},
        _ctx(cfg, registry),
    )

    assert result.error is not None
    assert result.error.code == "agent.builtin_immutable"


@pytest.mark.asyncio
async def test_agents_rpc_update_main_returns_builtin_immutable() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.update",
        {"id": "main", "name": "renamed"},
        _ctx(cfg, registry),
    )

    assert result.error is not None
    assert result.error.code == "agent.builtin_immutable"


@pytest.mark.asyncio
async def test_agents_rpc_update_missing_returns_agent_not_found() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.update",
        {"id": "ghost", "model": "openai/test"},
        _ctx(cfg, registry),
    )

    assert result.error is not None
    assert result.error.code == "agent.not_found"
    assert result.error.details == {"agentId": "ghost"}


@pytest.mark.asyncio
async def test_agents_rpc_delete_missing_returns_agent_not_found() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.delete",
        {"id": "ghost"},
        _ctx(cfg, registry),
    )

    assert result.error is not None
    assert result.error.code == "agent.not_found"


@pytest.mark.asyncio
async def test_agents_rpc_update_workspace_field_persists() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)
    await registry.create_agent(agent_id="ops")

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.update",
        {"id": "ops", "workspace": "/tmp/ops"},
        _ctx(cfg, registry),
    )

    assert result.error is None, result.error
    assert cfg.agents[0].workspace == "/tmp/ops"


@pytest.mark.asyncio
async def test_agents_rpc_update_enabled_toggle_persists() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)
    await registry.create_agent(agent_id="ops")

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.update",
        {"id": "ops", "enabled": False},
        _ctx(cfg, registry),
    )

    assert result.error is None, result.error
    assert cfg.agents[0].enabled is False


@pytest.mark.asyncio
async def test_agents_rpc_update_agent_dir_camelcase_persists() -> None:
    cfg = GatewayConfig()
    registry = AgentRegistry(cfg, persist_changes=False)
    await registry.create_agent(agent_id="ops")

    result = await get_dispatcher().dispatch(
        "r1",
        "agents.update",
        {"id": "ops", "agentDir": ".opensquilla/ops-dir"},
        _ctx(cfg, registry),
    )

    assert result.error is None, result.error
    assert cfg.agents[0].agent_dir == ".opensquilla/ops-dir"


@pytest.mark.asyncio
async def test_agents_files_rpc_falls_back_to_workspace_when_registry_unavailable(tmp_path) -> None:
    cfg = GatewayConfig(workspace_dir=str(tmp_path / "workspace"))
    ctx = RpcContext(conn_id="test", config=cfg)

    set_result = await get_dispatcher().dispatch(
        "r1",
        "agents.files.set",
        {"agentId": "main", "name": "MEMORY.md", "content": "notes"},
        ctx,
    )
    assert set_result.error is None, set_result.error
    assert set_result.payload == {"name": "MEMORY.md", "path": "MEMORY.md", "size": 5}

    get_result = await get_dispatcher().dispatch(
        "r2",
        "agents.files.get",
        {"agentId": "main", "name": "MEMORY.md"},
        ctx,
    )
    assert get_result.error is None, get_result.error
    assert get_result.payload == {"name": "MEMORY.md", "content": "notes"}

    list_result = await get_dispatcher().dispatch(
        "r3",
        "agents.files.list",
        {"agentId": "main"},
        ctx,
    )
    assert list_result.error is None, list_result.error
    memory_entry = next(row for row in list_result.payload["files"] if row["name"] == "MEMORY.md")
    assert memory_entry["status"] == "present"
    assert memory_entry["size"] == 5
