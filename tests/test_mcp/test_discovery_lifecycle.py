from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

from opensquilla.mcp.client import MCPClient
from opensquilla.mcp.types import MCPServerConfig, MCPToolDef, MCPToolResult
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolSpec


class FakeMCPClient(MCPClient):
    def __init__(
        self,
        config: MCPServerConfig,
        tools: list[MCPToolDef] | None = None,
        *,
        fail_list: bool = False,
    ) -> None:
        super().__init__(config)
        self.tools = tools or []
        self.fail_list = fail_list
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def list_tools(self) -> list[MCPToolDef]:
        if self.fail_list:
            raise RuntimeError("list failed")
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        return MCPToolResult(content=f"{name}:{arguments}")


@pytest_asyncio.fixture(autouse=True)
async def _close_mcp_clients():
    from opensquilla.mcp.discovery import close_active_clients

    await close_active_clients()
    yield
    await close_active_clients()


@pytest.mark.asyncio
async def test_discovered_mcp_clients_have_owner_and_close_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.mcp import discovery

    config = MCPServerConfig(name="docs", transport="stdio", command="mock-mcp")
    client = FakeMCPClient(
        config,
        tools=[
            MCPToolDef(
                name="lookup",
                description="Lookup docs",
                input_schema={"properties": {"q": {"type": "string"}}, "required": ["q"]},
            )
        ],
    )
    monkeypatch.setattr(discovery, "create_client", lambda _config: client)

    names = await discovery.discover_and_register(config, ToolRegistry(), owner="gateway")
    snapshot = discovery.active_clients_snapshot()

    assert names == ["mcp_lookup"]
    assert len(snapshot) == 1
    assert snapshot[0].owner == "gateway"
    assert snapshot[0].server_name == "docs"
    assert snapshot[0].transport == "stdio"
    assert snapshot[0].client is client
    assert await discovery.close_active_clients(owner="docs") == 1
    assert client.closed is True
    assert discovery.active_clients_snapshot() == ()


@pytest.mark.asyncio
async def test_failed_mcp_discovery_closes_client_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.mcp import discovery

    config = MCPServerConfig(name="broken", transport="stdio", command="mock-mcp")
    client = FakeMCPClient(config, fail_list=True)
    monkeypatch.setattr(discovery, "create_client", lambda _config: client)

    with pytest.raises(RuntimeError, match="list failed"):
        await discovery.discover_and_register(config, ToolRegistry())

    assert client.closed is True
    assert discovery.active_clients_snapshot() == ()


def test_tool_registry_lifecycle_owner_can_remove_mcp_registered_surface() -> None:
    registry = ToolRegistry()

    async def handler() -> str:
        return "ok"

    registry.register(
        spec=ToolSpec(name="mcp_lookup", description="Lookup docs", parameters={}),
        handler=handler,
        owner="mcp:docs",
    )

    assert registry.get("mcp_lookup") is not None

    removed = registry.unregister_owner("mcp:docs")

    assert removed == ["mcp_lookup"]
    assert registry.get("mcp_lookup") is None
