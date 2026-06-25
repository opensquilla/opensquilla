"""Native Windows default sandbox backend adapter."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import uuid
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
    process_executable_rx_roots,
    runtime_rx_roots,
    windows_platform_rx_roots,
    windows_sensitive_marker,
    workspace_cache_root,
    workspace_write_roots,
)
from opensquilla.sandbox.backend.windows_default_setup import default_setup_marker_path
from opensquilla.sandbox.backend.windows_default_support import probe_windows_default_support
from opensquilla.sandbox.operation_runtime import (
    SANDBOX_FILESYSTEM_WRITE_KINDS,
    FilesystemOperationRequest,
    SandboxOperation,
    SandboxOperationDomain,
    SandboxOperationResult,
)
from opensquilla.sandbox.run_mode import normalize_run_mode
from opensquilla.sandbox.types import SandboxBackendError, SandboxRequest, SandboxResult

_HELPER_MODULE = "opensquilla.sandbox.backend.windows_default_runner"
_FILESYSTEM_WORKER_MODULE = "opensquilla.sandbox.filesystem_worker"
_OUTPUT_BYTE_CAP = 1_048_576
_HELPER_PAYLOAD_ENV = "OPENSQUILLA_WINDOWS_DEFAULT_PAYLOAD"
_HELPER_TIMEOUT_GRACE_S = 30.0
_WINDOWS_PROCESS_BASE_ENV_KEYS = (
    "SystemRoot",
    "WINDIR",
    "ComSpec",
)


class WindowsDefaultBackend(Backend):
    """Windows backend used by Standard-Sandbox and Trusted-Sandbox."""

    name = "windows_default"

    def available(self) -> bool:
        return _support_ready()

    def operation_domains_supported(self) -> frozenset[SandboxOperationDomain]:
        return frozenset({"filesystem"})

    async def run_operation(
        self,
        operation: SandboxOperation,
    ) -> SandboxOperationResult:
        if operation.domain != "filesystem":
            raise SandboxBackendError(
                f"windows_default backend does not implement {operation.domain} operations"
            )
        _filesystem_request(operation)
        if not _support_ready():
            raise SandboxBackendError(
                "windows_default backend unavailable: administrator setup or Windows "
                "support checks are not ready"
            )
        if operation.workspace is None:
            raise SandboxBackendError("filesystem operation is missing workspace")
        payload_path = _filesystem_operation_payload_path(operation.workspace)
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(
            json.dumps(operation.to_payload(), ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            request = _filesystem_operation_request(operation, payload_path)
            result = await self.run(request)
        finally:
            try:
                payload_path.unlink()
            except FileNotFoundError:
                pass
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "filesystem worker failed"
            raise SandboxBackendError(f"windows_default filesystem worker failed: {detail}")
        return SandboxOperationResult.from_worker_stdout(result.stdout)

    async def run(self, request: SandboxRequest) -> SandboxResult:
        if not _support_ready():
            raise SandboxBackendError(
                "windows_default backend unavailable: administrator setup or Windows "
                "support checks are not ready"
            )

        ensure_cache_dirs(request.cwd)
        payload = _payload_for_request(request)
        helper_env = dict(os.environ)
        helper_env[_HELPER_PAYLOAD_ENV] = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )
        helper_argv = (sys.executable, "-m", _HELPER_MODULE, "--payload-env")
        wall = request.policy.limits.wall_timeout_s
        helper_wall = _helper_supervision_timeout(wall)
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *helper_argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=helper_env,
            )
        except (FileNotFoundError, OSError) as exc:
            raise SandboxBackendError(f"windows_default helper launch failed: {exc}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=helper_wall,
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


def _helper_supervision_timeout(command_timeout_s: float) -> float:
    return max(0.01, float(command_timeout_s)) + _HELPER_TIMEOUT_GRACE_S


def _payload_for_request(request: SandboxRequest) -> dict[str, Any]:
    env = build_cache_env(request.cwd, base_env=_process_base_env(request))
    policy = request.policy.summary()
    policy["windowsAclPlan"] = _acl_plan_payload(request)
    network_boundary = _windows_network_boundary_payload(request)
    if network_boundary is not None:
        policy["windowsNetworkBoundary"] = network_boundary
    stdin_b64 = (
        base64.b64encode(request.stdin).decode("ascii")
        if request.stdin is not None
        else None
    )
    return {
        "backend": "windows_default",
        "argv": list(request.argv),
        "cwd": str(request.cwd),
        "env": env,
        "policy": policy,
        "runMode": request.run_mode,
        "timeout": request.policy.limits.wall_timeout_s,
        "stdinBase64": stdin_b64,
    }


def _windows_network_boundary_payload(request: SandboxRequest) -> dict[str, object] | None:
    if request.policy.network.value != "proxy_allowlist":
        return None
    if request.policy.network_proxy is None:
        return None
    from opensquilla.sandbox.backend.windows_default_setup import (
        default_setup_marker_path,
        read_setup_marker,
    )

    marker = read_setup_marker(default_setup_marker_path())
    if marker is None or marker.network is None:
        return None
    return marker.network.to_json()


def _filesystem_operation_payload_path(workspace: Path) -> Path:
    return workspace_cache_root(workspace) / "fs-worker" / f"{uuid.uuid4().hex}.json"


def _filesystem_operation_request(
    operation: SandboxOperation,
    payload_path: Path,
) -> SandboxRequest:
    if operation.workspace is None:
        raise SandboxBackendError("filesystem operation is missing workspace")
    worker_root = workspace_cache_root(operation.workspace) / "fs-worker"
    worker_root.mkdir(parents=True, exist_ok=True)
    _validate_filesystem_operation_targets(operation)
    policy = _filesystem_operation_policy(operation, worker_root, payload_path)
    env = {
        "PATH": str(_python_executable().parent),
        "PYTHONPATH": _pythonpath_for_worker(),
        **_worker_home_env(worker_root),
    }
    return SandboxRequest(
        argv=(
            str(_python_executable()),
            "-m",
            _FILESYSTEM_WORKER_MODULE,
            str(payload_path),
        ),
        cwd=worker_root,
        action_kind=f"fs.worker.{operation.kind}",
        policy=policy,
        env=env,
        reason="sandboxed filesystem side-effect worker",
        run_mode=normalize_run_mode(operation.run_mode).value,
    )


def _python_executable() -> Path:
    return Path(sys.executable)


def _capability_store_path() -> Path:
    return default_setup_marker_path().with_name("cap_sids.json")


def _filesystem_operation_policy(
    operation: SandboxOperation,
    worker_root: Path,
    payload_path: Path,
):
    from opensquilla.sandbox.types import (
        MountSpec,
        NetworkMode,
        ResourceLimits,
        SandboxPolicy,
        SecurityLevel,
    )

    target_mounts = [
        MountSpec(
            host_path=root,
            sandbox_path=root,
            mode="rw" if operation.kind in SANDBOX_FILESYSTEM_WRITE_KINDS else "ro",
            required=True,
        )
        for root in _filesystem_operation_target_roots(operation)
    ]
    runtime_mounts = [
        MountSpec(
            host_path=root,
            sandbox_path=root,
            mode="ro",
            required=True,
        )
        for root in _runtime_readonly_roots()
    ]
    payload_mount = MountSpec(
        host_path=payload_path.parent,
        sandbox_path=payload_path.parent,
        mode="rw",
        required=True,
    )
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=tuple(dict.fromkeys((*target_mounts, *runtime_mounts, payload_mount))),
        workspace_rw=False,
        tmp_writable=True,
        limits=ResourceLimits(cpu_seconds=30, memory_mb=1024, pids=64, wall_timeout_s=30),
        env_allowlist=(
            "PATH",
            "PYTHONPATH",
            "SystemRoot",
            "WINDIR",
            "ComSpec",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
        ),
        require_approval=False,
        description=f"Windows filesystem worker policy for {operation.kind}",
    )


def _worker_home_env(worker_root: Path) -> dict[str, str]:
    home = str(worker_root)
    raw_drive = worker_root.drive
    drive = raw_drive or "C:"
    homepath = home[len(raw_drive) :] if raw_drive else home
    if not homepath.startswith(("\\", "/")):
        homepath = "\\" + homepath
    return {
        "HOME": home,
        "USERPROFILE": home,
        "HOMEDRIVE": drive,
        "HOMEPATH": homepath,
        "TEMP": home,
        "TMP": home,
    }


def _filesystem_operation_target_roots(operation: SandboxOperation) -> tuple[Path, ...]:
    request = _filesystem_request(operation)
    roots: list[Path] = []
    for path in request.paths:
        root = path.parent if operation.kind in SANDBOX_FILESYSTEM_WRITE_KINDS else path
        roots.append(_nearest_existing_acl_root(root))
    return tuple(dict.fromkeys(roots))


def _nearest_existing_acl_root(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def _validate_filesystem_operation_targets(operation: SandboxOperation) -> None:
    if operation.kind not in SANDBOX_FILESYSTEM_WRITE_KINDS:
        return
    request = _filesystem_request(operation)
    readonly_roots = _runtime_readonly_roots()
    for path in request.paths:
        for root in readonly_roots:
            if _is_relative_to_casefold(path, root):
                raise SandboxBackendError(
                    f"windows_default denied read-only runtime filesystem target: {path}"
                )


def _filesystem_request(operation: SandboxOperation) -> FilesystemOperationRequest:
    if not isinstance(operation.request, FilesystemOperationRequest):
        raise SandboxBackendError("filesystem operation is missing filesystem request")
    return operation.request


def _runtime_readonly_roots() -> tuple[Path, ...]:
    roots = [
        *runtime_rx_roots(_python_executable()),
        *_opensquilla_import_roots(),
    ]
    return tuple(dict.fromkeys(root for root in roots if root))


def _opensquilla_import_roots() -> tuple[Path, ...]:
    import opensquilla

    package_root = Path(opensquilla.__file__).resolve().parent
    roots = [package_root]
    if package_root.parent.name.lower() == "src":
        roots.append(package_root.parent)
    return tuple(roots)


def _pythonpath_for_worker() -> str:
    roots = _opensquilla_import_roots()
    if not roots:
        return ""
    return str(roots[-1] if roots[-1].name.lower() == "src" else roots[0].parent)


def _is_relative_to_casefold(candidate: Path, root: Path) -> bool:
    c = str(candidate).replace("\\", "/").rstrip("/").lower()
    r = str(root).replace("\\", "/").rstrip("/").lower()
    return c == r or c.startswith(r + "/")


def _acl_plan_payload(request: SandboxRequest) -> dict[str, object]:
    write_roots = workspace_write_roots(request.cwd)
    process_rx_roots = tuple(
        root for root in process_executable_rx_roots(request.argv, request.env) if root.exists()
    )
    runtime_acl_roots = tuple(
        root
        for root in runtime_rx_roots(_python_executable())
        if _rx_root_needs_acl_grant(root, request.env)
    )
    process_acl_roots = tuple(
        root for root in process_rx_roots if _rx_root_needs_acl_grant(root, request.env)
    )
    required: list[AclGrant] = [
        *(AclGrant(root, AclAccess.RWX, AclGrantKind.REQUIRED) for root in write_roots.rwx_roots),
        *(
            AclGrant(root, AclAccess.RX, AclGrantKind.REQUIRED)
            for root in _workspace_traversal_roots(request.cwd)
        ),
        *(AclGrant(root, AclAccess.RX, AclGrantKind.REQUIRED) for root in runtime_acl_roots),
        *(AclGrant(root, AclAccess.RX, AclGrantKind.REQUIRED) for root in process_acl_roots),
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
        expansion=_expansion_grants_from_env(request),
        sensitive_marker=_acl_sensitive_marker,
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


def _rx_root_needs_acl_grant(path: Path, env: dict[str, str]) -> bool:
    return not any(
        _is_relative_to_casefold(path, root) for root in windows_platform_rx_roots(env)
    )


def _workspace_traversal_roots(cwd: Path) -> tuple[Path, ...]:
    parent = cwd.parent
    if parent.name.lower() != ".opensquilla":
        return ()
    return (parent,)


def _acl_sensitive_marker(path: Path) -> str | None:
    return windows_sensitive_marker(path)


def _expansion_grants_from_env(request: SandboxRequest) -> tuple[AclGrant, ...]:
    raw = request.env.get("OPENSQUILLA_WINDOWS_SANDBOX_EXPANSION_ROOTS", "")
    roots = [item.strip() for item in raw.split(";") if item.strip()]
    return tuple(
        AclGrant(Path(root), AclAccess.RWX, AclGrantKind.EXPANSION)
        for root in roots
    )


def _allowed_env(request: SandboxRequest) -> dict[str, str]:
    return {
        key: value
        for key in request.policy.env_allowlist
        if isinstance((value := request.env.get(key)), str)
    }


def _process_base_env(request: SandboxRequest) -> dict[str, str]:
    env = _allowed_env(request)
    for key in _WINDOWS_PROCESS_BASE_ENV_KEYS:
        value = request.env.get(key) or os.environ.get(key)
        if isinstance(value, str) and value:
            env[key] = value
    return env


def _decode_capped(raw: bytes | None) -> tuple[str, bool]:
    if not raw:
        return "", False
    if len(raw) <= _OUTPUT_BYTE_CAP:
        return raw.decode("utf-8", errors="replace"), False
    return raw[:_OUTPUT_BYTE_CAP].decode("utf-8", errors="replace"), True


__all__ = ["WindowsDefaultBackend"]
