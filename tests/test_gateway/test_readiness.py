from __future__ import annotations

from starlette.testclient import TestClient

from opensquilla.gateway.app import create_gateway_app
from opensquilla.gateway.config import GatewayConfig


def test_ready_endpoint_reports_starting_until_gateway_marks_ready() -> None:
    app = create_gateway_app(GatewayConfig())
    app.state.gateway_ready = False

    with TestClient(app) as client:
        starting = client.get("/ready")
        assert starting.status_code == 503
        assert starting.json()["ready"] is False

        app.state.gateway_ready = True
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["ready"] is True
