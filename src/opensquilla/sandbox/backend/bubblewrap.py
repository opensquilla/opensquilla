"""Linux bubblewrap backend.

Executes the caller's argv inside a fresh ``bwrap`` child per request. The
argv construction follows the bubblewrap manpage (``bwrap(1)``).

Design notes:

* The sandbox layout is a minimal root view: ``/`` starts as tmpfs, host
  runtime directories such as ``/usr`` and ``/lib`` are mounted read-only,
  ``/dev`` receives a curated dev node set, ``/proc`` is a fresh proc mount,
  ``/tmp`` is a tmpfs when the policy allows it, and the user's workspace
  gets an explicit ``--bind`` or ``--ro-bind`` at ``/workspace``.
* Network namespaces are unshared whenever the policy selects
  ``NetworkMode.NONE``. For ``NetworkMode.HOST`` we deliberately keep the
  host network visible (no ``--unshare-net``) — this is only reached when
  the policy layer has opted in (e.g. ``STANDARD`` + network-tagged
  action).
* Capabilities are dropped via ``--cap-drop ALL`` and ``--new-session``
  detaches the controlling terminal to prevent ``TIOCSTI`` style escapes.
* Output is captured in memory with an upper bound; excess bytes are
  truncated and the ``truncated_*`` flags are set on the result.
* Wall timeouts are enforced with :func:`asyncio.wait_for`; on expiry we
  terminate the process group so dangling grandchildren do not outlive the
  sandbox. If SIGTERM isn't observed within a small grace window we follow
  with SIGKILL.

The backend does not assume root and never tries to privilege-up. If the
kernel forbids user namespaces the ``bwrap`` invocation will surface a
non-zero exit which we translate into a :class:`SandboxBackendError`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, cast

from opensquilla.sandbox.backend.base import Backend
from opensquilla.sandbox.backend.linux_proxy_bridge import (
    ENV_PROXY_PORT,
    ENV_PROXY_UDS,
    PROXY_ENV_KEYS,
    LinuxProxyBridgeHost,
)
from opensquilla.sandbox.types import (
    SANDBOX_WORKSPACE_PATH,
    MountSpec,
    NetworkMode,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SandboxResult,
    sandbox_path_text,
)

log = logging.getLogger(__name__)

_BWRAP_BINARY = "bwrap"
_OUTPUT_BYTE_CAP = 1_048_576  # 1 MiB per stream
_TERMINATE_GRACE_S = 2.0
_DEFAULT_BRIDGE_UDS_PATH = Path("/tmp/opensquilla-sandbox-proxy.sock")
_DEFAULT_BRIDGE_SCRIPT_NAME = "inner_bridge.py"
_BWRAP_PYTHON_CANDIDATES: tuple[Path, ...] = (
    Path("/usr/bin/python3"),
    Path("/bin/python3"),
    Path("/usr/bin/python"),
    Path("/bin/python"),
)
_HOST_RO_PATHS: tuple[Path, ...] = (
    Path("/usr"),
    Path("/bin"),
    Path("/lib"),
    Path("/lib64"),
    Path("/etc"),
)


def _validate_mount_path(path: Path, *, kind: str) -> None:
    """Reject non-absolute, traversal, or obviously unsafe paths.

    Symlink targets are *not* resolved here — the sandbox invariant is that
    the host side is whatever the caller passed in; if they handed us a
    symlink, that's fine as long as it's absolute and doesn't obviously
    escape. We do refuse ``..`` components so a typo cannot slide into a
    parent directory.
    """
    if not path.is_absolute():
        raise SandboxBackendError(f"{kind} mount path must be absolute: {path!r}")
    parts = path.parts
    if any(part == ".." for part in parts):
        raise SandboxBackendError(f"{kind} mount path contains '..': {path!r}")


def _validate_sandbox_path(path: str | PurePath, *, kind: str) -> str:
    text = sandbox_path_text(path)
    if not text.startswith("/"):
        raise SandboxBackendError(f"{kind} mount path must be absolute: {path!r}")
    parts = PurePosixPath(text).parts
    if any(part == ".." for part in parts):
        raise SandboxBackendError(f"{kind} mount path contains '..': {path!r}")
    return PurePosixPath(text).as_posix()


def _mount_args(spec: MountSpec) -> list[str]:
    _validate_mount_path(spec.host_path, kind="host")
    sandbox_path = _validate_sandbox_path(spec.sandbox_path, kind="sandbox")
    flag = "--bind" if spec.mode == "rw" else "--ro-bind"
    return [flag, str(spec.host_path), sandbox_path]


def _env_args(policy: SandboxPolicy, override_env: dict[str, str]) -> list[str]:
    """Produce ``--setenv`` pairs for the allowlisted environment.

    Both inherited host values and caller-provided ``override_env`` keys are
    filtered through ``policy.env_allowlist``. Previously overrides bypassed
    the allowlist, which let callers reintroduce disallowed variables such as
    ``SSH_AUTH_SOCK`` / ``AWS_SECRET_ACCESS_KEY`` / proxy settings — the
    stated env-scrubbing guarantee depends on the override path being gated
    too.
    """
    allowlist = set(policy.env_allowlist)
    resolved: dict[str, str] = {}
    for key in policy.env_allowlist:
        value = os.environ.get(key)
        if value is not None:
            resolved[key] = value
    for key, value in override_env.items():
        if key not in allowlist:
            log.debug(
                "sandbox.env_override_rejected: key=%s (not in allowlist)",
                key,
            )
            continue
        resolved[key] = value
    workspace_mount = next(
        (
            m
            for m in policy.mounts
            if sandbox_path_text(m.sandbox_path) == SANDBOX_WORKSPACE_PATH.as_posix()
        ),
        None,
    )
    if workspace_mount is not None and "HOME" in allowlist:
        resolved["HOME"] = sandbox_path_text(workspace_mount.sandbox_path)
    args: list[str] = []
    for key, value in resolved.items():
        args.extend(["--setenv", key, value])
    return args


def _dir_chain_args(path: str | PurePath) -> list[str]:
    sandbox_path = _validate_sandbox_path(path, kind="sandbox")
    args: list[str] = []
    current = PurePosixPath("/")
    for part in PurePosixPath(sandbox_path).parts[1:]:
        current /= part
        args.extend(["--dir", current.as_posix()])
    return args


def _proxy_env_args(uds_path: Path, port: int) -> list[str]:
    proxy_url = f"http://127.0.0.1:{port}"
    pairs = [
        (ENV_PROXY_UDS, str(uds_path)),
        (ENV_PROXY_PORT, str(port)),
        *((key, proxy_url) for key in PROXY_ENV_KEYS),
    ]
    args: list[str] = []
    for key, value in pairs:
        args.extend(["--setenv", key, value])
    return args


def _bridge_python_path() -> Path:
    for candidate in _BWRAP_PYTHON_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SandboxBackendError(
        "NetworkMode.PROXY_ALLOWLIST requires a system Python mounted "
        "inside the bubblewrap sandbox"
    )


def _default_bridge_script_path(uds_path: Path) -> Path:
    return uds_path.parent / _DEFAULT_BRIDGE_SCRIPT_NAME


def _proxy_bridge_child_argv(
    request: SandboxRequest,
    *,
    bridge_script_path: Path,
) -> list[str]:
    return [
        str(_bridge_python_path()),
        str(bridge_script_path),
        "--",
        *request.argv,
    ]


def build_bwrap_argv(
    request: SandboxRequest,
    *,
    binary: str = _BWRAP_BINARY,
    bridge_uds_path: Path | None = None,
    bridge_script_path: Path | None = None,
    bridge_port: int | None = None,
) -> list[str]:
    """Return the ``bwrap`` argv for ``request``.

    Factored out so unit tests can assert argv shape without running bwrap.
    Ordering matters for ``bwrap``: the flag stream describes the sandbox
    construction step-by-step, then ``--`` separates our flags from the
    child argv.
    """
    policy = request.policy
    argv: list[str] = [binary]
    proxy_bridge_uds_path: Path | None = None
    proxy_bridge_script_path: Path | None = None
    proxy_bridge_port: int | None = None

    # Structural flags first — these describe the process and namespace
    # posture and are safe to accumulate before any mount flags.
    argv += [
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
        "--unshare-cgroup-try",
        "--unshare-user-try",
        "--cap-drop",
        "ALL",
    ]
    if policy.network == NetworkMode.NONE:
        argv.append("--unshare-net")
    elif policy.network == NetworkMode.PROXY_ALLOWLIST:
        if policy.network_proxy is None:
            raise SandboxBackendError(
                "NetworkMode.PROXY_ALLOWLIST requires a network proxy "
                "for the bubblewrap backend"
            )
        argv.append("--unshare-net")
        proxy_bridge_uds_path = bridge_uds_path or _DEFAULT_BRIDGE_UDS_PATH
        proxy_bridge_script_path = (
            bridge_script_path or _default_bridge_script_path(proxy_bridge_uds_path)
        )
        proxy_bridge_port = bridge_port or policy.network_proxy.port
        if proxy_bridge_port <= 0 or proxy_bridge_port > 65535:
            raise SandboxBackendError(
                "NetworkMode.PROXY_ALLOWLIST requires a valid proxy port "
                "for the bubblewrap backend"
            )

    # Base filesystem skeleton. Use tmpfs as root so synthetic mount points
    # such as /workspace can be created even when the host root lacks them.
    # Runtime directories needed to execute normal host binaries are mounted
    # read-only afterwards.
    argv += ["--tmpfs", "/"]
    for host_path in _HOST_RO_PATHS:
        if host_path.exists():
            argv += ["--ro-bind", str(host_path), str(host_path)]
    argv += ["--proc", "/proc", "--dev", "/dev"]
    if policy.tmp_writable:
        argv += ["--tmpfs", "/tmp"]

    for spec in policy.mounts:
        if spec.required and not spec.host_path.exists():
            raise SandboxBackendError(f"required mount missing on host: {spec.host_path!r}")
        if not spec.host_path.exists():
            log.debug("sandbox.mount_skipped: %s (not present)", spec.host_path)
            continue
        argv += ["--dir", _validate_sandbox_path(spec.sandbox_path, kind="sandbox")]
        argv += _mount_args(spec)

    argv += _env_args(policy, request.env)
    if proxy_bridge_uds_path is not None and proxy_bridge_port is not None:
        bridge_dir = proxy_bridge_uds_path.parent
        _validate_mount_path(bridge_dir, kind="proxy bridge")
        if proxy_bridge_script_path is None:  # pragma: no cover - paired assignment above
            raise SandboxBackendError("missing linux proxy bridge script path")
        _validate_mount_path(proxy_bridge_script_path, kind="proxy bridge script")
        if proxy_bridge_script_path.parent != bridge_dir:
            raise SandboxBackendError(
                "linux proxy bridge script must be in the mounted bridge directory"
            )
        argv += _dir_chain_args(bridge_dir)
        argv += ["--bind", str(bridge_dir), str(bridge_dir)]
        argv += _proxy_env_args(proxy_bridge_uds_path, proxy_bridge_port)

    # Working directory inside the sandbox — default to the workspace mount
    # point when one exists, otherwise the host cwd mapped through.
    workspace_mount = next(
        (
            m
            for m in policy.mounts
            if sandbox_path_text(m.sandbox_path) == SANDBOX_WORKSPACE_PATH.as_posix()
        ),
        None,
    )
    if workspace_mount is not None:
        try:
            rel = request.cwd.relative_to(workspace_mount.host_path)
        except ValueError:
            argv += ["--chdir", str(request.cwd)]
        else:
            sandbox_cwd = PurePosixPath(sandbox_path_text(workspace_mount.sandbox_path))
            argv += ["--chdir", sandbox_cwd.joinpath(*rel.parts).as_posix()]
    else:
        argv += ["--chdir", str(request.cwd)]

    argv.append("--")
    if proxy_bridge_script_path is not None:
        argv.extend(
            _proxy_bridge_child_argv(
                request,
                bridge_script_path=proxy_bridge_script_path,
            )
        )
    else:
        argv.extend(request.argv)
    return argv


class BubblewrapBackend(Backend):
    """Linux bubblewrap-backed implementation of :class:`Backend`."""

    name = "bubblewrap"

    def __init__(self, binary: str = _BWRAP_BINARY) -> None:
        self._binary = binary

    def available(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        return shutil.which(self._binary) is not None

    async def run(self, request: SandboxRequest) -> SandboxResult:  # noqa: C901 — linear orchestration
        if not self.available():
            raise SandboxBackendError(
                "bubblewrap backend unavailable: missing 'bwrap' binary on PATH"
            )

        bridge: LinuxProxyBridgeHost | None = None
        bridge_tmp: tempfile.TemporaryDirectory[str] | None = None
        try:
            bridge_uds_path: Path | None = None
            if request.policy.network == NetworkMode.PROXY_ALLOWLIST:
                if request.policy.network_proxy is not None:
                    bridge_tmp = tempfile.TemporaryDirectory(
                        prefix="opensquilla-bwrap-proxy-bridge-"
                    )
                    bridge_uds_path = Path(bridge_tmp.name) / "proxy.sock"
                    bridge = LinuxProxyBridgeHost(
                        bridge_uds_path,
                        request.policy.network_proxy.host,
                        request.policy.network_proxy.port,
                    )
                    await bridge.start()

            argv = build_bwrap_argv(
                request,
                binary=self._binary,
                bridge_uds_path=bridge_uds_path,
            )
            log.info(
                "sandbox.bwrap_spawn: action=%s level=%s network=%s argv_len=%d",
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
                    start_new_session=True,
                )
            except FileNotFoundError as exc:
                raise SandboxBackendError(f"bwrap launch failed: {exc}") from exc
            except OSError as exc:
                raise SandboxBackendError(f"bwrap launch failed: {exc}") from exc

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
            )
        finally:
            if bridge is not None:
                await bridge.stop()
            if bridge_tmp is not None:
                bridge_tmp.cleanup()


def _decode_capped(raw: bytes | None) -> tuple[str, bool]:
    if not raw:
        return "", False
    if len(raw) <= _OUTPUT_BYTE_CAP:
        return raw.decode("utf-8", errors="replace"), False
    return raw[:_OUTPUT_BYTE_CAP].decode("utf-8", errors="replace"), True


async def _terminate_process_group(
    proc: asyncio.subprocess.Process,
) -> tuple[bytes, bytes]:
    """Best-effort process-group cleanup after a wall-timeout.

    We can't ``communicate`` a second time once the outer ``wait_for`` was
    cancelled, so we signal the group and then gather whatever the transport
    buffered. If SIGTERM doesn't clear the group we escalate to SIGKILL.
    """
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
        except Exception:  # noqa: BLE001 — best effort after kill
            stdout = b""
    if proc.stderr is not None:
        try:
            stderr = await proc.stderr.read()
        except Exception:  # noqa: BLE001 — best effort after kill
            stderr = b""
    return stdout, stderr


__all__ = ["BubblewrapBackend", "build_bwrap_argv"]
