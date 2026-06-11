"""Native Windows default sandbox backend adapter."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.backend.windows_default_acl import (
    AclAccess,
    AclGrant,
    AclGrantKind,
    plan_acl_refresh,
)
from opensquilla.sandbox.backend.windows_default_cache import build_cache_env, ensure_cache_dirs
from opensquilla.sandbox.backend.windows_default_capability import capability_sids_for_command
from opensquilla.sandbox.backend.windows_default_roots import (
    runtime_rx_roots,
    windows_sensitive_marker,
    workspace_write_roots,
)
from opensquilla.sandbox.backend.windows_default_setup import default_setup_marker_path
from opensquilla.sandbox.backend.windows_default_support import probe_windows_default_support
from opensquilla.sandbox.run_mode import normalize_run_mode
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
    policy = request.policy.summary()
    policy["windowsAclPlan"] = _acl_plan_payload(request)
    return {
        "backend": "windows_default",
        "argv": list(request.argv),
        "cwd": str(request.cwd),
        "env": env,
        "policy": policy,
        "runMode": request.run_mode,
        "timeout": request.policy.limits.wall_timeout_s,
    }


def _python_executable() -> Path:
    return Path(sys.executable)


def _capability_store_path() -> Path:
    return default_setup_marker_path().with_name("cap_sids.json")


def _acl_plan_payload(request: SandboxRequest) -> dict[str, object]:
    write_roots = workspace_write_roots(request.cwd)
    required: list[AclGrant] = [
        *(AclGrant(root, AclAccess.RWX, AclGrantKind.REQUIRED) for root in write_roots.rwx_roots),
        *(
            AclGrant(root, AclAccess.RX, AclGrantKind.REQUIRED)
            for root in runtime_rx_roots(_python_executable())
        ),
    ]
    policy_grants = [
        AclGrant(
            mount.host_path,
            AclAccess.RWX if mount.mode == "rw" else AclAccess.RX,
            AclGrantKind.POLICY,
        )
        for mount in request.policy.mounts
    ]
    plan = plan_acl_refresh(
        run_mode=normalize_run_mode(request.run_mode),
        required=required,
        policy=policy_grants,
        expansion=(),
        sensitive_marker=lambda path: windows_sensitive_marker(path),
    )
    if plan.denied:
        denied = plan.denied[0]
        raise SandboxBackendError(
            f"windows_default denied sensitive ACL grant for {denied.grant.path}: "
            f"{denied.reason}"
        )
    if plan.approval_required:
        grant = plan.approval_required[0]
        raise SandboxBackendError(
            f"windows_default ACL approval is required before granting {grant.path}"
        )

    roots = tuple(grant.path for grant in plan.auto_grants)
    sids = capability_sids_for_command(_capability_store_path(), roots)
    sid_by_root = {str(root): sid for root, sid in zip(roots, sids, strict=False)}
    grants: list[dict[str, str]] = []
    for grant in plan.auto_grants:
        grants.append(
            {
                "path": str(grant.path),
                "access": grant.access.value,
                "kind": grant.kind.value,
                "capabilitySid": sid_by_root[str(grant.path)],
            }
        )
    return {
        "autoGrants": grants,
        "approvalRequired": [],
        "denied": [],
        "capabilitySids": list(dict.fromkeys(item["capabilitySid"] for item in grants)),
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
