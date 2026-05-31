"""Control UI route factory — serves embedded HTML console with SPA fallback."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import jinja2
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from opensquilla import __version__
from opensquilla.gateway.config import GatewayConfig

# Conservative max-age for static assets. 30 days is long enough that hot
# clients save roundtrips but short enough that any deploy without a version
# bump still becomes visible within a release cycle. Templates already append
# ?v={{ version }} to every asset URL so cache invalidation on actual code
# change is immediate — this header only saves repeat hits for unchanged
# bytes within the 30-day window.
#
# Skip when OPENSQUILLA_STATIC_NO_CACHE is set (debugging / forced refresh).
# Skip on non-200 responses so 206 Range and 304 conditional reuse stay
# untouched.
_STATIC_CACHE_CONTROL = "public, max-age=2592000"


class _CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that attaches Cache-Control to 200 responses.

    Subclassing rather than middleware-wrapping keeps the path scoped to the
    /static mount only. Range (206) and conditional-GET (304) flows pass
    through unchanged so browsers' Last-Modified / ETag logic continues
    working.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 200 and not os.environ.get(
            "OPENSQUILLA_STATIC_NO_CACHE"
        ):
            response.headers.setdefault("Cache-Control", _STATIC_CACHE_CONTROL)
        return response

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

# Process-start timestamp baked into the template-only version string so every
# gateway restart busts the browser cache for static JS/CSS. config.version
# itself is preserved for protocol/RPC consumers that expect a stable string.
_TEMPLATE_VERSION_SUFFIX = str(int(time.time()))

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)
# Register tojson filter used in index.html template
_jinja_env.filters["tojson"] = lambda v, **kw: json.dumps(v)


def _request_ws_url(request: Request, config: GatewayConfig) -> str:
    """Build the browser-facing websocket URL from the current request."""
    host = request.headers.get("host") or f"{config.host}:{config.port}"
    if config.host in {"0.0.0.0", "::"} and host == "testserver":
        host = f"127.0.0.1:{config.port}"
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    ws_scheme = "wss" if scheme == "https" else "ws"
    return f"{ws_scheme}://{host}/ws"


def _build_bootstrap_context(config: GatewayConfig, request: Request) -> dict:
    """Build the template context for bootstrap config injection."""
    return {
        "version": f"{__version__}+{_TEMPLATE_VERSION_SUFFIX}",
        "ws_url": _request_ws_url(request, config),
        "auth_mode": config.auth.mode,
        "base_path": config.control_ui.base_path,
        "config_path": config.config_path or "",
        "features": {
            "diagnostics": config.diagnostics_enabled,
        },
    }


def create_control_ui_routes(config: GatewayConfig) -> list[Route | Mount]:
    """Create routes for the Control UI. Returns empty list if disabled."""
    if not config.control_ui.enabled:
        return []

    base = config.control_ui.base_path
    template = _jinja_env.get_template("index.html")

    async def serve_index(request: Request) -> HTMLResponse:
        ctx = _build_bootstrap_context(config, request)
        html = template.render(**ctx)
        return HTMLResponse(html)

    return [
        Mount(
            f"{base}/static",
            app=_CachedStaticFiles(directory=str(_STATIC_DIR)),
            name="control_ui_static",
        ),
        Route(f"{base}/{{path:path}}", serve_index, methods=["GET"]),
        Route(f"{base}/", serve_index, methods=["GET"]),
    ]
