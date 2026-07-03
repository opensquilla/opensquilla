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

    Source maps (.map) are excluded from long-term caching since they are
    only used for debugging and should not be aggressively cached.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 200 and not os.environ.get(
            "OPENSQUILLA_STATIC_NO_CACHE"
        ):
            # Skip cache-control for source maps — debug files should not be
            # cached aggressively (or served in production at all).
            if not path.endswith(".map"):
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


_SUPPORTED_LOCALES = ("en", "zh-Hans", "ja", "fr", "de", "es")


def _locale_from_tag(tag: str) -> str | None:
    """Map a single BCP-47 Accept-Language tag to a supported locale, else None."""
    t = tag.strip().lower()
    if not t:
        return None
    if t.startswith("zh"):
        return "zh-Hans"
    for code in ("ja", "fr", "de", "es", "en"):
        if t == code or t.startswith(code + "-"):
            return code
    return None


def _resolve_locale(config: GatewayConfig, request: Request) -> str:
    """Resolve the first-paint locale rendered into <html lang> and #opensquilla-data.

    Honors the configured default. Only when that default is the baseline 'en'
    do we sniff Accept-Language (the first supported tag wins), so an operator
    who explicitly pins a default is never overridden. The browser's saved
    localStorage choice and the in-app switcher always win client-side.
    """
    default = getattr(config.control_ui, "default_locale", "en")
    if default in _SUPPORTED_LOCALES and default != "en":
        return default
    accept = request.headers.get("accept-language", "") or ""
    for part in accept.split(","):
        code = _locale_from_tag(part.split(";", 1)[0])
        if code:
            return code
    return "en"


def _update_payload(config: GatewayConfig) -> dict | None:
    """Cached update-availability info for the bootstrap context.

    Read-only and non-blocking: the actual GitHub check runs in a background
    thread (see start_background_update_check). Returns a small dict only when a
    newer release is known, so the front end can treat "presence" as "show the
    notice"; returns None otherwise.
    """
    try:
        from opensquilla.observability.update_check import get_cached_update_info

        info = get_cached_update_info(config=config, version=__version__)
    except Exception:  # pragma: no cover - defensive, never break page render
        return None
    if info is None or not info.update_available:
        return None
    return info.to_public_dict()


def _build_bootstrap_context(config: GatewayConfig, request: Request) -> dict:
    """Build the template context for bootstrap config injection."""
    return {
        "version": f"{__version__}+{_TEMPLATE_VERSION_SUFFIX}",
        "ws_url": _request_ws_url(request, config),
        "auth_mode": config.auth.mode,
        "base_path": config.control_ui.base_path,
        "config_path": config.config_path or "",
        "locale": _resolve_locale(config, request),
        "update": _update_payload(config),
        "features": {
            "diagnostics": config.diagnostics_enabled,
        },
    }


def _vite_asset_url(raw_url: str, base_path: str) -> str:
    """Normalize a Vite asset URL to the configured Control UI base path."""
    if not raw_url:
        return ""
    if raw_url.startswith(("http://", "https://", "//")):
        return raw_url

    base = base_path.rstrip("/") or ""
    asset_prefix = f"{base}/static/dist/"
    if raw_url.startswith(asset_prefix):
        return raw_url

    marker = "/static/dist/"
    if raw_url.startswith("/") and marker in raw_url:
        return f"{asset_prefix}{raw_url.split(marker, 1)[1]}"
    if raw_url.startswith("./"):
        return f"{asset_prefix}{raw_url[2:]}"
    if raw_url.startswith("assets/"):
        return f"{asset_prefix}{raw_url}"
    return raw_url


def _read_vite_assets(base_path: str) -> tuple[str, list[str]]:
    """Read the Vite-generated index.html and extract the main JS module and
    every entry stylesheet.

    Returns (js_url, css_urls) relative to the static directory. Vite emits more
    than one entry stylesheet (e.g. a shared Icon chunk plus the main bundle),
    and their order in index.html is not stable — extracting only the first
    drops the main bundle and renders the page unstyled, so all of them must be
    injected.
    """
    dist_index = _DIST_DIR / "index.html"
    if not dist_index.exists():
        # Fallback: return empty assets; template serves a degraded experience.
        return ("", [])

    html = dist_index.read_text(encoding="utf-8")

    # Extract the main JS module
    js_match = re.search(r'<script type="module"[^>]*src="([^"]+)"', html)
    js_url = _vite_asset_url(js_match.group(1) if js_match else "", base_path)

    # Extract every stylesheet link, preserving document (cascade) order.
    css_urls = [
        _vite_asset_url(href, base_path)
        for href in re.findall(r'<link rel="stylesheet"[^>]*href="([^"]+)"', html)
    ]

    return (js_url, css_urls)


def create_control_ui_routes(config: GatewayConfig) -> list[Route | Mount]:
    """Create routes for the Control UI. Returns empty list if disabled."""
    if not config.control_ui.enabled:
        return []

    base = config.control_ui.base_path
    frontend = config.control_ui.frontend
    template_name = "legacy_index.html" if frontend == "legacy" else "index.html"
    template = _get_jinja_env().get_template(template_name)

    async def serve_index(request: Request) -> HTMLResponse:
        ctx = _build_bootstrap_context(config, request)
        if frontend == "vue":
            # Re-read latest Vite assets on every request so rebuilds are picked up
            # without restarting the gateway.
            live_js, live_css_urls = _read_vite_assets(base)
            ctx["vite_js_url"] = live_js
            ctx["vite_css_urls"] = live_css_urls
            # Back-compat single URL (first) for any consumer expecting one.
            ctx["vite_css_url"] = live_css_urls[0] if live_css_urls else ""
        html = template.render(**ctx)
        response = HTMLResponse(html)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

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
