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
@pytest.mark.parametrize(
    ("params", "accepted_params"),
    [
        (
            {"agentId": "ops", "sessionKey": "agent:ops:main", "timeoutMs": 100},
            {"agentId": "ops", "sessionKey": "agent:ops:main", "timeoutMs": 100},
        ),
        (
            {"agent_id": "ops", "session_key": "agent:ops:main", "timeout_ms": 100},
            {"agentId": "ops", "sessionKey": "agent:ops:main", "timeoutMs": 100},
        ),
    ],
)
async def test_agent_wait_reports_runtime_bridge_unavailable_with_compat_params(
    params: dict[str, object],
    accepted_params: dict[str, object],
) -> None:
    result = await get_dispatcher().dispatch(
        "r1",
        "agent.wait",
        params,
        RpcContext(conn_id="test", config=GatewayConfig()),
    )

    assert result.error is not None
    assert result.error.code == "agent.unavailable"
    assert result.error.details["reason"] == "runtime_bridge_unavailable"
    assert result.error.details["acceptedParams"] == accepted_params
    assert result.error.details["supportedParams"] == [
        "agentId",
        "agent_id",
        "sessionKey",
        "session_key",
        "timeoutMs",
        "timeout_ms",
    ]
    assert "agents.list" in result.error.details["availableRpcMethods"]


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"agentId": 123}, {"sessionKey": "  "}])
async def test_agent_wait_rejects_non_string_identifiers(params: dict[str, object]) -> None:
    result = await get_dispatcher().dispatch(
        "r1",
        "agent.wait",
        params,
        RpcContext(conn_id="test", config=GatewayConfig()),
    )

    assert result.error is not None
    assert result.error.code == "INVALID_REQUEST"


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
