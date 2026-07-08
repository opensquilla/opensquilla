"""Gateway catch-alls must log tracebacks server-side, not just return str(exc)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.testclient import TestClient

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.middleware import ErrorHandlingMiddleware
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc.registry import RpcRegistry


@pytest.fixture(autouse=True)
def _default_structlog_config() -> Iterator[None]:
    """Pin structlog to its default stdout renderer for deterministic capture.

    Another test in the same process may have routed structlog through the
    stdlib bridge (or left a custom configuration behind); reset to defaults
    so error events render to ``sys.stdout`` where ``capsys`` observes them,
    then restore the prior configuration state.
    """
    was_configured = structlog.is_configured()
    old_config = structlog.get_config()
    structlog.reset_defaults()
    try:
        yield
    finally:
        if was_configured:
            structlog.configure(**old_config)
        else:
            structlog.reset_defaults()


async def test_dispatch_catchall_logs_traceback(capsys) -> None:
    registry = RpcRegistry()

    async def _boom(params, ctx):
        raise RuntimeError("synthetic dispatch explosion")

    registry.register("test.boom", _boom, "operator.read")
    ctx = RpcContext(conn_id="test", config=GatewayConfig())

    response = await registry.dispatch("req-1", "test.boom", {}, ctx)

    # Client-visible frame is unchanged: same INTERNAL_ERROR shape as before.
    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "INTERNAL_ERROR"
    assert response.error.message == "synthetic dispatch explosion"

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "rpc.dispatch_failed" in combined
    assert "synthetic dispatch explosion" in combined
    assert "Traceback" in combined


def test_http_catchall_logs_traceback(capsys) -> None:
    async def _boom(request):
        raise RuntimeError("synthetic http explosion")

    app = Starlette(
        routes=[Route("/boom", _boom)],
        middleware=[Middleware(ErrorHandlingMiddleware)],
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    # Client-visible response is unchanged: same JSON error body as before.
    assert response.status_code == 500
    assert response.json() == {"error": "synthetic http explosion", "code": "INTERNAL_ERROR"}

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "http.request_failed" in combined
    assert "synthetic http explosion" in combined
    assert "Traceback" in combined
