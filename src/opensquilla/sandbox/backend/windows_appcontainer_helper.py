"""Fail-closed Windows AppContainer helper.

The adapter invokes this module in a separate interpreter. The helper owns the
Windows-only boundary: AppContainer profile/capability setup, token creation,
job-object lifetime, and child process creation. Until filesystem and network
restrictions are robust enough to enforce the full sandbox policy, the helper
validates input and exits non-zero instead of launching the requested command.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_UNENFORCEABLE = "windows_appcontainer helper cannot enforce AppContainer policy yet"


@dataclass(frozen=True)
class _HelperPayload:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    policy: dict[str, Any]
    timeout: float


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not sys.platform.startswith("win"):
            raise SystemExit("windows_appcontainer helper only runs on native Windows")
        payload = _parse_payload(args)
        _validate_policy_shape(payload.policy)
        _run_appcontainer(payload)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(1) from None
        raise


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

    timeout = raw.get("timeout")
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise SystemExit("invalid windows_appcontainer payload: timeout must be positive")

    return _HelperPayload(
        argv=tuple(argv),
        cwd=cwd,
        env=dict(env_raw),
        policy=policy,
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


def _run_appcontainer(payload: _HelperPayload) -> None:
    """Structured skeleton for the future Win32 AppContainer boundary."""
    handles = _create_appcontainer_profile_and_job(payload.policy)
    _create_process_in_appcontainer(payload, handles)


@dataclass(frozen=True)
class _Win32AppContainerHandles:
    profile_sid: int
    job: int


def _create_appcontainer_profile_and_job(
    policy: dict[str, Any],
) -> _Win32AppContainerHandles:
    """Create future AppContainer profile state and a kill-on-close job object.

    This is deliberately not called while policy enforcement is incomplete.
    It documents the concrete Win32 libraries and constants the final helper
    will use without risking an unsandboxed child process.
    """
    _ = policy
    if not sys.platform.startswith("win"):
        raise SystemExit("windows_appcontainer helper only runs on native Windows")
    raise SystemExit(_UNENFORCEABLE)


def _create_process_in_appcontainer(
    payload: _HelperPayload,
    handles: _Win32AppContainerHandles,
) -> None:
    """Future CreateProcess boundary with AppContainer attributes."""
    _ = (payload, handles, os.environ)
    raise SystemExit(_UNENFORCEABLE)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["main"]
