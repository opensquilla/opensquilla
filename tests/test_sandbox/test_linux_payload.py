from __future__ import annotations

import json
from pathlib import Path

from opensquilla.sandbox.backend.linux_payload import (
    FilesystemHelperPayload,
    HelperPayload,
    ProcessHelperPayload,
    build_filesystem_helper_payload,
    build_process_helper_payload,
    decode_payload,
    encode_payload,
)
from opensquilla.sandbox.operation_runtime import SandboxOperation
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    ResourceLimits,
    SandboxPolicy,
    SandboxRequest,
    SecurityLevel,
)


def test_process_payload_round_trips() -> None:
    payload = HelperPayload(
        operation_type="process",
        action_kind="shell.exec",
        run_mode="trusted",
        session_id="s1",
        cwd="/workspace",
        env={"PATH": "/usr/bin"},
        policy={
            "network": "none",
            "mounts": [
                {"host": "/repo", "sandbox": "/workspace", "mode": "rw", "required": True}
            ],
            "envAllowlist": ["PATH"],
            "tmpWritable": True,
            "wallTimeoutS": 30.0,
        },
        process=ProcessHelperPayload(
            argv=["sh", "-lc", "echo ok"],
            stdin_base64="aGVsbG8=",
        ),
        filesystem=None,
    )

    encoded = encode_payload(payload)
    decoded = decode_payload(encoded)

    assert decoded == payload
    assert json.loads(encoded)["operationType"] == "process"
    assert json.loads(encoded)["process"]["stdinBase64"] == "aGVsbG8="


def test_filesystem_payload_round_trips() -> None:
    payload = HelperPayload(
        operation_type="filesystem",
        action_kind="fs.worker.write_text",
        run_mode="trusted",
        session_id="s1",
        cwd="/repo/.opensquilla-cache/fs-worker",
        env={"PATH": "/usr/bin", "PYTHONPATH": "/repo/src"},
        policy={
            "network": "none",
            "mounts": [
                {"host": "/repo", "sandbox": "/repo", "mode": "rw", "required": True}
            ],
            "envAllowlist": ["PATH", "PYTHONPATH"],
            "tmpWritable": True,
            "wallTimeoutS": 30.0,
        },
        process=None,
        filesystem=FilesystemHelperPayload(
            kind="write_text",
            worker_payload_path="/repo/.opensquilla-cache/fs-worker/payload.json",
            worker_payload={
                "kind": "write_text",
                "path": "/repo/out.txt",
                "content": "hello",
            },
        ),
    )

    decoded = decode_payload(encode_payload(payload))

    assert decoded.filesystem is not None
    assert decoded.filesystem.kind == "write_text"
    assert decoded.filesystem.worker_payload["content"] == "hello"


def test_decode_payload_rejects_unknown_operation_type() -> None:
    raw = json.dumps(
        {
            "operationType": "unknown",
            "actionKind": "x",
            "runMode": "trusted",
            "sessionId": "",
            "cwd": str(Path("/repo")),
            "env": {},
            "policy": {},
            "process": None,
            "filesystem": None,
        }
    )

    try:
        decode_payload(raw)
    except ValueError as exc:
        assert "unknown operationType" in str(exc)
    else:
        raise AssertionError("decode_payload should reject unknown operation type")


def _policy(tmp_path: Path) -> SandboxPolicy:
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=(
            MountSpec(
                host_path=tmp_path,
                sandbox_path=Path("/workspace"),
                mode="rw",
                required=True,
            ),
        ),
        workspace_rw=True,
        tmp_writable=True,
        limits=ResourceLimits(wall_timeout_s=30),
        env_allowlist=("PATH",),
        require_approval=False,
    )


def test_build_process_helper_payload_from_sandbox_request(tmp_path: Path) -> None:
    request = SandboxRequest(
        argv=("sh", "-lc", "echo ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env={"PATH": "/usr/bin"},
        session_id="s1",
        run_mode="trusted",
    )

    payload = build_process_helper_payload(request)

    assert payload.operation_type == "process"
    assert payload.cwd == str(tmp_path)
    assert payload.process is not None
    assert payload.process.argv == ["sh", "-lc", "echo ok"]
    assert payload.policy["network"] == "none"
    assert payload.policy["mounts"][0]["host"] == str(tmp_path)
    assert payload.policy["mounts"][0]["sandbox"] == tmp_path.as_posix()
    assert payload.policy["cpuSeconds"] == 30
    assert payload.policy["memoryMb"] == 1024
    assert payload.policy["pids"] == 256
    assert payload.policy["wallTimeoutS"] == 30


def test_build_process_helper_payload_filters_env_allowlist(tmp_path: Path) -> None:
    request = SandboxRequest(
        argv=("sh", "-lc", "echo ok"),
        cwd=tmp_path,
        action_kind="shell.exec",
        policy=_policy(tmp_path),
        env={"PATH": "/usr/bin", "AWS_SECRET_ACCESS_KEY": "secret"},
        session_id="s1",
        run_mode="trusted",
    )

    payload = build_process_helper_payload(request)

    assert payload.env == {"PATH": "/usr/bin"}


def test_build_filesystem_helper_payload_from_operation(tmp_path: Path) -> None:
    operation = SandboxOperation.filesystem(
        kind="write_text",
        workspace=tmp_path,
        run_mode="trusted",
        path=tmp_path / "out.txt",
        paths=(tmp_path / "out.txt",),
        content="hello",
    )

    payload = build_filesystem_helper_payload(
        operation,
        policy=_policy(tmp_path),
        session_id="s1",
        worker_payload_path=tmp_path / ".opensquilla-cache" / "fs-worker" / "payload.json",
    )

    assert payload.operation_type == "filesystem"
    assert payload.filesystem is not None
    assert payload.filesystem.worker_payload["kind"] == "write_text"
    assert payload.filesystem.worker_payload["content"] == "hello"
