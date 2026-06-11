"""Native Windows default sandbox backend adapter."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.backend.windows_default_cache import build_cache_env, ensure_cache_dirs
from opensquilla.sandbox.backend.windows_default_support import probe_windows_default_support
from opensquilla.sandbox.types import SandboxBackendError, SandboxRequest, SandboxResult

_HELPER_MODULE = "opensquilla.sandbox.backend.windows_default_runner"
_OUTPUT_BYTE_CAP = 1_048_576


class WindowsDefaultBackend(Backend):
    """Windows backend used by Standard-Sandbox and Trusted-Sandbox."""

    name = "windows_default"

    def available(self) -> bool:
        return _support_ready()

    async def run(self, request: SandboxRequest) -> SandboxResult:
        if not _support_ready():
            raise SandboxBackendError(
                "windows_default backend unavailable: administrator setup or Windows "
                "support checks are not ready"
            )

        ensure_cache_dirs(request.cwd)
        payload = _payload_for_request(request)
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
        except (FileNotFoundError, OSError) as exc:
            raise SandboxBackendError(f"windows_default helper launch failed: {exc}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=wall)
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
                stderr="windows_default helper timed out",
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


def _support_ready() -> bool:
    return probe_windows_default_support().default_backend_available


def _payload_for_request(request: SandboxRequest) -> dict[str, Any]:
    env = build_cache_env(request.cwd, base_env=_allowed_env(request))
    return {
        "backend": "windows_default",
        "argv": list(request.argv),
        "cwd": str(request.cwd),
        "env": env,
        "policy": request.policy.summary(),
        "runMode": request.run_mode,
        "timeout": request.policy.limits.wall_timeout_s,
    }


def _allowed_env(request: SandboxRequest) -> dict[str, str]:
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


__all__ = ["WindowsDefaultBackend"]
