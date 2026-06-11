"""Windows default sandbox runner helper."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HelperPayload:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    policy: dict[str, Any]
    run_mode: str
    timeout: float


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not sys.platform.startswith("win"):
            raise SystemExit("windows_default runner only runs on native Windows")
        payload = _parse_payload(args)
        _validate_policy_is_enforceable(payload.policy)
        raise SystemExit(_run_windows_default(payload))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(1) from None
        raise


def _parse_payload(args: Sequence[str]) -> HelperPayload:
    if len(args) != 1:
        raise SystemExit("windows_default runner expects one JSON payload argument")
    try:
        raw = json.loads(args[0])
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid windows_default payload JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit("invalid windows_default payload: expected object")
    if raw.get("backend") != "windows_default":
        raise SystemExit("invalid windows_default payload: expected backend windows_default")

    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise SystemExit("invalid windows_default payload: argv must be a string list")

    cwd_raw = raw.get("cwd")
    if not isinstance(cwd_raw, str) or not cwd_raw:
        raise SystemExit("invalid windows_default payload: cwd is required")
    cwd = Path(cwd_raw)
    if not cwd.exists() or not cwd.is_dir():
        raise SystemExit(f"invalid windows_default cwd: {cwd}")

    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env_raw.items()
    ):
        raise SystemExit("invalid windows_default payload: env must be string map")

    policy = raw.get("policy")
    if not isinstance(policy, dict):
        raise SystemExit("invalid windows_default payload: policy is required")

    run_mode = raw.get("runMode")
    if run_mode not in {"standard", "trusted"}:
        raise SystemExit("invalid windows_default payload: runMode must be standard or trusted")

    timeout = raw.get("timeout")
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise SystemExit("invalid windows_default payload: timeout must be positive")

    return HelperPayload(
        argv=tuple(argv),
        cwd=cwd,
        env=dict(env_raw),
        policy=policy,
        run_mode=str(run_mode),
        timeout=float(timeout),
    )


def _validate_policy_is_enforceable(policy: dict[str, Any]) -> None:
    network = policy.get("network")
    if network not in {"none", "host", "proxy_allowlist"}:
        raise SystemExit(f"windows_default runner received unknown network mode: {network!r}")
    if network == "proxy_allowlist":
        raise SystemExit("Windows network boundary is pending for windows_default phase 1")


def _run_windows_default(payload: HelperPayload) -> int:
    return _run_windows_default_native(payload)


def _run_windows_default_native(payload: HelperPayload) -> int:
    raise SystemExit("windows_default native runner is unavailable in this build")


if __name__ == "__main__":
    main()
