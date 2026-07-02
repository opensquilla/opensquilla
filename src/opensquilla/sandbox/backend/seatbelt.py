"""macOS Seatbelt backend.

Executes requests through ``sandbox-exec`` with a generated SBPL profile.
Seatbelt is not a Linux namespace equivalent: paths stay as host paths, there
is no PID/user namespace, and V1 intentionally supports only host network or
no network. The profile is still deny-by-default for filesystem and network
access, with explicit read/write allowances for the workspace, configured
mounts, system runtime paths, and a backend-owned temporary directory.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, cast

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.managed_proxy_env import managed_proxy_env
from opensquilla.sandbox.operation_runtime import (
    SANDBOX_FILESYSTEM_WRITE_KINDS,
    FilesystemOperationRequest,
    SandboxOperation,
    SandboxOperationDomain,
    SandboxOperationResult,
)
from opensquilla.sandbox.run_mode import normalize_run_mode
from opensquilla.sandbox.types import (
    MountSpec,
    NetworkMode,
    NetworkProxySpec,
    ResourceLimits,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SandboxResult,
    SecurityLevel,
)

log = logging.getLogger(__name__)

_SANDBOX_EXEC_NAME = "sandbox-exec"
_SANDBOX_EXEC_SYSTEM_PATH = Path("/usr/bin/sandbox-exec")
_FILESYSTEM_WORKER_MODULE = "opensquilla.sandbox.filesystem_worker"
_OUTPUT_BYTE_CAP = 1_048_576
_TERMINATE_GRACE_S = 2.0

# This mirrors Codex's macOS Seatbelt posture for workspace-write:
# deny by default, allow ordinary macOS runtime services, allow full-disk reads,
# and constrain writes to explicit writable roots.
_SEATBELT_BASE_POLICY = """(version 1)

; start with closed-by-default
(deny default)

; child processes inherit the policy of their parent
(allow process-exec)
(allow process-fork)
(allow signal (target same-sandbox))

; process-info
(allow process-info* (target same-sandbox))

(allow file-write-data
  (require-all
    (path "/dev/null")
    (vnode-type CHARACTER-DEVICE)))

; sysctls permitted.
(allow sysctl-read)

; IOKit and common macOS runtime services.
(allow iokit-open
  (iokit-registry-entry-class "RootDomainUserClient"))

(allow mach-lookup
  (global-name "com.apple.system.opendirectoryd.libinfo"))

; Needed for python multiprocessing on macOS for SemLock.
(allow ipc-posix-sem)

