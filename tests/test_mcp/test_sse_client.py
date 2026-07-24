from __future__ import annotations

import asyncio
import http.server
import json
import queue
import threading
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from opensquilla.mcp.sse import MCPSSEClient
from opensquilla.mcp.types import MCPServerConfig

TOOLS = [
    {
        "name": "echo",
        "description": "Echo the given text back.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
]


class EndpointHandshakeSSEServer:
    """Minimal 2024-11-05 HTTP+SSE MCP server.

    * ``GET /sse`` opens a ``text/event-stream`` whose first event is
      ``event: endpoint`` carrying the session message URL; responses to
      POSTed requests arrive on this same stream.
    * ``POST /messages?session_id=<id>`` returns 202 and queues the response
      onto that session's stream.
    * Anything else returns 404 and is recorded in ``wrong_posts``.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, queue.Queue[dict[str, Any]]] = {}
        self.wrong_posts: list[str] = []
        self.session_posts: list[str] = []
        self.authorization_headers: list[str | None] = []
        self._shutdown = threading.Event()

        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                outer.authorization_headers.append(self.headers.get("Authorization"))
                if urlparse(self.path).path != "/sse":
                    self._plain(404, b"Not Found")
                    return
                sid = uuid.uuid4().hex
                q: queue.Queue[dict[str, Any]] = queue.Queue()
                outer.sessions[sid] = q
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self._write(f"event: endpoint\ndata: /messages?session_id={sid}\n\n")
                while not outer._shutdown.is_set():
                    try:
                        payload = q.get(timeout=0.1)
                    except queue.Empty:
                        if not self._write(": keepalive\n\n"):
                            return
                        continue
                    if not self._write(f"event: message\ndata: {json.dumps(payload)}\n\n"):
                        return

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                outer.authorization_headers.append(self.headers.get("Authorization"))
                parsed = urlparse(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                sid = (parse_qs(parsed.query).get("session_id") or [""])[0]
                if parsed.path != "/messages" or sid not in outer.sessions:
                    outer.wrong_posts.append(parsed.path)
                    self._plain(404, b"Not Found")
                    return
                msg = json.loads(body)
                outer.session_posts.append(msg.get("method", "?"))
                if "id" in msg:
                    outer.sessions[sid].put(outer.respond(msg))
                self._plain(202, b"Accepted")

            def _write(self, chunk: str) -> bool:
                try:
                    self.wfile.write(chunk.encode())
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionError, OSError):
                    return False

            def _plain(self, status: int, payload: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @staticmethod
    def respond(msg: dict[str, Any]) -> dict[str, Any]:
        method = msg["method"]
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sse-test", "version": "0.0.1"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "error": {"code": -32601, "message": f"unknown method {method}"},
            }
        return {"jsonrpc": "2.0", "id": msg["id"], "result": result}

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._shutdown.set()
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def sse_server(monkeypatch: pytest.MonkeyPatch) -> Any:
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                "all_proxy", "OPENSQUILLA_TRUST_ENV"):
        monkeypatch.delenv(var, raising=False)
    server = EndpointHandshakeSSEServer()
    server.start()
    yield server
    server.stop()


async def test_connect_completes_endpoint_handshake_and_lists_tools(
    sse_server: EndpointHandshakeSSEServer,
) -> None:
    config = MCPServerConfig(
        name="demo",
        transport="sse",
        url=f"http://127.0.0.1:{sse_server.port}/sse",
    )
    client = MCPSSEClient(config)
    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        tools = await asyncio.wait_for(client.list_tools(), timeout=10)
    finally:
        await client.close()

    assert [t.name for t in tools] == ["echo"]
    assert sse_server.session_posts == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    assert sse_server.wrong_posts == []


async def test_configured_headers_reach_sse_stream_and_message_posts(
    sse_server: EndpointHandshakeSSEServer,
) -> None:
    config = MCPServerConfig(
        name="authenticated",
        transport="sse",
        url=f"http://127.0.0.1:{sse_server.port}/sse",
        headers={"Authorization": "Bearer test-token"},
    )
    client = MCPSSEClient(config)
    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        await asyncio.wait_for(client.list_tools(), timeout=10)
    finally:
        await client.close()

    assert sse_server.authorization_headers
    assert set(sse_server.authorization_headers) == {"Bearer test-token"}


def test_endpoint_event_rejects_cross_origin_url() -> None:
    client = MCPSSEClient(
        MCPServerConfig(
            name="demo",
            transport="sse",
            url="https://mcp.example.test/sse",
        )
    )

    with pytest.raises(ValueError, match="same origin"):
        client._handle_event("endpoint", "http://127.0.0.1:8080/private")

    assert client._message_url is None
    assert not client._endpoint_ready.is_set()


@pytest.mark.parametrize(
    "endpoint",
    [
        "/messages?session_id=1",
        "https://mcp.example.test/messages?session_id=1",
        "https://mcp.example.test:443/messages?session_id=1",
    ],
)
def test_endpoint_event_accepts_same_origin_url(endpoint: str) -> None:
    client = MCPSSEClient(
        MCPServerConfig(
            name="demo",
            transport="sse",
            url="https://mcp.example.test/sse",
        )
    )

    client._handle_event("endpoint", endpoint)

    assert client._message_url is not None
    assert client._endpoint_ready.is_set()
