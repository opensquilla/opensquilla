"""Pin the Control UI Content-Security-Policy.

The chat surface previews artifacts (notably generated images) by fetching the
authenticated bytes and rendering an object URL (``blob:``) in an ``<img>``.
If ``img-src`` omits ``blob:`` the browser blocks every generated-image
preview while the file still downloads fine — a "the UI lied" failure. These
tests keep ``blob:`` in the policy and keep the header scoped to the Control UI
path prefix.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from opensquilla.gateway.middleware import SecurityHeadersMiddleware


def _client(path_prefix: str = "/control") -> TestClient:
    async def ok(_request):  # type: ignore[no-untyped-def]
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/control/ping", ok),
            Route("/other", ok),
        ]
    )
    app.add_middleware(SecurityHeadersMiddleware, path_prefix=path_prefix)
    return TestClient(app)


def test_csp_allows_blob_images_for_artifact_previews() -> None:
    response = _client().get("/control/ping")

    assert response.status_code == 200
    csp = response.headers.get("content-security-policy", "")
    assert "img-src 'self' data: blob:;" in csp, csp


def test_csp_still_constrains_default_and_connect_sources() -> None:
    csp = _client().get("/control/ping").headers.get("content-security-policy", "")

    # blob: is added only to img-src; the rest of the policy stays locked down.
    assert "default-src 'self';" in csp, csp
    assert "connect-src 'self' ws: wss:;" in csp, csp
    assert "blob:" not in csp.split("img-src", 1)[0], csp


def test_security_headers_scoped_to_control_prefix() -> None:
    response = _client().get("/other")

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
    assert "x-frame-options" not in response.headers
