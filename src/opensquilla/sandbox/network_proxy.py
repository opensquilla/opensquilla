"""Asyncio local HTTP proxy core for sandbox-managed network access."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from urllib.parse import urlsplit

from opensquilla.sandbox.domain_validation import normalize_domain
from opensquilla.sandbox.network_guard import NetworkDecision

_HEADER_LIMIT = 64 * 1024
_DEFAULT_HEADER_READ_TIMEOUT_SECONDS = 5.0


class SandboxProxyServer:
    def __init__(
        self,
        decide: Callable[[str], NetworkDecision],
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        header_read_timeout_seconds: float = _DEFAULT_HEADER_READ_TIMEOUT_SECONDS,
    ) -> None:
        self._decide = decide
        self.host = host
        self.port = port
        self._header_read_timeout_seconds = header_read_timeout_seconds
        self._server: asyncio.Server | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._active_writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        if self._server is not None:
            return

        server = await asyncio.start_server(self._accept_client, self.host, self.port)
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
        if server is not None:
            self._server = None
            server.close()
            await asyncio.sleep(0)

        current_task = asyncio.current_task()
        tasks = [
            task
            for task in self._active_tasks
            if task is not current_task and not task.done()
        ]
        for task in tasks:
            task.cancel()

        writers = tuple(self._active_writers)
        for writer in writers:
            writer.close()
            with suppress(RuntimeError):
                writer.transport.abort()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for writer in writers:
            with suppress(ConnectionError, RuntimeError):
                await writer.wait_closed()

        if server is not None:
            await server.wait_closed()

    def _accept_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._active_writers.add(writer)
        task = asyncio.create_task(self._handle(reader, writer))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._active_tasks.add(task)
        self._active_writers.add(writer)
        try:
            header = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"),
                timeout=self._header_read_timeout_seconds,
            )
            if len(header) > _HEADER_LIMIT:
                raise ValueError("request_header_too_large")
            normalized_host = _extract_request_host(header)
            if not normalized_host:
                raise ValueError("empty_host")
            decision = self._decide(normalized_host)
            if decision.status == "allow" and normalized_host:
                await _write_response(
                    writer,
                    _response(
                        502,
                        "Bad Gateway",
                        b"Upstream proxying is not implemented.\n",
                    ),
                )
            else:
                await _write_response(
                    writer,
                    _response(403, "Forbidden", b"Network access denied.\n"),
                )
        except (
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            ValueError,
        ):
            await _write_response(
                writer,
                _response(403, "Forbidden", b"Network access denied.\n"),
            )
        except Exception:
            await _write_response(
                writer,
                _response(403, "Forbidden", b"Network access denied.\n"),
            )
        finally:
            self._active_writers.discard(writer)
            if task is not None:
                self._active_tasks.discard(task)
            writer.close()
            with suppress(ConnectionError, RuntimeError):
                await writer.wait_closed()


def _extract_request_host(header: bytes) -> str:
    text = header.decode("iso-8859-1", errors="replace")
    lines = text.split("\r\n")
    if not lines or not lines[0].strip():
        raise ValueError("empty_request")

    request_parts = lines[0].split()
    if len(request_parts) != 3:
        raise ValueError("malformed_request_line")

    method = request_parts[0].upper()
    target = request_parts[1]
    version = request_parts[2].upper()
    if not version.startswith("HTTP/"):
        raise ValueError("malformed_request_line")
    if method == "CONNECT":
        return _host_from_connect_target(target)
    if "://" in target:
        return _host_from_absolute_url(target)

    host_values: list[str] = []
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() == "host":
            host_values.append(value)
    if len(host_values) != 1:
        raise ValueError("invalid_host_header")
    return _host_from_authority(host_values[0], require_port=False)


def _host_from_absolute_url(target: str) -> str:
    try:
        parsed = urlsplit(target)
        parsed.port
        hostname = parsed.hostname or ""
    except ValueError as exc:
        raise ValueError("malformed_absolute_url") from exc

    if not parsed.scheme or not parsed.netloc:
        raise ValueError("malformed_absolute_url")
    if "@" in parsed.netloc or parsed.netloc.endswith(":"):
        raise ValueError("malformed_absolute_url")
    return _normalize_nonempty_host(hostname)


def _host_from_connect_target(target: str) -> str:
    if "://" in target or any(char in target for char in "/?#"):
        raise ValueError("malformed_connect_target")
    return _host_from_authority(target, require_port=True)


def _host_from_authority(authority: str, *, require_port: bool) -> str:
    value = authority.strip()
    if not value or "://" in value or "@" in value:
        raise ValueError("malformed_authority")
    if any(char in value for char in "/?#"):
        raise ValueError("malformed_authority")

    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
        hostname = parsed.hostname or ""
    except ValueError as exc:
        raise ValueError("malformed_authority") from exc

    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("malformed_authority")
    if value.endswith(":"):
        raise ValueError("malformed_authority")
    if require_port and port is None:
        raise ValueError("missing_port")
    return _normalize_nonempty_host(hostname)


def _normalize_nonempty_host(host: str) -> str:
    normalized = normalize_domain(host)
    if not normalized:
        raise ValueError("empty_host")
    return normalized


async def _write_response(writer: asyncio.StreamWriter, response: bytes) -> None:
    if writer.is_closing():
        return
    with suppress(ConnectionError, RuntimeError):
        writer.write(response)
        await writer.drain()


def _response(status_code: int, reason: str, body: bytes) -> bytes:
    return (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii") + body


__all__ = ["SandboxProxyServer"]
