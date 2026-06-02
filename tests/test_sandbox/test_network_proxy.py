from __future__ import annotations

import asyncio

from opensquilla.sandbox.network_guard import NetworkDecision
from opensquilla.sandbox.network_proxy import SandboxProxyServer


async def _send_proxy_request(server: SandboxProxyServer, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection(server.host, server.port)
    try:
        writer.write(request)
        await writer.drain()
        return await reader.read(4096)
    finally:
        writer.close()
        await writer.wait_closed()


async def test_proxy_returns_403_for_unknown_absolute_http_host() -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        return NetworkDecision(
            status="ask",
            normalized_host=host,
            reason="unknown_domain",
            source=None,
        )

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        response = await _send_proxy_request(
            server,
            b"GET http://Example.com/path HTTP/1.1\r\n"
            b"Host: ignored.example\r\n"
            b"\r\n",
        )
    finally:
        await server.stop()

    assert response.startswith(b"HTTP/1.1 403")
    assert seen_hosts == ["example.com"]


async def test_proxy_returns_403_for_connect_block() -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        return NetworkDecision(
            status="block",
            normalized_host=host,
            reason="ip_literal",
            source="validation",
        )

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        response = await _send_proxy_request(
            server,
            b"CONNECT 169.254.169.254:443 HTTP/1.1\r\n\r\n",
        )
    finally:
        await server.stop()

    assert response.startswith(b"HTTP/1.1 403")
    assert seen_hosts == ["169.254.169.254"]


async def test_proxy_returns_502_for_allowed_host_until_upstream_is_implemented() -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        return NetworkDecision(
            status="allow",
            normalized_host=host,
            reason="domain_grant",
            source="domain:pypi.org",
        )

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        response = await _send_proxy_request(
            server,
            b"GET /simple HTTP/1.1\r\nHost: PyPI.org:443\r\n\r\n",
        )
    finally:
        await server.stop()

    assert response.startswith(b"HTTP/1.1 502")
    assert seen_hosts == ["pypi.org"]


async def test_proxy_stop_is_idempotent() -> None:
    server = SandboxProxyServer(
        lambda host: NetworkDecision(
            status="ask",
            normalized_host=host,
            reason="unknown_domain",
            source=None,
        )
    )
    await server.start()

    assert server.host == "127.0.0.1"
    assert server.port > 0

    await server.stop()
    await server.stop()
