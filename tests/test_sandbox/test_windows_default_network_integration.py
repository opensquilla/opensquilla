from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

import pytest

WINDOWS_ADMIN_NETWORK = pytest.mark.skipif(
    not sys.platform.startswith("win")
    or os.environ.get("OPENSQUILLA_RUN_WINDOWS_NETWORK_INTEGRATION") != "1",
    reason="requires Windows admin setup and OPENSQUILLA_RUN_WINDOWS_NETWORK_INTEGRATION=1",
)


def _proxy_port_from_marker() -> int:
    from opensquilla.sandbox.backend.windows_default_setup import (
        default_setup_marker_path,
        read_setup_marker,
    )

    marker = read_setup_marker(default_setup_marker_path())
    if marker is None or marker.network is None or not marker.network.allowed_proxy_ports:
        pytest.fail("Windows network setup marker is missing allowed proxy ports")
    return marker.network.allowed_proxy_ports[0]


def _policy(tmp_path: Path):
    from opensquilla.sandbox.types import (
        NetworkMode,
        NetworkProxySpec,
        ResourceLimits,
        SandboxPolicy,
        SecurityLevel,
    )

    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.PROXY_ALLOWLIST,
        mounts=(),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=10),
        env_allowlist=("PATH", "SystemRoot", "COMSPEC", "TEMP", "TMP"),
        require_approval=False,
        network_proxy=NetworkProxySpec(host="127.0.0.1", port=_proxy_port_from_marker()),
    )


async def _run_python(tmp_path: Path, code: str):
    from opensquilla.sandbox.backend.windows_default import WindowsDefaultBackend
    from opensquilla.sandbox.types import SandboxRequest

    _ = tmp_path
    request = SandboxRequest(
        argv=(sys.executable, "-c", code),
        cwd=Path.cwd(),
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        run_mode="trusted",
    )
    return await WindowsDefaultBackend().run(request)


@WINDOWS_ADMIN_NETWORK
@pytest.mark.asyncio
async def test_sandbox_blocks_direct_public_connect(tmp_path: Path) -> None:
    result = await _run_python(
        tmp_path,
        "import socket; socket.create_connection(('93.184.216.34', 80), timeout=2)",
    )

    assert result.returncode != 0


@WINDOWS_ADMIN_NETWORK
@pytest.mark.asyncio
async def test_sandbox_blocks_direct_dns_connect(tmp_path: Path) -> None:
    result = await _run_python(
        tmp_path,
        "\n".join(
            (
                "import socket",
                "try:",
                "    socket.create_connection(('8.8.8.8', 53), timeout=2)",
                "    print('UNEXPECTED_SUCCESS')",
                "except Exception as exc:",
                "    print(type(exc).__name__ + ': ' + str(exc))",
            )
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert "UNEXPECTED_SUCCESS" not in result.stdout


@WINDOWS_ADMIN_NETWORK
@pytest.mark.asyncio
async def test_sandbox_blocks_loopback_non_proxy_port(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2.0)
        port = listener.getsockname()[1]
        accepted: list[bytes] = []

        def accept_once() -> None:
            try:
                conn, _addr = listener.accept()
            except (OSError, TimeoutError):
                return
            with conn:
                accepted.append(conn.recv(16))

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        result = await _run_python(
            tmp_path,
            "\n".join(
                (
                    "import socket",
                    "try:",
                    f"    s = socket.create_connection(('127.0.0.1', {port}), timeout=2)",
                    "    s.sendall(b'host-listener-ok')",
                    "    s.close()",
                    "    print('UNEXPECTED_SUCCESS')",
                    "except Exception as exc:",
                    "    print(type(exc).__name__ + ': ' + str(exc))",
                )
            ),
        )
        thread.join(timeout=3.0)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert "UNEXPECTED_SUCCESS" not in result.stdout
    assert accepted == []


@WINDOWS_ADMIN_NETWORK
def test_full_host_access_socket_is_not_modified_by_boundary() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        accepted: list[bytes] = []

        def accept_once() -> None:
            conn, _addr = listener.accept()
            with conn:
                accepted.append(conn.recv(16))

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as client:
            client.sendall(b"ok")
        thread.join(timeout=2.0)

    assert accepted == [b"ok"]
