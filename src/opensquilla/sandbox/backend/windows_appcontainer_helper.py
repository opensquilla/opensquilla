"""Windows AppContainer helper.

The adapter invokes this module in a separate interpreter. The helper owns the
Windows-only boundary: AppContainer profile setup, filesystem ACL grants, token
creation, job-object lifetime, and child process creation. The helper requires
AppContainer process enforcement for every launch and additionally requires the
proxy allowlist boundary for proxy-networked policies.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensquilla.sandbox.backend.windows_acl import grant_path_to_appcontainer
from opensquilla.sandbox.backend.windows_primitives import (
    appcontainer_profile_name,
    ensure_appcontainer_profile,
    launch_appcontainer_process,
)
from opensquilla.sandbox.backend.windows_support import (
    APPCONTAINER_ENFORCED_ENV,
    PROXY_ALLOWLIST_ENFORCED_ENV,
    probe_windows_sandbox_support,
)
from opensquilla.sandbox.types import SandboxBackendError

_UNENFORCEABLE = "windows_appcontainer helper cannot enforce AppContainer policy yet"


@dataclass(frozen=True)
class _HelperPayload:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    policy: dict[str, Any]
    session_id: str
    appcontainer_profile_name: str | None
    appcontainer_sid: str | None
    timeout: float


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not sys.platform.startswith("win"):
            raise SystemExit("windows_appcontainer helper only runs on native Windows")
        payload = _parse_payload(args)
        _validate_policy_shape(payload.policy)
        _require_declared_enforcement(payload.policy)
        _run_appcontainer(payload)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(1) from None
        raise
    except SandboxBackendError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


def _parse_payload(args: Sequence[str]) -> _HelperPayload:
    if len(args) != 1:
        raise SystemExit("windows_appcontainer helper expects one JSON payload argument")
    try:
        raw = json.loads(args[0])
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid windows_appcontainer payload JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit("invalid windows_appcontainer payload: expected object")

    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise SystemExit("invalid windows_appcontainer payload: argv must be a string list")

    cwd_raw = raw.get("cwd")
    if not isinstance(cwd_raw, str) or not cwd_raw:
        raise SystemExit("invalid windows_appcontainer payload: cwd is required")
    cwd = Path(cwd_raw)
    if not cwd.exists() or not cwd.is_dir():
        raise SystemExit(f"invalid windows_appcontainer cwd: {cwd}")

    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in env_raw.items()
    ):
        raise SystemExit("invalid windows_appcontainer payload: env must be string map")

    policy = raw.get("policy")
    if not isinstance(policy, dict):
        raise SystemExit("invalid windows_appcontainer payload: policy is required")

    session_id = raw.get("session_id", "default")
    if not isinstance(session_id, str) or not session_id:
        raise SystemExit(
            "invalid windows_appcontainer payload: session_id must be a non-empty string"
        )

    profile_name = raw.get("appcontainer_profile_name")
    if profile_name is not None and (not isinstance(profile_name, str) or not profile_name):
        raise SystemExit(
            "invalid windows_appcontainer payload: appcontainer_profile_name "
            "must be a non-empty string"
        )

    appcontainer_sid = raw.get("appcontainer_sid")
    if appcontainer_sid is not None and (
        not isinstance(appcontainer_sid, str) or not appcontainer_sid
    ):
        raise SystemExit(
            "invalid windows_appcontainer payload: appcontainer_sid must be a non-empty string"
        )

    timeout = raw.get("timeout")
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise SystemExit("invalid windows_appcontainer payload: timeout must be positive")

    return _HelperPayload(
        argv=tuple(argv),
        cwd=cwd,
        env=dict(env_raw),
        policy=policy,
        session_id=session_id,
        appcontainer_profile_name=profile_name,
        appcontainer_sid=appcontainer_sid,
        timeout=float(timeout),
    )


def _validate_policy_shape(policy: dict[str, Any]) -> None:
    network = policy.get("network")
    if network not in {"none", "host", "proxy_allowlist"}:
        raise SystemExit(
            f"windows_appcontainer helper received unknown network mode: {network!r}"
        )
    if network == "proxy_allowlist":
        proxy = policy.get("network_proxy")
        if not isinstance(proxy, dict):
            raise SystemExit(
                "windows_appcontainer helper proxy_allowlist requires network_proxy"
            )
        if not isinstance(proxy.get("host"), str) or not isinstance(proxy.get("port"), int):
            raise SystemExit(
                "windows_appcontainer helper proxy_allowlist requires network_proxy "
                "with host and port"
            )

    mounts = policy.get("mounts")
    if not isinstance(mounts, list):
        raise SystemExit("invalid windows_appcontainer policy: mounts must be a list")
    for mount in mounts:
        if not isinstance(mount, dict):
            raise SystemExit("invalid windows_appcontainer policy: mount must be an object")
        if not all(isinstance(mount.get(key), str) for key in ("host", "sandbox", "mode")):
            raise SystemExit(
                "invalid windows_appcontainer policy: mount host, sandbox, and mode "
                "are required"
            )


def _require_declared_enforcement(policy: dict[str, Any]) -> None:
    support = probe_windows_sandbox_support()
    if not support.is_windows or not support.ctypes_available or not support.appcontainer_enforced:
        missing = []
        if not support.ctypes_available:
            missing.append("ctypes")
        if not support.appcontainer_enforced:
            missing.append(APPCONTAINER_ENFORCED_ENV)
        suffix = f" (missing {', '.join(missing)})" if missing else ""
        raise SystemExit(f"{_UNENFORCEABLE}{suffix}")
    if policy.get("network") == "proxy_allowlist" and not support.proxy_allowlist_enforced:
        missing = []
        if not support.proxy_allowlist_enforced:
            missing.append(PROXY_ALLOWLIST_ENFORCED_ENV)
        suffix = f" (missing {', '.join(missing)})" if missing else ""
        raise SystemExit(f"{_UNENFORCEABLE}{suffix}")


def _run_appcontainer(payload: _HelperPayload) -> None:
    profile_name = payload.appcontainer_profile_name or appcontainer_profile_name(
        payload.session_id
    )
    appcontainer_sid = payload.appcontainer_sid or ensure_appcontainer_profile(profile_name)
    asyncio.run(_grant_policy_paths(payload, appcontainer_sid))
    result = asyncio.run(
        launch_appcontainer_process(
            profile_name=profile_name,
            argv=payload.argv,
            cwd=payload.cwd,
            env=payload.env,
            timeout=payload.timeout,
        )
    )
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    raise SystemExit(result.returncode)


async def _grant_policy_paths(
    payload: _HelperPayload,
    appcontainer_sid: str,
) -> None:
    for mount in payload.policy["mounts"]:
        host = Path(mount["host"])
        mode = mount["mode"]
        if mode not in {"rw", "ro"}:
            raise SystemExit(
                f"invalid windows_appcontainer policy: unknown mount mode {mode!r}"
            )
        if mode == "rw":
            _prepare_missing_file_mount(host)
        await grant_path_to_appcontainer(host, appcontainer_sid, mode=mode)


def _prepare_missing_file_mount(path: Path) -> None:
    if path.exists() or not path.suffix or not path.parent.exists():
        return
    path.touch(exist_ok=True)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["main"]
