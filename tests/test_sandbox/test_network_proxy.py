from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from opensquilla.sandbox.network_guard import NetworkDecision
from opensquilla.sandbox.network_proxy import SandboxProxyServer


def _allow_decision(host: str) -> NetworkDecision:
    return NetworkDecision(
        status="allow",
        normalized_host=host,
        reason="test_allow",
        source="test",
    )


async def _send_proxy_request(server: SandboxProxyServer, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection(server.host, server.port)
    try:
        writer.write(request)
        await writer.drain()
        return await reader.read(4096)
    finally:
        writer.close()
        await writer.wait_closed()


async def _wait_for_active_client(server: SandboxProxyServer) -> None:
    for _ in range(50):
        if server._active_writers:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("proxy did not register active client")


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


@pytest.mark.parametrize(
    "target",
    [
        b"http://PyPI.org:99999/simple",
        b"http://PyPI.org:abc/simple",
        b"http://PyPI.org:443:evil/simple",
    ],
)
async def test_proxy_rejects_malformed_absolute_url_port_before_decision(
    target: bytes,
) -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        return _allow_decision(host)

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        response = await _send_proxy_request(
            server,
            b"GET " + target + b" HTTP/1.1\r\n\r\n",
        )
    finally:
        await server.stop()

    assert response.startswith(b"HTTP/1.1 403")
    assert seen_hosts == []


async def test_proxy_rejects_malformed_connect_target_before_decision() -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        return _allow_decision(host)

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        response = await _send_proxy_request(
            server,
            b"CONNECT http://PyPI.org:443/simple HTTP/1.1\r\n\r\n",
        )
    finally:
        await server.stop()

    assert response.startswith(b"HTTP/1.1 403")
    assert seen_hosts == []


async def test_proxy_rejects_duplicate_host_headers_before_decision() -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        return _allow_decision(host)

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        response = await _send_proxy_request(
            server,
            b"GET /simple HTTP/1.1\r\n"
            b"Host: PyPI.org\r\n"
            b"Host: example.com\r\n"
            b"\r\n",
        )
    finally:
        await server.stop()

    assert response.startswith(b"HTTP/1.1 403")
    assert seen_hosts == []


async def test_proxy_rejects_missing_or_empty_host_before_decision() -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        return _allow_decision(host)

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        missing_host = await _send_proxy_request(
            server,
            b"GET /simple HTTP/1.1\r\n\r\n",
        )
        empty_host = await _send_proxy_request(
            server,
            b"GET /simple HTTP/1.1\r\nHost: \r\n\r\n",
        )
    finally:
        await server.stop()

    assert missing_host.startswith(b"HTTP/1.1 403")
    assert empty_host.startswith(b"HTTP/1.1 403")
    assert seen_hosts == []


async def test_proxy_returns_403_when_decision_callback_raises() -> None:
    seen_hosts: list[str] = []

    def decide(host: str) -> NetworkDecision:
        seen_hosts.append(host)
        raise RuntimeError("decision failed")

    server = SandboxProxyServer(decide)
    await server.start()
    try:
        response = await _send_proxy_request(
            server,
            b"GET /simple HTTP/1.1\r\nHost: PyPI.org\r\n\r\n",
        )
    finally:
        await server.stop()

    assert response.startswith(b"HTTP/1.1 403")
    assert seen_hosts == ["pypi.org"]


async def test_proxy_stop_closes_idle_active_client() -> None:
    server = SandboxProxyServer(_allow_decision)
    await server.start()
    reader, writer = await asyncio.open_connection(server.host, server.port)
    try:
        writer.write(b"GET /simple HTTP/1.1\r\n")
        await writer.drain()
        await _wait_for_active_client(server)

        await server.stop()

        with suppress(ConnectionResetError):
            assert await asyncio.wait_for(reader.read(4096), timeout=1.0) == b""
    finally:
        writer.close()
        with suppress(ConnectionResetError):
            await writer.wait_closed()
