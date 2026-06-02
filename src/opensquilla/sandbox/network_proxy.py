"""Asyncio local HTTP proxy core for sandbox-managed network access."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

from opensquilla.sandbox.domain_validation import normalize_domain
from opensquilla.sandbox.network_guard import NetworkDecision

_HEADER_LIMIT = 64 * 1024
_DEFAULT_HEADER_READ_TIMEOUT_SECONDS = 5.0
_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class _ParsedRequest:
    method: str
    target: str
    version: str
    host: str
    port: int
    origin_form: str | None
    content_length: int


class SandboxProxyServer:
    def __init__(
        self,
        decide: Callable[[str], NetworkDecision],
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        header_read_timeout_seconds: float = _DEFAULT_HEADER_READ_TIMEOUT_SECONDS,
        resolver: Callable[[str, int], tuple[str, int]] | None = None,
    ) -> None:
        self._decide = decide
        self._resolver = resolver or _identity_resolver
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
            request = _parse_request(header)
            if not request.host:
                raise ValueError("empty_host")
            decision = self._decide(request.host)
            if decision.status == "allow" and request.host:
                try:
                    if request.method == "CONNECT":
                        await self._forward_connect(request, reader, writer)
                    else:
                        await self._forward_http(request, header, reader, writer)
                except Exception:
                    await _write_response(
                        writer,
                        _response(502, "Bad Gateway", b"Upstream connection failed.\n"),
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

    async def _open_upstream(
        self,
        request: _ParsedRequest,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        connect_host, connect_port = self._resolver(request.host, request.port)
        upstream_reader, upstream_writer = await asyncio.open_connection(
            connect_host,
            connect_port,
        )
        self._active_writers.add(upstream_writer)
        return upstream_reader, upstream_writer

    async def _forward_http(
        self,
        request: _ParsedRequest,
        header: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if request.origin_form is None:
            raise ValueError("missing_origin_form")
        upstream_reader, upstream_writer = await self._open_upstream(request)
        try:
            body = b""
            if request.content_length:
                body = await reader.readexactly(request.content_length)
            upstream_writer.write(_rewrite_http_header(request, header) + body)
            await upstream_writer.drain()

            while True:
                chunk = await upstream_reader.read(_CHUNK_SIZE)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        finally:
            self._active_writers.discard(upstream_writer)
            upstream_writer.close()
            with suppress(ConnectionError, RuntimeError):
                await upstream_writer.wait_closed()

    async def _forward_connect(
        self,
        request: _ParsedRequest,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        upstream_reader, upstream_writer = await self._open_upstream(request)
        try:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await _tunnel(reader, writer, upstream_reader, upstream_writer)
        finally:
            self._active_writers.discard(upstream_writer)
            upstream_writer.close()
            with suppress(ConnectionError, RuntimeError):
                await upstream_writer.wait_closed()


def _extract_request_host(header: bytes) -> str:
    return _parse_request(header).host


def _parse_request(header: bytes) -> _ParsedRequest:
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
    content_length = _content_length(lines[1:])
    if method == "CONNECT":
        host, port = _host_port_from_connect_target(target)
        return _ParsedRequest(
            method=method,
            target=target,
            version=version,
            host=host,
            port=port,
            origin_form=None,
            content_length=content_length,
        )
    if "://" in target:
        if len(_host_values(lines[1:])) > 1:
            raise ValueError("invalid_host_header")
        host, port, origin_form = _parts_from_absolute_url(target)
        return _ParsedRequest(
            method=method,
            target=target,
            version=version,
            host=host,
            port=port,
            origin_form=origin_form,
            content_length=content_length,
        )

    host_values = _host_values(lines[1:])
    if len(host_values) != 1:
        raise ValueError("invalid_host_header")
    host, port = _host_port_from_authority(
        host_values[0],
        require_port=False,
        default_port=80,
    )
    return _ParsedRequest(
        method=method,
        target=target,
        version=version,
        host=host,
        port=port,
        origin_form=_origin_form_target(target),
        content_length=content_length,
    )


def _host_from_absolute_url(target: str) -> str:
    host, _port, _origin_form = _parts_from_absolute_url(target)
    return host


def _parts_from_absolute_url(target: str) -> tuple[str, int, str]:
    try:
        parsed = urlsplit(target)
        parsed.port
        hostname = parsed.hostname or ""
    except ValueError as exc:
        raise ValueError("malformed_absolute_url") from exc

    if parsed.scheme.lower() != "http" or not parsed.netloc:
        raise ValueError("malformed_absolute_url")
    if "@" in parsed.netloc or parsed.netloc.endswith(":") or parsed.fragment:
        raise ValueError("malformed_absolute_url")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return _normalize_nonempty_host(hostname), parsed.port or 80, path


def _host_from_connect_target(target: str) -> str:
    host, _port = _host_port_from_connect_target(target)
    return host


def _host_port_from_connect_target(target: str) -> tuple[str, int]:
    if "://" in target or any(char in target for char in "/?#"):
        raise ValueError("malformed_connect_target")
    return _host_port_from_authority(target, require_port=True)


def _host_from_authority(authority: str, *, require_port: bool) -> str:
    host, _port = _host_port_from_authority(
        authority,
        require_port=require_port,
        default_port=None if require_port else 80,
    )
    return host


def _host_port_from_authority(
    authority: str,
    *,
    require_port: bool,
    default_port: int | None = None,
) -> tuple[str, int]:
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
    if port is None:
        if default_port is None:
            raise ValueError("missing_port")
        port = default_port
    return _normalize_nonempty_host(hostname), port


def _host_values(lines: list[str]) -> list[str]:
    values: list[str] = []
    for line in lines:
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() == "host":
            values.append(value)
    return values


def _content_length(lines: list[str]) -> int:
    values: list[str] = []
    for line in lines:
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() == "content-length":
            values.append(value.strip())
    if not values:
        return 0
    if len(values) != 1:
        raise ValueError("invalid_content_length")
    try:
        length = int(values[0])
    except ValueError as exc:
        raise ValueError("invalid_content_length") from exc
    if length < 0:
        raise ValueError("invalid_content_length")
    return length


def _origin_form_target(target: str) -> str:
    if not target:
        raise ValueError("empty_request_target")
    if target == "*":
        return target
    if not target.startswith("/") or "://" in target:
        raise ValueError("malformed_request_target")
    return target


def _rewrite_http_header(request: _ParsedRequest, header: bytes) -> bytes:
    text = header.decode("iso-8859-1", errors="replace")
    lines = text.split("\r\n")
    header_lines = lines[1:-2]
    rewritten: list[str] = [
        f"{request.method} {request.origin_form} {request.version}",
    ]
    has_host = False
    has_connection = False
    for line in header_lines:
        name, separator, value = line.partition(":")
        if not separator:
            continue
        lowered = name.strip().lower()
        if lowered == "host":
            has_host = True
        if lowered == "connection":
            has_connection = True
        if lowered == "proxy-connection":
            continue
        rewritten.append(f"{name}:{value}")
    if not has_host:
        host_value = request.host if request.port == 80 else f"{request.host}:{request.port}"
        rewritten.append(f"Host: {host_value}")
    if not has_connection:
        rewritten.append("Connection: close")
    return ("\r\n".join(rewritten) + "\r\n\r\n").encode("iso-8859-1")


def _normalize_nonempty_host(host: str) -> str:
    normalized = normalize_domain(host)
    if not normalized:
        raise ValueError("empty_host")
    return normalized


def _identity_resolver(host: str, port: int) -> tuple[str, int]:
    return host, port


async def _tunnel(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    client_to_upstream = asyncio.create_task(_pipe(client_reader, upstream_writer))
    upstream_to_client = asyncio.create_task(_pipe(upstream_reader, client_writer))
    tasks = {client_to_upstream, upstream_to_client}
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.gather(*done, return_exceptions=True)


async def _pipe(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        while True:
            chunk = await reader.read(_CHUNK_SIZE)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    finally:
        writer.close()


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
