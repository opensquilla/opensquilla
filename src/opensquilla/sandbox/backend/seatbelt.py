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
from opensquilla.sandbox.types import (
    NetworkMode,
    NetworkProxySpec,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SandboxResult,
)

log = logging.getLogger(__name__)

_SANDBOX_EXEC_NAME = "sandbox-exec"
_SANDBOX_EXEC_SYSTEM_PATH = Path("/usr/bin/sandbox-exec")
_OUTPUT_BYTE_CAP = 1_048_576
_TERMINATE_GRACE_S = 2.0

# Broad but explicit runtime reads needed for ordinary macOS command
# execution. Every path here widens the sandbox, so keep the list boring.
_BASE_RO_PATHS: tuple[Path, ...] = (
    Path("/bin"),
    Path("/sbin"),
    Path("/usr/bin"),
    Path("/usr/lib"),
    Path("/System/Library"),
    Path("/Library/Developer/CommandLineTools"),
)
_BREW_PREFIXES: tuple[Path, ...] = (Path("/opt/homebrew"), Path("/usr/local"))
_PROTECTED_SUBPATH_NAMES = (".git", ".codex", ".agents")


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


def _parents_for(path: Path) -> list[Path]:
    parents: list[Path] = []
    current = path
    if path.is_file():
        current = path.parent
    for parent in (current, *current.parents):
        if parent == parent.parent:
            break
        parents.append(parent)
    return list(reversed(parents))


def _resolve_executable(argv0: str) -> Path | None:
    candidate = Path(argv0)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    resolved = shutil.which(argv0)
    if resolved is None:
        return None
    return Path(resolved).resolve(strict=False)


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _extra_runtime_read_paths(request: SandboxRequest) -> list[Path]:
    paths: list[Path] = [request.cwd]
    argv0 = Path(request.argv[0])
    if argv0.is_absolute():
        paths.append(argv0)
        paths.extend(_parents_for(argv0))
    exe = _resolve_executable(request.argv[0])
    if exe is not None:
        paths.append(exe)
        paths.extend(_parents_for(exe))
        for prefix in _BREW_PREFIXES:
            if _is_under(exe, prefix):
                paths.append(prefix)
    return paths


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


def _read_rules(paths: Iterable[Path]) -> list[str]:
    rules: list[str] = []
    for path in _unique_existing(paths):
        selector = _literal(path) if path.is_file() else _subpath(path)
        rules.append(f"(allow file-read* {selector})")
    return rules


def _write_rules(paths: Iterable[Path]) -> list[str]:
    return [f"(allow file-write* {_subpath(path)})" for path in _unique_existing(paths)]


def _protected_write_deny_rules(paths: Iterable[Path]) -> list[str]:
    rules: list[str] = []
    for root in _unique_existing(paths):
        if root.is_file():
            continue
        for name in _PROTECTED_SUBPATH_NAMES:
            protected = root / name
            if protected.exists():
                rules.append(f"(deny file-write* {_subpath(protected)})")
    return rules


def _network_proxy_rule(proxy: NetworkProxySpec) -> str:
    return f"(allow network-outbound (remote tcp {_scheme_string(f'{proxy.host}:{proxy.port}')}))"


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

    read_paths: list[Path] = []
    write_paths: list[Path] = []
    workspace = next(
        (m for m in policy.mounts if m.sandbox_path.as_posix() == "/workspace"),
        None,
    )
    if workspace is not None:
        read_paths.append(workspace.host_path)
        if workspace.mode == "rw" or policy.workspace_rw:
            write_paths.append(workspace.host_path)

    for spec in policy.mounts:
        if spec is workspace:
            continue
        if not spec.host_path.exists():
            if spec.required:
                raise SandboxBackendError(f"required mount missing on host: {spec.host_path!r}")
            log.debug("sandbox.seatbelt_mount_skipped: %s (not present)", spec.host_path)
            continue
        read_paths.append(spec.host_path)
        if spec.mode == "rw":
            write_paths.append(spec.host_path)

    if tmp_dir is not None:
        read_paths.append(tmp_dir)
        write_paths.append(tmp_dir)

    read_paths.extend(path for path in _BASE_RO_PATHS if path.exists())
    read_paths.extend(_extra_runtime_read_paths(request))

    lines: list[str] = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        f"(allow file-read* {_literal(Path('/'))})",
    ]
    if policy.network == NetworkMode.NONE:
        lines.append("(deny network*)")
    elif policy.network == NetworkMode.HOST:
        lines.append("(allow network*)")
    elif policy.network == NetworkMode.PROXY_ALLOWLIST:
        if policy.network_proxy is None:  # pragma: no cover - guarded above
            raise SandboxBackendError(
                "NetworkMode.PROXY_ALLOWLIST requires a network proxy "
                "for the seatbelt backend"
            )
        lines.append(_network_proxy_rule(policy.network_proxy))
    else:  # pragma: no cover - exhaustive guard for future enum values
        raise SandboxBackendError(f"unsupported seatbelt network mode: {policy.network!r}")

    lines.extend(_read_rules(read_paths))
    lines.extend(_write_rules(write_paths))
    lines.extend(_protected_write_deny_rules(write_paths))
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


class SeatbeltBackend(Backend):
    """macOS ``sandbox-exec`` backend."""

    name = "seatbelt"

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary

    def available(self) -> bool:
        if sys.platform != "darwin":
            return False
        return _sandbox_exec_binary(self._binary) is not None

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
            if not timed_out and returncode != 0:
                notes = _classify_denial(request.argv, stderr)
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


def _classify_denial(argv: tuple[str, ...], stderr: str) -> tuple[_SeatbeltNote, ...]:
    """Scan the tail of ``stderr`` for known Seatbelt denial signatures."""
    if not stderr:
        return ()
    tail = stderr[-_STDERR_SCAN_BYTES:]
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

    return tuple(notes)


__all__ = [
    "SeatbeltBackend",
    "build_seatbelt_argv",
    "render_seatbelt_profile",
    "seatbelt_env_for_policy",
    "_render_sbpl_skeleton",
]
