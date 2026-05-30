"""Control UI route factory — serves embedded HTML console with SPA fallback."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from opensquilla import __version__
from opensquilla.gateway.config import GatewayConfig

_STATIC_CACHE_CONTROL = "public, max-age=2592000"


class _CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that attaches Cache-Control to 200 responses."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 200 and not os.environ.get(
            "OPENSQUILLA_STATIC_NO_CACHE"
        ):
            response.headers.setdefault("Cache-Control", _STATIC_CACHE_CONTROL)
        return response


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_DIST_DIR = _STATIC_DIR / "dist"

_TEMPLATE_VERSION_SUFFIX = str(int(time.time()))

_jinja_env = None


def _get_jinja_env():
    global _jinja_env
    if _jinja_env is None:
        import jinja2

        _jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        _jinja_env.filters["tojson"] = lambda v, **kw: json.dumps(v)
    return _jinja_env


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


def _read_vite_assets(base_path: str) -> tuple[str, str]:
    """Read the Vite-generated index.html and extract the main JS/CSS assets.

    Returns (js_url, css_url) relative to the static directory.
    """
    dist_index = _DIST_DIR / "index.html"
    if not dist_index.exists():
        # Fallback: return empty strings; template will serve a degraded experience
        return ("", "")

    html = dist_index.read_text(encoding="utf-8")

    # Extract the main JS module
    js_match = re.search(r'<script type="module"[^>]*src="([^"]+)"', html)
    js_url = js_match.group(1) if js_match else ""
    # Prepend base path to relative URLs
    if js_url and js_url.startswith("./"):
        js_url = f"{base_path}/static/dist/{js_url[2:]}"

    # Extract the main CSS link
    css_match = re.search(r'<link rel="stylesheet"[^>]*href="([^"]+)"', html)
    css_url = css_match.group(1) if css_match else ""
    if css_url and css_url.startswith("./"):
        css_url = f"{base_path}/static/dist/{css_url[2:]}"

    return (js_url, css_url)


def create_control_ui_routes(config: GatewayConfig) -> list[Route | Mount]:
    """Create routes for the Control UI. Returns empty list if disabled."""
    if not config.control_ui.enabled:
        return []

    base = config.control_ui.base_path
    js_url, css_url = _read_vite_assets(base)
    template = _get_jinja_env().get_template("index.html")

    async def serve_index(request: Request) -> HTMLResponse:
        ctx = _build_bootstrap_context(config, request)
        ctx["vite_js_url"] = js_url
        ctx["vite_css_url"] = css_url
        html = template.render(**ctx)
        return HTMLResponse(html)

    routes: list[Route | Mount] = [
        Mount(
            f"{base}/static",
            app=_CachedStaticFiles(directory=str(_STATIC_DIR)),
            name="control_ui_static",
        ),
        Route(f"{base}/{{path:path}}", serve_index, methods=["GET"]),
        Route(f"{base}/", serve_index, methods=["GET"]),
    ]
    return routes
