"""Owner-gated HTTP route serving the diagnostics bundle zip.

Deliberately an HTTP route rather than an RPC method: the RPC transport is
WebSocket JSON and cannot stream zip bytes. Auth posture matches an
admin-scoped RPC — AuthMiddleware enforces the gateway token in token mode
(the path is outside the control-UI prefix), and the handler additionally
requires an owner principal so open-mode remote peers are rejected.
"""

from __future__ import annotations

import asyncio
import math
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import structlog
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from opensquilla.gateway.config import GatewayConfig

log = structlog.get_logger(__name__)

_DEFAULT_DAYS = 3
_MIN_DAYS = 1
_MAX_DAYS = 30


def _extract_http_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    token_header = request.headers.get("x-opensquilla-token")
    if token_header:
        return token_header
    return request.query_params.get("token")


def _request_principal_is_owner(config: GatewayConfig, request: Request) -> bool:
    from opensquilla.gateway.auth import resolve_auth

    auth_params: dict[str, str] = {}
    token = _extract_http_token(request)
    if token:
        auth_params["token"] = token
    peer_ip = request.client.host if request.client is not None else None
    principal = resolve_auth(config, auth_params, "operator", peer_ip=peer_ip)
    return bool(principal and principal.is_owner)


_DEFAULT_SCHEME_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    return _DEFAULT_SCHEME_PORTS.get(scheme)


def _request_origin_allowed(request: Request) -> bool:
    """Reject browser requests whose Origin is not the gateway itself.

    A hostile web page can make a loopback victim's browser POST here (the
    permissive default CORS policy would even let it read the zip), so the
    owner check alone is not enough. Browsers always attach ``Origin`` to
    cross-origin fetches; the gateway-served Web UI is same-origin so its
    ``Origin`` matches the request's own host. Requests without an ``Origin``
    header (curl, the desktop node client) are not browser-mediated and pass.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    request_url = request.url
    if not parsed.scheme or parsed.hostname is None or request_url.hostname is None:
        return False  # includes the opaque "null" origin
    return (
        parsed.scheme == request_url.scheme
        and parsed.hostname == request_url.hostname
        and _effective_port(parsed.scheme, parsed.port)
        == _effective_port(request_url.scheme, request_url.port)
    )


def _clamped_days(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return _DEFAULT_DAYS
    if isinstance(value, float) and not math.isfinite(value):
        return _DEFAULT_DAYS
    return max(_MIN_DAYS, min(int(value), _MAX_DAYS))


def register_bundle_routes(app: Starlette, *, config: GatewayConfig) -> None:
    """Register POST /api/v1/diagnostics/bundle on the given Starlette app."""

    async def bundle_handler(request: Request) -> FileResponse | JSONResponse:
        if not _request_origin_allowed(request):
            return JSONResponse(
                {"error": "cross-origin requests are not allowed", "code": "FORBIDDEN_ORIGIN"},
                status_code=403,
            )
        if not _request_principal_is_owner(config, request):
            return JSONResponse(
                {"error": "Owner privileges required", "code": "OWNER_REQUIRED"},
                status_code=403,
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        include_content = body.get("include_content") is True
        days = _clamped_days(body.get("days", _DEFAULT_DAYS))

        # Imported at call time so the gateway app boots without pulling in
        # the collector, and tests can monkeypatch the module attribute.
        from opensquilla.observability import bundle as bundle_module

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        tmp_dir = Path(tempfile.mkdtemp(prefix="opensquilla-bundle-"))
        dest = tmp_dir / f"opensquilla-bundle-{stamp}.zip"

        def _cleanup() -> None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        try:
            await asyncio.to_thread(
                bundle_module.collect_bundle,
                dest,
                days=days,
                include_content=include_content,
            )
        except Exception as exc:
            # Full traceback goes to the server log only — never the response.
            log.error("bundle_route.generation_failed", error=str(exc), exc_info=True)
            _cleanup()
            return JSONResponse(
                {"error": "Bundle generation failed", "code": "INTERNAL_ERROR"},
                status_code=500,
            )

        return FileResponse(
            os.fspath(dest),
            media_type="application/zip",
            filename=dest.name,
            background=BackgroundTask(_cleanup),
        )

    app.router.routes.append(
        Route("/api/v1/diagnostics/bundle", bundle_handler, methods=["POST"])
    )