; Needed for PyTorch/libomp on macOS to register OpenMP runtimes.
(allow ipc-posix-shm-read-data
  ipc-posix-shm-write-create
  ipc-posix-shm-write-unlink
  (ipc-posix-name-regex #"^/__KMP_REGISTERED_LIB_[0-9]+$"))

(allow mach-lookup
  (global-name "com.apple.PowerManagement.control"))

; allow openpty()
(allow pseudo-tty)
(allow file-read* file-write* file-ioctl (literal "/dev/ptmx"))
(allow file-read* file-write*
  (require-all
    (regex #"^/dev/ttys[0-9]+")
    (extension "com.apple.sandbox.pty")))
(allow file-ioctl (regex #"^/dev/ttys[0-9]+"))

; allow readonly user preferences
(allow ipc-posix-shm-read* (ipc-posix-name-prefix "apple.cfprefs."))
(allow mach-lookup
  (global-name "com.apple.cfprefsd.daemon")
  (global-name "com.apple.cfprefsd.agent")
  (local-name "com.apple.cfprefsd.agent"))
(allow user-preference-read)
"""

_SEATBELT_NETWORK_POLICY = """; allow safe AF_SYSTEM sockets used for local platform services.
(allow system-socket
  (require-all
    (socket-domain AF_SYSTEM)
    (socket-protocol 2)))

(allow mach-lookup
  (global-name "com.apple.bsd.dirhelper")
  (global-name "com.apple.system.opendirectoryd.membership")
  (global-name "com.apple.SecurityServer")
  (global-name "com.apple.networkd")
  (global-name "com.apple.ocspd")
  (global-name "com.apple.trustd.agent")
  (global-name "com.apple.SystemConfiguration.DNSConfiguration")
  (global-name "com.apple.SystemConfiguration.configd"))

(allow sysctl-read
  (sysctl-name-regex #"^net.routetable"))
"""

_TMP_RW_PATHS: tuple[Path, ...] = (Path("/tmp"),)
_PROTECTED_SUBPATH_NAMES = (".git", ".codex", ".agents")
_SEATBELT_LOOPBACK_PROXY_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _sandbox_exec_binary(binary: str | None = None) -> str | None:
    if binary is not None:
        return shutil.which(binary)
    if _SANDBOX_EXEC_SYSTEM_PATH.exists():
        return str(_SANDBOX_EXEC_SYSTEM_PATH)
    return shutil.which(_SANDBOX_EXEC_NAME)


def _validate_mount_path(path: PurePath, *, kind: str) -> None:
    if not path.is_absolute():
        raise SandboxBackendError(f"{kind} path must be absolute: {path!r}")
    if any(part == ".." for part in path.parts):
        raise SandboxBackendError(f"{kind} path contains '..': {path!r}")


def _validate_request(request: SandboxRequest) -> None:
    if not request.argv:
        raise SandboxBackendError("seatbelt request argv must not be empty")
    _validate_mount_path(request.cwd, kind="cwd")
    if not request.cwd.exists():
        raise SandboxBackendError(f"cwd missing on host: {request.cwd!r}")
    for spec in request.policy.mounts:
        _validate_mount_path(spec.host_path, kind="host mount")
        _validate_mount_path(spec.sandbox_path, kind="sandbox mount")
        if spec.required and not spec.host_path.exists():
            raise SandboxBackendError(f"required mount missing on host: {spec.host_path!r}")


def _scheme_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _literal(path: Path) -> str:
    return f"(literal {_scheme_string(str(path))})"


def _subpath(path: Path) -> str:
    return f"(subpath {_scheme_string(str(path))})"


def _unique_existing(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        candidates = [path]
        try:
            resolved = path.resolve(strict=False)
        except OSError:
            resolved = path
        if resolved != path:
            candidates.append(resolved)
        for candidate in candidates:
            key = str(candidate)
            if key in seen or not candidate.exists():
                continue
            seen.add(key)
            result.append(candidate)
    return result


def seatbelt_env_for_policy(
    policy: SandboxPolicy,
    override_env: dict[str, str],
    *,
    tmp_dir: Path | None,
) -> dict[str, str]:
    allowlist = set(policy.env_allowlist)
    resolved: dict[str, str] = {}
    for key in policy.env_allowlist:
        value = os.environ.get(key)
        if value is not None:
            resolved[key] = value
    for key, value in override_env.items():
        if key not in allowlist:
            log.debug("sandbox.seatbelt_env_override_rejected: key=%s", key)
            continue
        resolved[key] = value
    if tmp_dir is not None:
        resolved["TMPDIR"] = str(tmp_dir)
        resolved.update(_tool_cache_env(tmp_dir))
    if policy.network == NetworkMode.PROXY_ALLOWLIST:
        if policy.network_proxy is None:
            raise SandboxBackendError(
                "NetworkMode.PROXY_ALLOWLIST requires a network proxy "
                "for the seatbelt backend"
            )
        resolved.update(
            managed_proxy_env(
                policy.network_proxy.host,
                policy.network_proxy.port,
            )
        )
    return resolved


_env_for_policy = seatbelt_env_for_policy


def _tool_cache_env(tmp_dir: Path) -> dict[str, str]:
    cache_root = tmp_dir / "cache"
    return {
        "XDG_CACHE_HOME": str(cache_root / "xdg"),
        "npm_config_cache": str(cache_root / "npm"),
        "NPM_CONFIG_CACHE": str(cache_root / "npm"),
        "PIP_CACHE_DIR": str(cache_root / "pip"),
        "UV_CACHE_DIR": str(cache_root / "uv"),
    }


def _regex_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _protected_metadata_regex(root: Path, name: str) -> str:
    root_text = str(root).rstrip("/")
    if not root_text:
        root_text = "/"
    escaped_root = re.escape(root_text)
    escaped_name = re.escape(name)
    if root_text == "/":
        return f"^/{escaped_name}(/.*)?$"
    return f"^{escaped_root}/{escaped_name}(/.*)?$"


def _write_rules(paths: Iterable[Path]) -> list[str]:
    rules: list[str] = []
    for root in _unique_existing(paths):
        if root.is_file():
            continue
        require_parts = [_subpath(root)]
        for name in _PROTECTED_SUBPATH_NAMES:
            regex = _regex_string(_protected_metadata_regex(root, name))
            require_parts.append(f'(require-not (regex #"{regex}"))')
        rules.append(f"(allow file-write* (require-all {' '.join(require_parts)}))")
    return rules


def _seatbelt_proxy_endpoint(proxy: NetworkProxySpec) -> str:
    host = proxy.host.strip().lower()
    if host not in _SEATBELT_LOOPBACK_PROXY_HOSTS:
        raise SandboxBackendError(
            "seatbelt proxy allowlist requires a loopback network_proxy host "
            f"(got {proxy.host!r})"
        )
    if not 1 <= proxy.port <= 65535:
        raise SandboxBackendError(
            f"seatbelt proxy allowlist requires a valid network_proxy port (got {proxy.port!r})"
        )
    return f"localhost:{proxy.port}"


def _network_proxy_rule(proxy: NetworkProxySpec) -> str:
    endpoint = _seatbelt_proxy_endpoint(proxy)
    return f"(allow network-outbound (remote ip {_scheme_string(endpoint)}))"


def _tmp_write_paths(tmp_dir: Path | None) -> list[Path]:
    paths: list[Path] = []
    if tmp_dir is not None:
        paths.append(tmp_dir)
    paths.extend(_TMP_RW_PATHS)
    env_tmp = os.environ.get("TMPDIR")
    if env_tmp:
        candidate = Path(env_tmp)
        if candidate.is_absolute():
            paths.append(candidate)
    return paths


def render_seatbelt_profile(
    request: SandboxRequest,
    *,
    tmp_dir: Path | None = None,
) -> str:
    """Render a deny-by-default SBPL profile for ``request``."""
    policy = request.policy
    if policy.network == NetworkMode.PROXY_ALLOWLIST:
        if policy.network_proxy is None:
            raise SandboxBackendError(
                "NetworkMode.PROXY_ALLOWLIST requires a network proxy "
                "for the seatbelt backend"
            )

    write_paths: list[Path] = []
    workspace = next(
        (m for m in policy.mounts if m.sandbox_path.as_posix() == "/workspace"),
        None,
    )
    if workspace is not None:
        if workspace.mode == "rw" or policy.workspace_rw:
            write_paths.append(workspace.host_path)

    for spec in policy.mounts:
        if spec is workspace:
            continue
        if not spec.host_path.exists():
            if spec.required:
                raise SandboxBackendError(
                    f"required mount missing on host: {spec.host_path!r}"
                )
            log.debug("sandbox.seatbelt_mount_skipped: %s (not present)", spec.host_path)
            continue
        if spec.mode == "rw":
            write_paths.append(spec.host_path)

    if policy.tmp_writable:
        write_paths.extend(_tmp_write_paths(tmp_dir))

    lines: list[str] = [
        _SEATBELT_BASE_POLICY.rstrip(),
        "; allow read-only file operations",
        "(allow file-read*)",
    ]
    if policy.network == NetworkMode.NONE:
        lines.append("(deny network*)")
    elif policy.network == NetworkMode.HOST:
        lines.append("(allow network-outbound)")
        lines.append("(allow network-inbound)")
        lines.append(_SEATBELT_NETWORK_POLICY.rstrip())
    elif policy.network == NetworkMode.PROXY_ALLOWLIST:
        if policy.network_proxy is None:  # pragma: no cover - guarded above
            raise SandboxBackendError(
                "NetworkMode.PROXY_ALLOWLIST requires a network proxy "
                "for the seatbelt backend"
            )
        lines.append(_network_proxy_rule(policy.network_proxy))
        lines.append(_SEATBELT_NETWORK_POLICY.rstrip())
    else:  # pragma: no cover - exhaustive guard for future enum values
        raise SandboxBackendError(f"unsupported seatbelt network mode: {policy.network!r}")

    lines.extend(_write_rules(write_paths))
    return "\n".join(lines) + "\n"


def _render_sbpl_skeleton(policy: SandboxPolicy) -> str:
    """Compatibility helper for existing tests.

    New code should call :func:`render_seatbelt_profile` with a full request so
    the renderer can include cwd, executable, and temporary-directory rules.
    """
    cwd = Path.cwd()
    return render_seatbelt_profile(
        SandboxRequest(
            argv=("sh", "-c", "true"),
            cwd=cwd,
            action_kind="seatbelt.profile",
            policy=policy,
        )
    )


def build_seatbelt_argv(
    request: SandboxRequest,
    profile_path: Path,
    *,
    binary: str | None = None,
) -> list[str]:
    resolved = _sandbox_exec_binary(binary)
    if resolved is None:
        label = binary or _SANDBOX_EXEC_NAME
        raise SandboxBackendError(f"seatbelt backend unavailable: missing {label!r} binary")
    _validate_mount_path(profile_path, kind="profile")
    return [resolved, "-f", str(profile_path), *request.argv]


def _filesystem_request(operation: SandboxOperation) -> FilesystemOperationRequest:
    if not isinstance(operation.request, FilesystemOperationRequest):
        raise SandboxBackendError("filesystem operation is missing filesystem request")
    return operation.request


def _filesystem_operation_payload_path(workspace: Path) -> Path:
    return workspace / ".opensquilla-cache" / "fs-worker" / f"{time.monotonic_ns()}.json"


def _filesystem_operation_request(
    operation: SandboxOperation,
    payload_path: Path,
) -> SandboxRequest:
    if operation.workspace is None:
        raise SandboxBackendError("filesystem operation is missing workspace")
    _filesystem_request(operation)
    worker_root = payload_path.parent
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


def _filesystem_operation_policy(
    operation: SandboxOperation,
    worker_root: Path,
    payload_path: Path,
) -> SandboxPolicy:
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
        MountSpec(host_path=root, sandbox_path=root, mode="ro", required=True)
        for root in _runtime_readonly_roots()
    ]
    worker_mount = MountSpec(
        host_path=worker_root,
        sandbox_path=worker_root,
        mode="rw",
        required=True,
    )
    payload_mount = MountSpec(
        host_path=payload_path.parent,
        sandbox_path=payload_path.parent,
        mode="rw",
        required=True,
    )
    return SandboxPolicy(
        level=SecurityLevel.STANDARD,
        network=NetworkMode.NONE,
        mounts=tuple(dict.fromkeys((*target_mounts, *runtime_mounts, worker_mount, payload_mount))),
        workspace_rw=False,
        tmp_writable=True,
        limits=ResourceLimits(cpu_seconds=30, memory_mb=1024, pids=64, wall_timeout_s=30),
        env_allowlist=(
            "PATH",
            "PYTHONPATH",
            "HOME",
            "TMP",
            "TEMP",
            "TMPDIR",
            "LANG",
            "LC_ALL",
        ),
        require_approval=False,
        description=f"macOS filesystem worker policy for {operation.kind}",
    )


def _filesystem_operation_target_roots(operation: SandboxOperation) -> tuple[Path, ...]:
    request = _filesystem_request(operation)
    roots: list[Path] = []
    for path in request.paths:
        root = path.parent if operation.kind in SANDBOX_FILESYSTEM_WRITE_KINDS else path
        roots.append(_nearest_existing_path(root))
    return tuple(dict.fromkeys(roots))


def _nearest_existing_path(path: Path) -> Path:
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
                    f"seatbelt denied read-only runtime filesystem target: {path}"
                )


def _runtime_readonly_roots() -> tuple[Path, ...]:
    return tuple(dict.fromkeys(root for root in _opensquilla_import_roots() if root))


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


def _python_executable() -> Path:
    return Path(sys.executable)


def _worker_home_env(worker_root: Path) -> dict[str, str]:
    home = str(worker_root)
    return {
        "HOME": home,
        "TMP": home,
        "TEMP": home,
    }


def _is_relative_to_casefold(candidate: Path, root: Path) -> bool:
    c = str(candidate).replace("\\", "/").rstrip("/").lower()
    r = str(root).replace("\\", "/").rstrip("/").lower()
    return c == r or c.startswith(r + "/")


class SeatbeltBackend(Backend):
    """macOS ``sandbox-exec`` backend."""

    name = "seatbelt"

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary

    def available(self) -> bool:
        if sys.platform != "darwin":
            return False
        return _sandbox_exec_binary(self._binary) is not None

    def operation_domains_supported(self) -> frozenset[SandboxOperationDomain]:
        return frozenset({"filesystem"})

    async def run_operation(
        self,
        operation: SandboxOperation,
    ) -> SandboxOperationResult:
        if operation.domain != "filesystem":
            raise SandboxBackendError(
                f"seatbelt backend does not implement {operation.domain} operations"
            )
        if operation.workspace is None:
            raise SandboxBackendError("filesystem operation is missing workspace")
        _filesystem_request(operation)
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
            with contextlib.suppress(FileNotFoundError):
                payload_path.unlink()
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "filesystem worker failed"
            raise SandboxBackendError(f"seatbelt filesystem worker failed: {detail}")
        return SandboxOperationResult.from_worker_stdout(result.stdout)

    async def run(self, request: SandboxRequest) -> SandboxResult:
        if not self.available():
            raise SandboxBackendError(
                "seatbelt backend unavailable: missing 'sandbox-exec' binary on macOS"
            )
        _validate_request(request)

        tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
        profile_path: Path | None = None
        try:
            tmp_dir: Path | None = None
            if request.policy.tmp_writable:
                tmp_ctx = tempfile.TemporaryDirectory(prefix="opensquilla-seatbelt-tmp-")
                tmp_dir = Path(tmp_ctx.name)

            profile = render_seatbelt_profile(request, tmp_dir=tmp_dir)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix="opensquilla-seatbelt-",
                suffix=".sb",
                delete=False,
            ) as profile_file:
                profile_file.write(profile)
                profile_file.flush()
                profile_path = Path(profile_file.name)

            argv = build_seatbelt_argv(request, profile_path, binary=self._binary)
            env = _env_for_policy(request.policy, request.env, tmp_dir=tmp_dir)

            log.info(
                "sandbox.seatbelt_spawn: action=%s level=%s network=%s argv_len=%d",
                request.action_kind,
                request.policy.level.label,
                request.policy.network.value,
                len(argv),
            )

            wall = request.policy.limits.wall_timeout_s
            started = time.monotonic()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE if request.stdin is not None else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(request.cwd),
                    env=env,
                    start_new_session=True,
                )
            except FileNotFoundError as exc:
                raise SandboxBackendError(f"seatbelt launch failed: {exc}") from exc
            except OSError as exc:
                raise SandboxBackendError(f"seatbelt launch failed: {exc}") from exc

            timed_out = False
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=request.stdin), timeout=wall
                )
            except TimeoutError:
                timed_out = True
                stdout_bytes, stderr_bytes = await _terminate_process_group(proc)

            elapsed = time.monotonic() - started
            stdout, trunc_out = _decode_capped(stdout_bytes)
            stderr, trunc_err = _decode_capped(stderr_bytes)
            returncode = proc.returncode if proc.returncode is not None else -1
            notes: tuple[_SeatbeltNote, ...] = ()
            if not timed_out:
                notes = _classify_denial(
                    request.argv,
                    stderr,
                    stdout=stdout,
                    network=request.policy.network,
                )
                if returncode == 0:
                    notes = tuple(note for note in notes if note.category == "network.denied")
                for note in notes:
                    log.info(
                        "sandbox.seatbelt_note: category=%s argv0=%s blocked_path=%s action=%s",
                        note.category,
                        Path(request.argv[0]).name if request.argv else "",
                        note.blocked_path,
                        request.action_kind,
                    )
            return SandboxResult(
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                wall_time_s=elapsed,
                backend_used=self.name,
                policy_used=request.policy.summary(),
                truncated_stdout=trunc_out,
                truncated_stderr=trunc_err,
                timed_out=timed_out,
                backend_notes=tuple(n.to_user_string() for n in notes),
            )
        finally:
            if profile_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(profile_path)
            if tmp_ctx is not None:
                tmp_ctx.cleanup()


def _decode_capped(raw: bytes | None) -> tuple[str, bool]:
    if not raw:
        return "", False
    if len(raw) <= _OUTPUT_BYTE_CAP:
        return raw.decode("utf-8", errors="replace"), False
    return raw[:_OUTPUT_BYTE_CAP].decode("utf-8", errors="replace"), True


async def _terminate_process_group(
    proc: asyncio.subprocess.Process,
) -> tuple[bytes, bytes]:
    pid = proc.pid
    os_mod = cast(Any, os)
    signal_mod = cast(Any, signal)
    try:
        os_mod.killpg(pid, signal_mod.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_S)
    except TimeoutError:
        try:
            os_mod.killpg(pid, signal_mod.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            await proc.wait()
        except ProcessLookupError:
            pass

    stdout = b""
    stderr = b""
    if proc.stdout is not None:
        try:
            stdout = await proc.stdout.read()
        except Exception:  # noqa: BLE001
            stdout = b""
    if proc.stderr is not None:
        try:
            stderr = await proc.stderr.read()
        except Exception:  # noqa: BLE001
            stderr = b""
    return stdout, stderr


# ─── Denial classifier ───────────────────────────────────────────────────


@dataclass(frozen=True)
class _SeatbeltNote:
    """One classified denial extracted from sandbox-exec stderr."""

    category: str
    hint: str
    blocked_path: Path | None = None

    def to_user_string(self) -> str:
        return f"{self.category}: {self.hint}"


_STDERR_SCAN_BYTES = 8192

_EXECVP_RE = re.compile(
    r"sandbox-exec:\s+execvp\(\)\s+of\s+'([^']+)'\s+failed:\s+Operation not permitted"
)
_DYLD_RE = re.compile(r"dyld(?:\[\d+\])?:\s*Library not loaded:\s*(\S+)")
_OPNOTPERM_RE = re.compile(
    r"(?:at\s+'([^']+)'[^\n]*\(Operation not permitted\))"
    r"|(/[^\s:]+):\s*Operation not permitted"
)
_TMP_RE = re.compile(r"\b(mkstemp|mkdtemp|tmpfile)\b.*(?:permitted|denied|failed)")
_PING_SENDTO_DENIED_RE = re.compile(
    r"\bping6?:\s+sendto:\s+Operation not permitted\b",
    re.IGNORECASE,
)
_PING_PACKET_LOSS_RE = re.compile(
    r"\b100(?:\.0+)?%\s+packet loss\b",
    re.IGNORECASE,
)
_PING_COMMAND_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s;&|]))(?:/[^\s;&|]*/)?ping6?(?=$|[\s;&|])"
)


def _looks_like_ping_invocation(argv: tuple[str, ...]) -> bool:
    return bool(_PING_COMMAND_RE.search(" ".join(argv)))


def _network_is_restricted(network: NetworkMode | None) -> bool:
    return network is not NetworkMode.HOST


def _classify_denial(
    argv: tuple[str, ...],
    stderr: str,
    *,
    stdout: str = "",
    network: NetworkMode | None = None,
) -> tuple[_SeatbeltNote, ...]:
    """Scan the tail of ``stderr`` for known Seatbelt denial signatures."""
    if not stderr and not stdout:
        return ()
    tail = stderr[-_STDERR_SCAN_BYTES:]
    stdout_tail = stdout[-_STDERR_SCAN_BYTES:]
    notes: list[_SeatbeltNote] = []
    seen: set[tuple[str, str]] = set()

    def _add(note: _SeatbeltNote) -> None:
        key = (note.category, str(note.blocked_path))
        if key in seen:
            return
        seen.add(key)
        notes.append(note)

    for match in _EXECVP_RE.finditer(tail):
        path = Path(match.group(1))
        _add(_SeatbeltNote(
            category="execve.denied",
            hint=f"sandbox blocked execve of {path}",
            blocked_path=path,
        ))

    for match in _DYLD_RE.finditer(tail):
        path = Path(match.group(1))
        _add(_SeatbeltNote(
            category="filesystem.read",
            hint=f"dyld could not load {path}",
            blocked_path=path,
        ))

    for match in _OPNOTPERM_RE.finditer(tail):
        raw_path = match.group(1) or match.group(2)
        if not raw_path:
            continue
        path = Path(raw_path)
        if any(n.blocked_path == path for n in notes):
            continue
        _add(_SeatbeltNote(
            category="filesystem.read",
            hint=f"sandbox blocked access to {path}",
            blocked_path=path,
        ))

    if _TMP_RE.search(tail):
        _add(_SeatbeltNote(category="tmp.denied", hint="sandbox denied a tmp-directory operation"))

    if _looks_like_ping_invocation(argv):
        if _PING_SENDTO_DENIED_RE.search(tail):
            _add(_SeatbeltNote(
                category="network.denied",
                hint="sandbox blocked raw ICMP ping traffic",
            ))
        elif _network_is_restricted(network) and _PING_PACKET_LOSS_RE.search(stdout_tail):
            _add(_SeatbeltNote(
                category="network.denied",
                hint="sandbox blocked raw ICMP ping traffic",
            ))

    return tuple(notes)


__all__ = [
    "SeatbeltBackend",
    "build_seatbelt_argv",
    "render_seatbelt_profile",
    "seatbelt_env_for_policy",
    "_render_sbpl_skeleton",
]
