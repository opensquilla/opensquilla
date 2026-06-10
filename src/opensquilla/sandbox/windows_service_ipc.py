"""Windows sandbox broker IPC state and helpers."""

from __future__ import annotations

import json
import os
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensquilla.paths import state_dir as default_state_dir

DEFAULT_PIPE_NAME = r"\\.\pipe\opensquilla-sandbox-service"
STATE_FILENAME = "windows-sandbox-service.json"


@dataclass(frozen=True)
class BrokerConnectionState:
    pipe_name: str
    authkey_hex: str
    state_file: Path
    ipc_kind: str = "tcp"
    broker_host: str = "127.0.0.1"
    broker_port: int | None = None
    pid: int | None = None
    python_executable: str | None = None

    @property
    def authkey(self) -> bytes:
        return bytes.fromhex(self.authkey_hex)

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ipc_kind": self.ipc_kind,
            "pipe_name": self.pipe_name,
            "authkey_hex": self.authkey_hex,
        }
        if self.ipc_kind == "tcp":
            payload["broker_host"] = self.broker_host
            payload["broker_port"] = self.broker_port
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.python_executable:
            payload["python_executable"] = self.python_executable
        return payload


def service_state_dir(config: Any | None = None) -> Path:
    config_state_dir = getattr(config, "state_dir", None)
    if isinstance(config_state_dir, str) and config_state_dir.strip():
        return Path(config_state_dir).expanduser() / "sandbox" / "windows"
    return default_state_dir("sandbox", "windows")


def broker_state_path(base_dir: str | Path | None = None) -> Path:
    if base_dir is None:
        return service_state_dir() / STATE_FILENAME
    return Path(base_dir) / STATE_FILENAME


def new_broker_state(
    *,
    pipe_name: str = DEFAULT_PIPE_NAME,
    base_dir: str | Path | None = None,
    python_executable: str | None = None,
    ipc_kind: str = "tcp",
    broker_host: str = "127.0.0.1",
    broker_port: int | None = None,
) -> BrokerConnectionState:
    if ipc_kind not in {"tcp", "pipe"}:
        raise ValueError("ipc_kind must be tcp or pipe")
    if ipc_kind == "tcp" and broker_port is None:
        broker_port = _reserve_loopback_port(broker_host)
    return BrokerConnectionState(
        pipe_name=pipe_name,
        authkey_hex=secrets.token_hex(32),
        state_file=broker_state_path(base_dir),
        ipc_kind=ipc_kind,
        broker_host=broker_host,
        broker_port=broker_port,
        python_executable=python_executable,
    )


def read_broker_state(path: str | Path) -> BrokerConnectionState | None:
    state_file = Path(path)
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None

    ipc_kind = str(data.get("ipc_kind") or "").strip().lower()
    if not ipc_kind:
        ipc_kind = "tcp" if data.get("broker_port") is not None else "pipe"
    pipe_name = str(data.get("pipe_name") or DEFAULT_PIPE_NAME).strip()
    authkey_hex = str(data.get("authkey_hex") or "").strip()
    if ipc_kind not in {"tcp", "pipe"} or not pipe_name or not authkey_hex:
        return None
    try:
        bytes.fromhex(authkey_hex)
    except ValueError:
        return None
    pid_value = data.get("pid")
    try:
        pid = int(pid_value) if pid_value is not None else None
    except (TypeError, ValueError):
        pid = None
    broker_host = str(data.get("broker_host") or "127.0.0.1").strip()
    try:
        broker_port = int(data["broker_port"]) if data.get("broker_port") is not None else None
    except (TypeError, ValueError):
        return None
    if ipc_kind == "tcp" and not _valid_loopback_endpoint(broker_host, broker_port):
        return None
    python_executable = data.get("python_executable")
    return BrokerConnectionState(
        pipe_name=pipe_name,
        authkey_hex=authkey_hex,
        state_file=state_file,
        ipc_kind=ipc_kind,
        broker_host=broker_host,
        broker_port=broker_port,
        pid=pid,
        python_executable=str(python_executable) if python_executable else None,
    )


def write_broker_state(state: BrokerConnectionState) -> None:
    state.state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state.state_file.with_suffix(state.state_file.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(state.to_json(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp_path, state.state_file)


def request_sync(
    state: BrokerConnectionState,
    payload: dict[str, object],
) -> dict[str, object]:
    from multiprocessing.connection import Client

    if state.ipc_kind == "tcp":
        if not _valid_loopback_endpoint(state.broker_host, state.broker_port):
            raise ConnectionError("Windows sandbox broker TCP endpoint is invalid")
        address = (state.broker_host, int(state.broker_port))
        conn = Client(address, family="AF_INET", authkey=state.authkey)
    else:
        conn = Client(state.pipe_name, family="AF_PIPE", authkey=state.authkey)
    try:
        conn.send(payload)
        response = conn.recv()
    finally:
        conn.close()
    if not isinstance(response, dict):
        raise RuntimeError("Windows sandbox broker returned a non-object response")
    if response.get("status") == "error":
        message = str(response.get("message") or "Windows sandbox broker request failed")
        raise RuntimeError(message)
    return response


def _reserve_loopback_port(host: str) -> int:
    if host != "127.0.0.1":
        raise ValueError("Windows sandbox broker IPC must bind to 127.0.0.1")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _valid_loopback_endpoint(host: str, port: int | None) -> bool:
    return host == "127.0.0.1" and port is not None and 1 <= int(port) <= 65535


def broker_ready(state_file: str | Path | None = None) -> bool:
    path = Path(state_file) if state_file is not None else broker_state_path()
    state = read_broker_state(path)
    if state is None:
        return False
    try:
        response = request_sync(state, {"op": "health"})
    except Exception:
        return False
    return response.get("status") == "ok"


__all__ = [
    "BrokerConnectionState",
    "DEFAULT_PIPE_NAME",
    "STATE_FILENAME",
    "broker_ready",
    "broker_state_path",
    "new_broker_state",
    "read_broker_state",
    "request_sync",
    "service_state_dir",
    "write_broker_state",
]
