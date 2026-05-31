"""MCP stdio transport client."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, cast

from opensquilla import __version__
from opensquilla.mcp.client import MCPClient
from opensquilla.mcp.types import MCPServerConfig, MCPToolDef, MCPToolResult


class MCPStdioClient(MCPClient):
    """MCP client using stdio transport (subprocess + Content-Length framing)."""

    _CLOSE_TIMEOUT_SECONDS = 2.0

    def __init__(self, config: MCPServerConfig) -> None:
        super().__init__(config)
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0

    @staticmethod
    def _encode_request(request: dict[str, Any]) -> bytes:
        """Encode a JSON-RPC request with Content-Length framing."""
        body = json.dumps(request)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        return header.encode() + body.encode()

    @staticmethod
    def _decode_response(data: bytes) -> dict[str, Any]:
        """Decode a Content-Length framed response."""
        if b"\r\n\r\n" not in data:
            raise ValueError("Missing header/body separator in response")

        header_part, body = data.split(b"\r\n\r\n", 1)
        headers = header_part.decode()

        content_length: int | None = None
        for line in headers.splitlines():
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break

        if content_length is None:
            raise ValueError("Missing Content-Length header")

        if len(body) < content_length:
            raise ValueError(f"Truncated body: expected {content_length} bytes, got {len(body)}")

        return cast(dict[str, Any], json.loads(body[:content_length].decode()))

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def connect(self) -> None:
        """Spawn the subprocess and perform MCP initialization handshake."""
        assert self.config.command is not None, "stdio transport requires command"

        env: dict[str, str] | None = None
        if self.config.env:
            env = {**os.environ, **self.config.env}

        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            env=env,
        )

        # MCP initialize handshake
        await self._send_request(
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
        """Terminate the subprocess."""
        process = self._process
        self._process = None
        if process is None:
            return
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=self._CLOSE_TIMEOUT_SECONDS)
        except TimeoutError:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def _send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and read the response."""
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None

        req_id = self._next_id()
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            request["params"] = params

        encoded = self._encode_request(request)
        self._process.stdin.write(encoded)
        await self._process.stdin.drain()

        return await self._read_response()

    async def _send_notification(self, method: str) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        assert self._process is not None
        assert self._process.stdin is not None

        notification = {"jsonrpc": "2.0", "method": method}
        encoded = self._encode_request(notification)
        self._process.stdin.write(encoded)
        await self._process.stdin.drain()

    async def _read_response(self) -> dict[str, Any]:
        """Read and decode a Content-Length framed response from stdout."""
        assert self._process is not None
        assert self._process.stdout is not None

        # Read header lines until blank line
        header_lines: list[str] = []
        while True:
            line = await self._process.stdout.readline()
            decoded = line.decode().rstrip("\r\n")
            if decoded == "":
                break
            header_lines.append(decoded)

        content_length: int | None = None
        for h in header_lines:
            if h.lower().startswith("content-length:"):
                content_length = int(h.split(":", 1)[1].strip())
                break

        if content_length is None:
            raise ValueError("Missing Content-Length header in response")

        body = await self._process.stdout.read(content_length)
        return cast(dict[str, Any], json.loads(body.decode()))

    async def list_tools(self) -> list[MCPToolDef]:
        """List tools from the MCP server."""
        response = await self._send_request("tools/list")
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
        response = await self._send_request("tools/call", {"name": name, "arguments": arguments})

        if "error" in response:
            return MCPToolResult(
                content=response["error"].get("message", "Unknown error"),
                is_error=True,
            )

        result = response.get("result", {})
        content_list = result.get("content", [])
        text = "\n".join(c.get("text", "") for c in content_list if c.get("type") == "text")
        return MCPToolResult(content=text)
