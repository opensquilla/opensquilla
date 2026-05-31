"""MCP SSE transport client."""

from __future__ import annotations

import json
from typing import Any, cast

import httpx

from opensquilla import __version__
from opensquilla.env import trust_env as _trust_env
from opensquilla.mcp.client import MCPClient
from opensquilla.mcp.types import MCPServerConfig, MCPToolDef, MCPToolResult


class MCPSSEClient(MCPClient):
    """MCP client using SSE transport (HTTP POST for calls, SSE for responses)."""

    def __init__(self, config: MCPServerConfig) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        self._message_endpoint = config.message_endpoint or "/message"

    @staticmethod
    def _parse_sse_event(raw: str) -> dict[str, Any] | None:
        """Parse a single SSE event block into a JSON dict."""
        if not raw or raw.startswith(":"):
            return None

        data_lines: list[str] = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            # Ignore event:, id:, retry: fields

        if not data_lines:
            return None

        combined = "".join(data_lines)
        try:
            return cast(dict[str, Any], json.loads(combined))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _parse_sse_stream(stream: str) -> list[dict[str, Any]]:
        """Parse a full SSE stream into a list of JSON events."""
        events = []
        for block in stream.split("\n\n"):
            block = block.strip()
            if block:
                event = MCPSSEClient._parse_sse_event(block)
                if event is not None:
                    events.append(event)
        return events

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @property
    def _base_url(self) -> str:
        assert self.config.url is not None
        return self.config.url.rstrip("/")

    @property
    def _message_url(self) -> str:
        return f"{self._base_url}{self._message_endpoint}"

    async def connect(self) -> None:
        """Create the HTTP client session and perform MCP initialization handshake."""
        self._client = httpx.AsyncClient(trust_env=_trust_env())

        # Send initialize request (response is acknowledged server-side;
        # we don't inspect it — the MCP spec only requires us to send the
        # handshake and follow up with the initialized notification).
        await self._send_and_receive(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "opensquilla", "version": __version__},
            },
        )
        # Send initialized notification
        await self._send_notification("notifications/initialized")

    async def close(self) -> None:
        """Close the HTTP client session."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _send_and_receive(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """POST a JSON-RPC request and receive response via SSE."""
        assert self._client is not None

        req_id = self._next_id()
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            request["params"] = params

        # POST the request
        await self._client.post(self._message_url, json=request)

        # GET SSE stream for response
        async with self._client.stream("GET", self._base_url) as response:
            buffer = ""
            async for line in response.aiter_lines():
                if line:
                    buffer += line + "\n"
                else:
                    # Empty line = end of event
                    event = self._parse_sse_event(buffer.strip())
                    buffer = ""
                    if event is not None and event.get("id") == req_id:
                        return event

        return {}

    async def _send_notification(self, method: str) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        assert self._client is not None

        notification: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        await self._client.post(self._message_url, json=notification)

    async def list_tools(self) -> list[MCPToolDef]:
        """List tools from the MCP server."""
        response = await self._send_and_receive("tools/list")
        tools_data = response.get("result", {}).get("tools", [])
        return [
            MCPToolDef(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools_data
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        """Call a tool on the MCP server."""
        response = await self._send_and_receive(
            "tools/call", {"name": name, "arguments": arguments}
        )

        if "error" in response:
            return MCPToolResult(
                content=response["error"].get("message", "Unknown error"),
                is_error=True,
            )

        result = response.get("result", {})
        content_list = result.get("content", [])
        text = "\n".join(c.get("text", "") for c in content_list if c.get("type") == "text")
        return MCPToolResult(content=text)
