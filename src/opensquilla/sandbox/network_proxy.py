"""Asyncio local HTTP proxy core for sandbox-managed network access."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from opensquilla.sandbox.domain_validation import normalize_domain
from opensquilla.sandbox.network_guard import NetworkDecision

_HEADER_LIMIT = 64 * 1024


class SandboxProxyServer:
    def __init__(
        self,
        decide: Callable[[str], NetworkDecision],
        *,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._decide = decide
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        if self._server is not None:
            return

        server = await asyncio.start_server(self._handle, self.host, self.port)
        socket = next(iter(server.sockets or ()), None)
        if socket is None:
            server.close()
            await server.wait_closed()
            raise RuntimeError("sandbox proxy failed to bind")

        bound_host, bound_port = socket.getsockname()[:2]
        self.host = str(bound_host)
        self.port = int(bound_port)
        self._server = server

    async def stop(self) -> None:
        server = self._server
        if server is None:
            return
        self._server = None
        server.close()
        await server.wait_closed()

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            if len(header) > _HEADER_LIMIT:
                raise ValueError("request_header_too_large")
            normalized_host = _extract_request_host(header)
            decision = self._decide(normalized_host)
            if decision.status == "allow" and normalized_host:
                writer.write(
                    _response(
                        502,
                        "Bad Gateway",
                        b"Upstream proxying is not implemented.\n",
                    )
                )
            else:
                writer.write(_response(403, "Forbidden", b"Network access denied.\n"))
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            writer.write(_response(403, "Forbidden", b"Network access denied.\n"))
            await writer.drain()
        except Exception:
            writer.write(_response(403, "Forbidden", b"Network access denied.\n"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


def _extract_request_host(header: bytes) -> str:
    text = header.decode("iso-8859-1", errors="replace")
    lines = text.split("\r\n")
    if not lines or not lines[0].strip():
        return ""

    request_parts = lines[0].split()
    if len(request_parts) < 2:
        return ""

    method = request_parts[0].upper()
    target = request_parts[1]
    if method == "CONNECT":
        return normalize_domain(target)
    if "://" in target:
        return normalize_domain(target)

    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() == "host":
            return normalize_domain(value)
    return ""


def _response(status_code: int, reason: str, body: bytes) -> bytes:
    return (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii") + body


__all__ = ["SandboxProxyServer"]
