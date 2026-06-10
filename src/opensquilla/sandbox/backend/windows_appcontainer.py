"""Native Windows AppContainer sandbox adapter.

This module is intentionally only an adapter. It never launches the requested
command directly; it delegates all Windows-specific process-boundary work to
``windows_appcontainer_helper`` in a fresh Python interpreter and fails closed
when that helper cannot enforce the requested policy.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.backend.windows_primitives import prepare_appcontainer_identity
from opensquilla.sandbox.backend.windows_support import probe_windows_sandbox_support
from opensquilla.sandbox.types import SandboxBackendError, SandboxRequest, SandboxResult

_HELPER_MODULE = "opensquilla.sandbox.backend.windows_appcontainer_helper"
_OUTPUT_BYTE_CAP = 1_048_576


class WindowsAppContainerBackend(Backend):
    """Windows AppContainer backend wrapper."""

    name = "windows_appcontainer"

    def available(self) -> bool:
        return probe_windows_sandbox_support().appcontainer_available

    async def run(self, request: SandboxRequest) -> SandboxResult:
        if not self.available():
            raise SandboxBackendError(
                "windows_appcontainer backend unavailable: requires native Windows "
                "plus an enforced AppContainer process boundary"
            )

        session_id = str(getattr(request, "session_id", "") or "default")
        identity = prepare_appcontainer_identity(session_id)
        payload = _payload_for_request(request, session_id=session_id, identity=identity)
        helper_argv = (
            sys.executable,
            "-m",
            _HELPER_MODULE,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )
        wall = request.policy.limits.wall_timeout_s
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *helper_argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SandboxBackendError(
                f"windows AppContainer helper launch failed: {exc}"
            ) from exc
        except OSError as exc:
            raise SandboxBackendError(
                f"windows AppContainer helper launch failed: {exc}"
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=wall,
            )
        except TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except ProcessLookupError:
                pass
            elapsed = time.monotonic() - started
            return SandboxResult(
                returncode=124,
                stdout="",
                stderr="windows_appcontainer helper timed out",
                wall_time_s=elapsed,
                backend_used=self.name,
                policy_used=request.policy.summary(),
                timed_out=True,
            )

        elapsed = time.monotonic() - started
        stdout, trunc_out = _decode_capped(stdout_bytes)
        stderr, trunc_err = _decode_capped(stderr_bytes)
        return SandboxResult(
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            wall_time_s=elapsed,
            backend_used=self.name,
            policy_used=request.policy.summary(),
            truncated_stdout=trunc_out,
            truncated_stderr=trunc_err,
            timed_out=False,
        )


def _payload_for_request(
    request: SandboxRequest,
    *,
    session_id: str | None = None,
    identity: Any | None = None,
) -> dict[str, Any]:
    return {
        "argv": list(request.argv),
        "cwd": str(request.cwd),
        "env": _allowed_env(request),
        "policy": request.policy.summary(),
        "session_id": session_id or str(getattr(request, "session_id", "") or "default"),
        "appcontainer_profile_name": str(getattr(identity, "profile_name", "") or ""),
        "appcontainer_sid": str(getattr(identity, "appcontainer_sid", "") or ""),
        "timeout": request.policy.limits.wall_timeout_s,
    }


def _allowed_env(request: SandboxRequest) -> dict[str, str]:
    if sys.platform.startswith("win"):
        source: dict[str, tuple[str, str]] = {}
        for key, value in request.env.items():
            if isinstance(value, str):
                source.setdefault(key.casefold(), (key, value))

        filtered: dict[str, str] = {}
        seen: set[str] = set()
        for allowed_key in request.policy.env_allowlist:
            folded = allowed_key.casefold()
            if folded in seen:
                continue
            if folded in source:
                key, value = source[folded]
                filtered[key] = value
                seen.add(folded)
        return filtered

    return {
        key: value
        for key in request.policy.env_allowlist
        if isinstance((value := request.env.get(key)), str)
    }


def _decode_capped(raw: bytes | None) -> tuple[str, bool]:
    if not raw:
        return "", False
    if len(raw) <= _OUTPUT_BYTE_CAP:
        return raw.decode("utf-8", errors="replace"), False
    return raw[:_OUTPUT_BYTE_CAP].decode("utf-8", errors="replace"), True


__all__ = ["WindowsAppContainerBackend"]
