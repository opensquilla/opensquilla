"""Regression: the gateway bind preflight must match uvicorn's real bind.

uvicorn/asyncio sets SO_REUSEADDR on POSIX, so it can bind a port still in
TIME_WAIT after a restart. The preflight probe must do the same or it reports a
false "already in use" when the operator restarts the gateway. It must still
report a truly-live listener as unavailable.
"""

from __future__ import annotations

import socket

import pytest

from opensquilla.cli.gateway_cmd import _gateway_bind_available


def test_bind_available_false_for_live_listener() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen()
    try:
        assert _gateway_bind_available("127.0.0.1", port) is False
    finally:
        srv.close()


@pytest.mark.skipif(not hasattr(socket, "SO_REUSEADDR"), reason="needs SO_REUSEADDR")
def test_bind_available_true_after_restart_timewait() -> None:
    # Force the port into TIME_WAIT with a real server-side active close, the
    # exact state a gateway restart leaves behind. A probe without SO_REUSEADDR
    # would report this as "in use"; uvicorn (and now the preflight) binds fine.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen()
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = srv.accept()
    conn.shutdown(socket.SHUT_RDWR)
    conn.close()
    client.close()
    srv.close()

    assert _gateway_bind_available("127.0.0.1", port) is True
