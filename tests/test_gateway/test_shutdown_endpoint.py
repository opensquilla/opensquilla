"""The owner-only graceful shutdown endpoint (POST /api/system/shutdown).

This is the cross-platform shutdown path the CLI and desktop use where POSIX
signals can't drain — notably Windows, which has no real SIGTERM. The endpoint
must (1) reject non-owner (non-loopback) callers, (2) report 503 when no run
loop is attached to drive the drain, and (3) invoke the run loop's shutdown
trigger and return 202 for a loopback-proven owner.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from opensquilla.gateway.app import create_gateway_app
from opensquilla.gateway.config import GatewayConfig

# A loopback peer on a loopback-bound, no-auth gateway is the proven owner;
# a non-loopback peer is not (see gateway.auth.OpenScopeResolver).
_OWNER_PEER = ("127.0.0.1", 51000)
_REMOTE_PEER = ("203.0.113.7", 51000)


def _app(trigger=None):
    app = create_gateway_app(GatewayConfig())
    if trigger is not None:
        app.state.request_shutdown = trigger
    return app


def test_shutdown_endpoint_triggers_drain_for_owner() -> None:
    calls: list[str] = []
    app = _app(trigger=calls.append)

    with TestClient(app, client=_OWNER_PEER) as client:
        response = client.post("/api/system/shutdown")

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "accepted"}
    # The run loop's trigger is invoked with the close() reason.
    assert calls == ["api_shutdown"]


def test_shutdown_endpoint_rejects_non_owner() -> None:
    calls: list[str] = []
    app = _app(trigger=calls.append)

    with TestClient(app, client=_REMOTE_PEER) as client:
        response = client.post("/api/system/shutdown")

    assert response.status_code == 403, response.text
    # A rejected caller must never reach the shutdown trigger.
    assert calls == []


def test_shutdown_endpoint_unavailable_without_run_loop() -> None:
    # No request_shutdown attached (app built without a server, as in embedded
    # run=False use): the owner gets a clean 503, not a 500.
    app = _app(trigger=None)

    with TestClient(app, client=_OWNER_PEER) as client:
        response = client.post("/api/system/shutdown")

    assert response.status_code == 503, response.text


def test_shutdown_endpoint_rejects_get() -> None:
    app = _app(trigger=lambda _reason: None)

    with TestClient(app, client=_OWNER_PEER) as client:
        response = client.get("/api/system/shutdown")

    assert response.status_code == 405, response.text
