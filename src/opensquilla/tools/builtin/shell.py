"""Shell built-in tools: exec_command, background_process, process."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import dataclasses
import json
import ntpath
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import structlog

from opensquilla.gateway.approval_queue import get_approval_queue
from opensquilla.sandbox.backend.bubblewrap import BubblewrapBackend, build_bwrap_argv
from opensquilla.sandbox.backend.noop import NoopBackend
from opensquilla.sandbox.backend.seatbelt import (
    SeatbeltBackend,
    build_seatbelt_argv,
    render_seatbelt_profile,
)
from opensquilla.sandbox.capability_profile import CapabilityProfile, capability_profile_for_command
from opensquilla.sandbox.dev_policy_matrix import (
    DevPolicyDecisionKind,
    NetworkTargetClass,
    PathTargetClass,
    decide_dev_recovery,
)
from opensquilla.sandbox.escalation import (
    build_path_approval_params,
    current_tool_mounts,
    grant_temporary_mount_for_current_tool,
    request_sandbox_approval,
)
from opensquilla.sandbox.governance import action_fingerprint
from opensquilla.sandbox.integration import (
    build_request,
    escalate_backend_denial,
    gate_action,
    get_runtime,
    preflight_subprocess_managed_network,
    prepare_subprocess_managed_network_proxy,
    run_under_backend,
)
from opensquilla.sandbox.operation_profile import OperationProfile, classify_command
from opensquilla.sandbox.operation_runtime import SandboxToolDescriptor
from opensquilla.sandbox.path_validation import MountDecision, decide_path_access
from opensquilla.sandbox.policy import LevelHints, build_policy, select_level
from opensquilla.sandbox.runtime_recovery import (
    classify_network_failure,
    classify_path_target,
    explicit_network_hosts_from_command,
    network_class_for_failure,
)
from opensquilla.sandbox.types import (
    DenialReason,
    DenialResult,
    MountSpec,
    NetworkMode,
    SandboxPolicy,
    SandboxRequest,
)
from opensquilla.tools.builtin.shell_policy import check_safe_bin
from opensquilla.tools.path_policy import reject_foreign_host_path
from opensquilla.tools.registry import tool
from opensquilla.tools.run_mode import (
    current_run_mode,
    full_host_access_active,
    trusted_sandbox_active,
)
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolError,
    UnsupportedSurfaceError,
    current_tool_context,
)

log = structlog.get_logger(__name__)

_DEFAULT_EXEC_TIMEOUT = 60.0
_MAX_EXEC_TIMEOUT = 600.0
_APPROVAL_RETRY_WAIT_SECONDS = 180.0
_EXEC_TOOL_TIMEOUT_PADDING = _APPROVAL_RETRY_WAIT_SECONDS + 5.0
_DEFAULT_BACKGROUND_TIMEOUT = 1800.0
_MAX_BACKGROUND_TIMEOUT = 3600.0
_BACKGROUND_TERMINATE_TIMEOUT = 1.0
_BACKGROUND_KILL_TIMEOUT = 1.0
_EXEC_TERMINATE_TIMEOUT = 0.25
_EXEC_KILL_TIMEOUT = 0.25
_EXEC_STDIN_WRITE_CHUNK_BYTES = 64 * 1024
_EXEC_STDIN_GUARD_CHUNK_CHARS = 64 * 1024
_EXEC_STDIN_GUARD_OVERLAP_CHARS = 1024
_COMMAND_AUDIT_MAX_CHARS = 4096
_SANDBOX_NETWORK_HINT = (
    "Hint: sandboxed shell/code has no direct network. Use sandbox_network approval "
    "or trusted managed-network mode, then retry the shell command through the "
    "managed proxy. Do not switch to separate web download tools for package "
    "installs unless the user explicitly asks for an offline workaround."
)
_SANDBOX_NETWORK_FAILURE_MARKERS: tuple[str, ...] = (
    "could not resolve host",
    "could not resolve proxy",
    "temporary failure in name resolution",
    "name or service not known",
    "getaddrinfo failed",
    "network is unreachable",
    "nodename nor servname provided",
    "name resolution failed",
    "failed to resolve",
    "curl: (6)",
)
_SHELL_NULL_REDIRECT_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s;|&]))\d*[<>]{1,2}\s*/dev/null(?=$|[\s;|&])"
)
_BACKEND_NOTE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\)[^\s'\"`$(){}\[\]<>;,|&]+"
    r"|(?:~)?/[^\s'\"`$(){}\[\]<>;,|&]+"
)
_BACKEND_NOTE_WRITE_MARKERS = (
    "bind",
    "create",
    "mkdir",
    "mount",
    "rename",
    "rmdir",
    "truncate",
    "unlink",
    "write",
)
_BACKEND_NOTE_READ_MARKERS = (
    "execve",
    "filesystem.read",
    "open",
    "read",
    "stat",
)
_WINDOWS_POSIX_TMP_QUOTED_RE = re.compile(
    r"(?P<quote>['\"])(?P<path>/tmp(?:/[^'\"]*)?)(?P=quote)"
)
_WINDOWS_POSIX_TMP_BARE_RE = re.compile(
    r"(?<![A-Za-z0-9_./:\\-])(?P<path>/tmp(?:/[^\s'\";&|<>)]*)?)"
)
_WINDOWS_ROOT_TMP_QUOTED_RE = re.compile(
    r"(?P<quote>['\"])(?P<path>(?:[A-Za-z]:[\\/]|[\\/])tmp(?:[\\/][^'\"]*)?)(?P=quote)",
    re.IGNORECASE,
)
_WINDOWS_ROOT_TMP_BARE_RE = re.compile(
    r"(?<![A-Za-z0-9_./:\\-])"
    r"(?P<path>(?:[A-Za-z]:[\\/]|[\\/])tmp(?:[\\/][^\s'\";&|<>)]*)?)",
    re.IGNORECASE,
)
_WINDOWS_SHELL_ARG_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')
_WINDOWS_SHELL_PATH_FLAGS = frozenset(
    {
        "-destination",
        "-filepath",
        "-literalpath",
        "-name",
        "-path",
    }
)
_WINDOWS_SHELL_VALUE_FLAGS = frozenset(
    {
        "-encoding",
        "-erroraction",
        "-errorvariable",
        "-ev",
        "-exclude",
        "-filter",
        "-include",
        "-inputobject",
        "-itemtype",
        "-outvariable",
        "-ov",
        "-stream",
        "-type",
        "-value",
        "-warningaction",
        "-warningvariable",
    }
)
_WINDOWS_SHELL_CREATE_COMMANDS = frozenset({"md", "mkdir", "new-item", "ni"})
_WINDOWS_SHELL_CONTENT_COMMANDS = frozenset({"add-content", "out-file", "set-content"})
_WINDOWS_SHELL_REMOVE_COMMANDS = frozenset({"del", "erase", "remove-item", "rm"})
PROCESS_ACTIONS: frozenset[str] = frozenset(
    {"eof", "kill", "list", "log", "poll", "remove", "submit", "write"}
)

# Background process session store
_bg_sessions: dict[str, _BgSession] = {}


@dataclass
class _BgSession:
    session_id: str
    command: str
    process: asyncio.subprocess.Process
    session_key: str | None = None
    agent_id: str | None = None
    is_owner_run: bool = False
    local_urls: list[str] = field(default_factory=list)
    output_lines: list[str] = field(default_factory=list)
    done: bool = False
    timed_out: bool = False
    killed: bool = False
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    returncode: int | None = None
    collector_task: asyncio.Task[None] | None = None
    cleanup_callbacks: list[Callable[[], None]] = field(default_factory=list)
    async_cleanup_callbacks: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


@dataclass(frozen=True)
class _SpawnedBackgroundProcess:
    process: asyncio.subprocess.Process
    cleanup_callbacks: list[Callable[[], None]] = field(default_factory=list)
    async_cleanup_callbacks: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


# Task-local flag for a single host rerun after the sandbox backend itself
# denied execution and the operator approved that host-once escalation.
_host_once_current_call: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_host_once_current_call", default=False
)
# Legacy private alias for tests/callers that reset the task-local grant.
# Semantics are now host-once, not ordinary approval elevation.
_elevate_current_call = _host_once_current_call


def _audit_command(command: str) -> str:
    if len(command) <= _COMMAND_AUDIT_MAX_CHARS:
        return command
    return command[:_COMMAND_AUDIT_MAX_CHARS] + "...[truncated]"


def _looks_like_sandbox_network_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SANDBOX_NETWORK_FAILURE_MARKERS)


def _append_sandbox_network_hint(text: str, *, force: bool = False) -> str:
    if _SANDBOX_NETWORK_HINT in text:
        return text
    if not force and not _looks_like_sandbox_network_failure(text):
        return text
    return text.rstrip() + "\n" + _SANDBOX_NETWORK_HINT + "\n"


def _profile_shell_command(command: str) -> OperationProfile:
    return classify_command(("sh", "-lc", command))


def _level_hints_for_shell_profile(
    profile: OperationProfile,
    *,
    warnlist_handled: bool = False,
) -> LevelHints:
    return LevelHints(
        needs_network=profile.needs_network,
        high_impact=profile.high_impact and not warnlist_handled,
    )


def _sandbox_effectively_off() -> bool:
    runtime = get_runtime()
    effective = getattr(runtime, "effective", None) if runtime is not None else None
    return runtime is None or not bool(getattr(effective, "sandbox_enabled", False))


def _context_run_mode() -> str | None:
    return current_run_mode()


def _context_elevated_mode() -> str | None:
    """Legacy compatibility: only Full Host Access counts as elevated."""
    return "full" if full_host_access_active() else None


def _consume_host_once_current_call() -> bool:
    if not _host_once_current_call.get():
        return False
    _host_once_current_call.set(False)
    return True


def _host_execution_allowed() -> bool:
    if _consume_host_once_current_call():
        return True
    return full_host_access_active()


def _without_shell_null_redirections(command: str) -> str:
    return _SHELL_NULL_REDIRECT_RE.sub(" ", command)


def _workdir_is_configured_workspace(workdir: str | None) -> bool:
    if not workdir:
        return False
    ctx = current_tool_context.get()
    workspace_dir = getattr(ctx, "workspace_dir", None) if ctx is not None else None
    if not workspace_dir:
        return False
    try:
        cwd = Path(workdir).expanduser().resolve(strict=False)
        workspace = Path(workspace_dir).expanduser().resolve(strict=False)
        return cwd == workspace or workspace in cwd.parents
    except (OSError, RuntimeError):
        return False


def _sensitive_payload_block(tool_name: str, text: str) -> str | None:
    from opensquilla.tools.builtin.web import (
        _sensitive_body_block,
        _sensitive_body_marker,
        _sensitive_url_marker,
    )

    for token in text.split():
        stripped = token.strip("'\"")
        if stripped.startswith(("http://", "https://")):
            marker = _sensitive_url_marker(stripped)
            if marker is not None:
                return _sensitive_body_block(tool_name, marker)
    marker = _sensitive_body_marker(text)
    if marker is not None:
        return _sensitive_body_block(tool_name, marker)
    return None


def _iter_stdin_guard_chunks(text: str) -> Iterator[str]:
    if len(text) <= _EXEC_STDIN_GUARD_CHUNK_CHARS:
        yield text
        return
    step = _EXEC_STDIN_GUARD_CHUNK_CHARS - _EXEC_STDIN_GUARD_OVERLAP_CHARS
    start = 0
    while start < len(text):
        end = min(len(text), start + _EXEC_STDIN_GUARD_CHUNK_CHARS)
        yield text[start:end]
        if end >= len(text):
            break
        start += step


def _sensitive_shell_block(
    tool_name: str,
    command: str,
    *,
    workdir: str | None = None,
    stdin: str | None = None,
) -> str | None:
    if _context_elevated_mode() == "full":
        return None

    from opensquilla.sandbox.sensitive_paths import build_block_envelope, sensitive_path_in_text

    checked_command = _without_shell_null_redirections(command)
    include_workdir = bool(workdir) and not _workdir_is_configured_workspace(workdir)
    checked_text = f"{workdir} {checked_command}" if include_workdir else checked_command
    ctx = current_tool_context.get()
    workspace = ctx.workspace_dir if ctx is not None else None
    marker = sensitive_path_in_text(checked_text, workspace=workspace)
    if marker is not None:
        return json.dumps(
            build_block_envelope(checked_text, marker, tool_name=tool_name),
            ensure_ascii=False,
        )

    payload_block = _sensitive_payload_block(tool_name, checked_text)
    if payload_block is not None:
        return payload_block
    if stdin is None:
        return None

    for stdin_chunk in _iter_stdin_guard_chunks(stdin):
        marker = sensitive_path_in_text(stdin_chunk, workspace=workspace)
        if marker is not None:
            return json.dumps(
                build_block_envelope(
                    f"{checked_command}\n[stdin omitted]",
                    marker,
                    tool_name=tool_name,
                ),
                ensure_ascii=False,
            )
    for stdin_chunk in _iter_stdin_guard_chunks(stdin):
        payload_block = _sensitive_payload_block(tool_name, stdin_chunk)
        if payload_block is not None:
            return payload_block
    return None


def _workspace_lockdown_roots() -> list[Path]:
    ctx = current_tool_context.get()
    if ctx is None or not ctx.workspace_lockdown:
        return []
    roots: list[Path] = []
    if ctx.workspace_dir:
        roots.append(Path(ctx.workspace_dir).expanduser().resolve(strict=False))
    if ctx.scratch_dir:
        roots.append(Path(ctx.scratch_dir).expanduser().resolve(strict=False))
    return roots


def _path_inside_any_root(path: Path, roots: list[Path]) -> bool:
    candidate = path.expanduser().resolve(strict=False)
    for root in roots:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _path_access_required_envelope(
    decision: MountDecision,
    *,
    approval_id: str | None = None,
) -> dict[str, object]:
    ctx = current_tool_context.get()
    workspace_root = _workspace_root_for_path_access()
    approval = build_path_approval_params(
        decision,
        session_key=getattr(ctx, "session_key", None) if ctx is not None else None,
        workspace=str(workspace_root) if workspace_root is not None else None,
    )
    if approval is None:
        return {
            "status": "path_access_required",
            "path": decision.normalized_path,
            "access": decision.access,
            "message": _path_access_message(workspace_root),
        }
    return request_sandbox_approval(
        approval,
        approval_id=approval_id,
        message=_path_access_message(workspace_root),
        denied_message=_path_access_denied_message(workspace_root),
    )


def _path_access_message(workspace_root: Path | None) -> str:
    workspace = str(workspace_root) if workspace_root is not None else "the configured workspace"
    return (
        f"The requested path is outside the current workspace ({workspace}). "
        "Ask the user whether to add this path as read-only or read/write access."
    )


def _path_access_denied_message(workspace_root: Path | None) -> str:
    workspace = str(workspace_root) if workspace_root is not None else "the configured workspace"
    return (
        "The user denied access outside the current workspace. "
        "Do not ask for the same access again in this turn. "
        "Explain that the requested path cannot be inspected from the current "
        f"workspace ({workspace}) unless the user approves access or changes run mode. "
        "Do not substitute details from other repositories or prior comparison context."
    )


def _path_access_blocked_envelope(decision: MountDecision) -> dict[str, object]:
    return {
        "status": "blocked",
        "reason": "sensitive_path",
        "path": decision.normalized_path,
        "message": decision.reason,
    }


def _sandbox_path_access_enabled() -> bool:
    runtime = get_runtime()
    if runtime is None or not runtime.effective.sandbox_enabled:
        return False
    return not full_host_access_active()


def _workspace_root_for_path_access() -> Path | None:
    ctx = current_tool_context.get()
    if ctx is not None and ctx.workspace_dir:
        return Path(ctx.workspace_dir).expanduser().resolve(strict=False)
    runtime = get_runtime()
    runtime_workspace = getattr(runtime, "workspace", None) if runtime is not None else None
    if runtime_workspace is not None:
        return Path(runtime_workspace).expanduser().resolve(strict=False)
    return None


def _windows_sandbox_backend_active(runtime: object | None = None) -> bool:
    runtime = get_runtime() if runtime is None else runtime
    backend = getattr(runtime, "backend", None) if runtime is not None else None
    backend_name = str(getattr(backend, "name", "") or "")
    return backend_name.startswith("windows_")


def _windows_session_slug() -> str:
    ctx = current_tool_context.get()
    raw = str(getattr(ctx, "session_key", None) or "default")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-._")
    if not slug:
        return "default"
    return slug[:80]


def _windows_session_tmp_root() -> Path | None:
    workspace = _workspace_root_for_path_access()
    if workspace is None:
        return None
    return (
        workspace
        / ".opensquilla"
        / "tmp"
        / _windows_session_slug()
    ).resolve(strict=False)


def _windows_tmp_tail(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    lower = normalized.lower()
    if lower == "/tmp" or lower.startswith("/tmp/"):
        return normalized[4:].lstrip("/")
    match = re.match(r"^[A-Za-z]:/tmp(?:/(.*))?$", normalized, re.IGNORECASE)
    if match:
        return match.group(1) or ""
    return None


def _windows_translate_tmp_path(path: str) -> str:
    tail = _windows_tmp_tail(path)
    if tail is None:
        return path
    root = _windows_session_tmp_root()
    if root is None:
        return path
    mapped = root.joinpath(*[part for part in tail.split("/") if part]) if tail else root
    mapped.parent.mkdir(parents=True, exist_ok=True)
    if not tail:
        mapped.mkdir(parents=True, exist_ok=True)
    return str(mapped)


def _windows_translate_posix_tmp_path(path: str) -> str:
    return _windows_translate_tmp_path(path)


def _windows_translate_tmp_references(command: str) -> str:
    def replace_quoted(match: re.Match[str]) -> str:
        quote = match.group("quote")
        return f"{quote}{_windows_translate_tmp_path(match.group('path'))}{quote}"

    translated = _WINDOWS_POSIX_TMP_QUOTED_RE.sub(replace_quoted, command)
    translated = _WINDOWS_ROOT_TMP_QUOTED_RE.sub(replace_quoted, translated)
    translated = _WINDOWS_POSIX_TMP_BARE_RE.sub(
        lambda match: _windows_translate_tmp_path(match.group("path")),
        translated,
    )
    return _WINDOWS_ROOT_TMP_BARE_RE.sub(
        lambda match: _windows_translate_tmp_path(match.group("path")),
        translated,
    )


def _windows_translate_posix_tmp_references(command: str) -> str:
    return _windows_translate_tmp_references(command)


def _apply_windows_session_tmp_env(env: dict[str, str]) -> None:
    root = _windows_session_tmp_root()
    if root is None:
        return
    root.mkdir(parents=True, exist_ok=True)
    value = str(root)
    env["TEMP"] = value
    env["TMP"] = value
    env["TMPDIR"] = value


def _sandbox_shell_policy_cwd(cwd: str | None) -> Path | None:
    workspace = _workspace_root_for_path_access()
    if workspace is not None:
        return workspace
    if cwd:
        return Path(cwd).expanduser().resolve(strict=False)
    return None


def _trusted_windows_cmd_path() -> str:
    comspec = os.environ.get("COMSPEC", "")
    if _is_absolute_cmd_exe(comspec):
        return comspec
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or ""
    if system_root and "\x00" not in system_root and ntpath.isabs(system_root):
        return ntpath.join(system_root, "System32", "cmd.exe")
    return r"C:\Windows\System32\cmd.exe"


def _is_absolute_cmd_exe(path: str) -> bool:
    return "\x00" not in path and ntpath.isabs(path) and ntpath.basename(path).lower() == "cmd.exe"


def _trusted_windows_powershell_path() -> str:
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or ""
    if system_root and "\x00" not in system_root and ntpath.isabs(system_root):
        return ntpath.join(
            system_root,
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
    return r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def _windows_direct_powershell_argv(command: str) -> tuple[str, ...]:
    return (
        _trusted_windows_powershell_path(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    )


_WINDOWS_SANDBOX_SHELL_HOST_CODE = r"""
import os
import re
import shutil
import stat
import subprocess
import sys

_REMOVE_ITEM_RE = re.compile(
    r"^(?:Remove-Item|rm|del|erase)\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_INVOKE_PYTHON_RE = re.compile(
    r"^Invoke-OpenSquillaPythonProcess\s+"
    r"-FilePath\s+'(?P<path>(?:''|[^'])*)'\s+"
    r"-Arguments\s+@\((?P<args>.*)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_PATH_TOKEN_RE = re.compile(
    r"(?:-(?:LiteralPath|Path)\s+)?(?P<quote>['\"])(?P<path>.*?)(?P=quote)",
    re.IGNORECASE,
)
_EXPLICIT_BARE_PATH_RE = re.compile(
    r"-(?:LiteralPath|Path)\s+(?P<path>(?!['\"])[^\s;{}]+)",
    re.IGNORECASE,
)
_ARG_TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')
_OUTPUT_RE = re.compile(r"^(?:Write-Output|echo)\s+(?P<text>.+)$", re.IGNORECASE)
_IF_REMOVE_RE = re.compile(
    r"^if\s*\(.*?Test-Path.+?\)\s*\{\s*(?P<remove>Remove-Item\b.+?)\s*\}$",
    re.IGNORECASE | re.DOTALL,
)
_VALUE_FLAGS = {
    "-credential",
    "-ea",
    "-erroraction",
    "-ev",
    "-errorvariable",
    "-exclude",
    "-filter",
    "-include",
    "-ov",
    "-outvariable",
    "-stream",
    "-wa",
    "-warningaction",
    "-wv",
    "-warningvariable",
}


def _strip_outer_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _looks_like_path(value):
    return bool(
        re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith("\\\\")
        or value.startswith(".\\")
        or value.startswith("./")
        or value.startswith("\\")
        or value.startswith("/")
    )


def _split_statements(script):
    statements = []
    current = []
    quote = ""
    escaped = False
    for char in script:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "`":
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            current.append(char)
            quote = char
            continue
        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue
        current.append(char)
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def _nested_powershell_command(command):
    match = re.match(
        r"^\s*powershell(?:\.exe)?\b(?P<args>.*)$",
        command,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    args = match.group("args")
    command_match = re.search(
        r"(?:^|\s)-(?:Command|c)\s+(?P<script>.+)$",
        args,
        re.IGNORECASE | re.DOTALL,
    )
    if not command_match:
        return None
    return _strip_outer_quotes(command_match.group("script"))


def _remove_statement_path(statement):
    match = _REMOVE_ITEM_RE.match(statement)
    if not match:
        return None
    rest = match.group("rest")
    path_match = _PATH_TOKEN_RE.search(rest)
    if not path_match:
        explicit_bare = _EXPLICIT_BARE_PATH_RE.search(rest)
        if explicit_bare:
            return explicit_bare.group("path")
        skip_next = False
        for token in _ARG_TOKEN_RE.findall(rest):
            token = _strip_outer_quotes(token)
            folded = token.lower()
            if skip_next:
                skip_next = False
                continue
            if folded in _VALUE_FLAGS:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            if _looks_like_path(token):
                return token
        return None
    return path_match.group("path")


def _if_remove_statement_path(statement):
    match = _IF_REMOVE_RE.match(statement)
    if not match:
        return None
    return _remove_statement_path(match.group("remove"))


def _output_statement_text(statement):
    match = _OUTPUT_RE.match(statement)
    if not match:
        return None
    text = match.group("text")
    if re.search(r"[<>|&]", text):
        return None
    return _strip_outer_quotes(text)


def _remove_path(path, *, recurse, force):
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            if recurse:
                shutil.rmtree(path)
            else:
                os.rmdir(path)
        else:
            if force:
                try:
                    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                except OSError:
                    pass
            os.remove(path)
    except FileNotFoundError:
        return None
    except Exception as exc:
        return f"{path}: {type(exc).__name__}: {exc}"
    return None


def _handle_simple_delete_script(script):
    statements = _split_statements(script)
    if not statements:
        return None
    operations = []
    recurse = False
    force = False
    for statement in statements:
        path = _remove_statement_path(statement)
        if path is not None:
            recurse = recurse or bool(re.search(r"\s-Recurse\b", statement, re.IGNORECASE))
            force = force or bool(re.search(r"\s-Force\b", statement, re.IGNORECASE))
            operations.append(("remove", path))
            continue
        path = _if_remove_statement_path(statement)
        if path is not None:
            recurse = recurse or bool(re.search(r"\s-Recurse\b", statement, re.IGNORECASE))
            force = force or bool(re.search(r"\s-Force\b", statement, re.IGNORECASE))
            operations.append(("remove", path))
            continue
        output = _output_statement_text(statement)
        if output is not None:
            operations.append(("output", output))
            continue
        return None
    errors = [
        error
        for operation, value in operations
        if operation == "remove"
        if (error := _remove_path(value, recurse=recurse, force=force))
    ]
    if errors:
        sys.stderr.write("\n".join(errors))
        return 1
    for operation, value in operations:
        if operation == "output":
            print(value)
    return 0


def _ps_single_quote(value):
    return "'" + value.replace("'", "''") + "'"


def _python_process_prelude():
    target = _ps_single_quote(sys.executable)
    return (
        "function ConvertTo-OpenSquillaNativeArgumentLine { "
        "param([string[]]$Arguments) "
        "$quoted = foreach ($arg in $Arguments) { "
        "$value = [string]$arg; "
        "if ($value.Length -eq 0) { '\"\"' } "
        "elseif ($value -notmatch '[\\s\"]') { $value } "
        "else { '\"' + (($value -replace '\\\\', '\\\\') -replace '\"', '\\\"') + '\"' } "
        "}; "
        "$quoted -join ' ' "
        "}; "
        "function Invoke-OpenSquillaPythonProcess { "
        "param([Parameter(Mandatory=$true)][string]$FilePath, [string[]]$Arguments = @()) "
        "$argumentLine = ConvertTo-OpenSquillaNativeArgumentLine -Arguments $Arguments; "
        "$psi = New-Object System.Diagnostics.ProcessStartInfo; "
        "$psi.FileName = $FilePath; "
        "$psi.Arguments = $argumentLine; "
        "$psi.WorkingDirectory = (Get-Location).Path; "
        "$psi.UseShellExecute = $false; "
        "$psi.RedirectStandardOutput = $true; "
        "$psi.RedirectStandardError = $true; "
        "$process = New-Object System.Diagnostics.Process; "
        "$process.StartInfo = $psi; "
        "[void]$process.Start(); "
        "$stdout = $process.StandardOutput.ReadToEnd(); "
        "$stderr = $process.StandardError.ReadToEnd(); "
        "$process.WaitForExit(); "
        "if ($stdout) { [Console]::Out.Write($stdout) }; "
        "if ($stderr) { [Console]::Error.Write($stderr) }; "
        "$global:LASTEXITCODE = $process.ExitCode; "
        "if ($process.ExitCode -ne 0) { "
        "Write-Error ('Python process exited with code ' + $process.ExitCode) "
        "} "
        "}; "
        "function python { "
        f"Invoke-OpenSquillaPythonProcess -FilePath {target} -Arguments $args "
        "}; "
        "function python3 { "
        f"Invoke-OpenSquillaPythonProcess -FilePath {target} -Arguments $args "
        "}; "
        f"function py {{ Invoke-OpenSquillaPythonProcess -FilePath {target} -Arguments $args }}; "
    )


def _with_python_aliases(command):
    return _python_process_prelude() + command


def _python_sitecustomize_source():
    return r'''
import os
import subprocess
import tempfile

if os.name == "nt" and os.environ.get("OPENSQUILLA_WINDOWS_APPCONTAINER_TEMPFILE_PATCH") == "1":
    def _opensquilla_mkdtemp(suffix=None, prefix=None, dir=None):
        sanitized = tempfile._sanitize_params(prefix, suffix, dir)
        prefix, suffix, dir = sanitized[:3]
        names = tempfile._get_candidate_names()
        for _ in range(tempfile.TMP_MAX):
            name = next(names)
            path = os.path.join(dir, prefix + name + suffix)
            try:
                os.mkdir(path)
            except FileExistsError:
                continue
            return os.path.abspath(path)
        raise FileExistsError(tempfile._errno.EEXIST, "No usable temporary directory name found")

    tempfile.mkdtemp = _opensquilla_mkdtemp

    _opensquilla_check_output = subprocess.check_output

    def _opensquilla_patched_check_output(*popenargs, **kwargs):
        env = kwargs.get("env")
        site_dir = os.environ.get("OPENSQUILLA_WINDOWS_APPCONTAINER_SITE_DIR")
        if isinstance(env, dict) and site_dir:
            env = dict(env)
            env["OPENSQUILLA_WINDOWS_APPCONTAINER_TEMPFILE_PATCH"] = "1"
            env["OPENSQUILLA_WINDOWS_APPCONTAINER_SITE_DIR"] = site_dir
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = site_dir + (os.pathsep + existing if existing else "")
            kwargs["env"] = env
        return _opensquilla_check_output(*popenargs, **kwargs)

    subprocess.check_output = _opensquilla_patched_check_output
'''.strip()


def _prepare_python_sitecustomize(tmp):
    if not tmp:
        return ""
    site_dir = os.path.join(tmp, "opensquilla-python-sitecustomize")
    os.makedirs(site_dir, exist_ok=True)
    sitecustomize = os.path.join(site_dir, "sitecustomize.py")
    with open(sitecustomize, "w", encoding="utf-8") as handle:
        handle.write(_python_sitecustomize_source())
        handle.write("\n")
    return site_dir


def _split_ps_single_quoted_array(raw):
    args = []
    index = 0
    while index < len(raw):
        while index < len(raw) and raw[index] in " \t\r\n,":
            index += 1
        if index >= len(raw):
            break
        if raw[index] != "'":
            return None
        index += 1
        value = []
        while index < len(raw):
            char = raw[index]
            if char == "'":
                if index + 1 < len(raw) and raw[index + 1] == "'":
                    value.append("'")
                    index += 2
                    continue
                index += 1
                break
            value.append(char)
            index += 1
        else:
            return None
        args.append("".join(value))
        while index < len(raw) and raw[index] in " \t\r\n":
            index += 1
        if index < len(raw):
            if raw[index] != ",":
                return None
            index += 1
    return args


def _env_with_python_sitecustomize(site_dir):
    env = os.environ.copy()
    if not site_dir:
        return env
    env["OPENSQUILLA_WINDOWS_APPCONTAINER_TEMPFILE_PATCH"] = "1"
    env["OPENSQUILLA_WINDOWS_APPCONTAINER_SITE_DIR"] = site_dir
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = site_dir + (os.pathsep + existing if existing else "")
    return env


def _handle_python_process_script(script, cwd, site_dir):
    match = _INVOKE_PYTHON_RE.match(script.strip())
    if match is None:
        return None
    args = _split_ps_single_quoted_array(match.group("args"))
    if args is None:
        return None
    executable = match.group("path").replace("''", "'")
    result = subprocess.run(
        [executable, *args],
        cwd=cwd or None,
        env=_env_with_python_sitecustomize(site_dir),
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


def _with_sandbox_environment(command, cwd, tmp, python_site_dir):
    prelude = ""
    if tmp:
        quoted_tmp = _ps_single_quote(tmp)
        prelude += (
            f"$env:TEMP = {quoted_tmp}; "
            f"$env:TMP = {quoted_tmp}; "
            f"$env:TMPDIR = {quoted_tmp}; "
        )
    if python_site_dir:
        quoted_site_dir = _ps_single_quote(python_site_dir)
        prelude += (
            "$env:OPENSQUILLA_WINDOWS_APPCONTAINER_TEMPFILE_PATCH = '1'; "
            f"$env:OPENSQUILLA_WINDOWS_APPCONTAINER_SITE_DIR = {quoted_site_dir}; "
            "if ($env:PYTHONPATH) { "
            f"$env:PYTHONPATH = {quoted_site_dir} + ';' + $env:PYTHONPATH "
            "} "
            f"else {{ $env:PYTHONPATH = {quoted_site_dir} }}; "
        )
    if not cwd:
        return prelude + command
    quoted_cwd = _ps_single_quote(cwd)
    return prelude + (
        f"try {{ Set-Location -LiteralPath {quoted_cwd} -ErrorAction Stop }} "
        f"catch {{ Write-Error $_; exit 1 }}; {command}"
    )


def _with_final_exit_code(command):
    return (
        f"{command}; "
        "if ($global:LASTEXITCODE -is [int] -and $global:LASTEXITCODE -ne 0) "
        "{ exit $global:LASTEXITCODE }; "
        "if (-not $?) { exit 1 }"
    )


def main():
    if len(sys.argv) not in {3, 4, 5}:
        sys.stderr.write("windows sandbox shell host expects powershell path and command")
        return 2
    powershell = sys.argv[1]
    command = sys.argv[2]
    cwd = sys.argv[3] if len(sys.argv) >= 4 else ""
    tmp = sys.argv[4] if len(sys.argv) == 5 else ""
    python_site_dir = _prepare_python_sitecustomize(tmp)
    nested_command = _nested_powershell_command(command)
    effective_command = nested_command if nested_command is not None else command
    remove_result = _handle_simple_delete_script(effective_command)
    if remove_result is not None:
        return remove_result
    python_process_result = _handle_python_process_script(
        effective_command,
        cwd,
        python_site_dir,
    )
    if python_process_result is not None:
        return python_process_result

    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _with_final_exit_code(
                _with_sandbox_environment(
                    _with_python_aliases(effective_command),
                    cwd,
                    tmp,
                    python_site_dir,
                )
            ),
        ],
        check=False,
    )
    return result.returncode


raise SystemExit(main())
""".strip()


def _sandbox_shell_backend_argv(
    command: str,
    runtime: object,
    *,
    cwd: Path | str | None = None,
) -> tuple[str, ...]:
    backend = getattr(runtime, "backend", None)
    backend_name = getattr(backend, "name", "")
    if backend_name.startswith("windows_"):
        return _windows_direct_powershell_argv(_windows_powershell_compat_command(command))
    return ("sh", "-lc", command)


def _sandbox_shell_backend_cwd(cwd: str | None, request: SandboxRequest) -> Path:
    if cwd:
        return Path(cwd).expanduser().resolve(strict=False)
    return request.cwd


async def _run_backend_with_managed_network(
    request: SandboxRequest,
    *,
    runtime: object,
) -> object:
    if getattr(request.policy, "network", None) is not NetworkMode.PROXY_ALLOWLIST:
        return await run_under_backend(request, runtime=runtime)
    managed_network = await prepare_subprocess_managed_network_proxy(
        request,
        runtime=runtime,
    )
    try:
        return await run_under_backend(managed_network.request, runtime=runtime)
    finally:
        await managed_network.cleanup()


def _windows_strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _windows_shell_tokens(script: str) -> list[str]:
    return [_windows_strip_outer_quotes(token) for token in _WINDOWS_SHELL_ARG_RE.findall(script)]


def _windows_split_logical_and(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(script):
        char = script[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue
        if char == "`":
            current.append(char)
            escaped = True
            index += 1
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "'\"":
            current.append(char)
            quote = char
            index += 1
            continue
        if char == "&" and index + 1 < len(script) and script[index + 1] == "&":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 2
            continue
        current.append(char)
        index += 1
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def _windows_ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _windows_ps_array_literal(values: list[str]) -> str:
    if not values:
        return "@()"
    return "@(" + ",".join(_windows_ps_single_quote(value) for value in values) + ")"


def _windows_python_executable_token(token: str) -> bool:
    command = _windows_shell_command_name(token)
    if command not in {"python", "python3", "pythonw"}:
        return False
    return any(separator in token for separator in ("\\", "/", ":"))


def _windows_powershell_python_process_statement(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    executable_index = 1 if tokens[0] == "&" and len(tokens) > 1 else 0
    executable = tokens[executable_index]
    if not _windows_python_executable_token(executable):
        return None
    arguments = tokens[executable_index + 1 :]
    return (
        "Invoke-OpenSquillaPythonProcess "
        f"-FilePath {_windows_ps_single_quote(executable)} "
        f"-Arguments {_windows_ps_array_literal(arguments)}"
    )


def _windows_nested_powershell_command(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    executable_index = 1 if tokens[0] == "&" and len(tokens) > 1 else 0
    executable = tokens[executable_index]
    if _windows_shell_command_name(executable) not in {"powershell", "pwsh"}:
        return None
    for index, token in enumerate(tokens[executable_index + 1 :], start=executable_index + 1):
        if token.lower() in {"-c", "-command"} and index + 1 < len(tokens):
            return _windows_strip_outer_quotes(" ".join(tokens[index + 1 :]))
    return None


def _windows_powershell_compat_statement(statement: str) -> str:
    tokens = _windows_shell_tokens(statement)
    nested_powershell = _windows_nested_powershell_command(tokens)
    if nested_powershell is not None:
        return nested_powershell
    python_statement = _windows_powershell_python_process_statement(tokens)
    if python_statement is not None:
        return python_statement
    if len(tokens) < 3:
        return statement
    if _windows_shell_command_name(tokens[0]) != "mkdir":
        return statement
    if tokens[1].lower() != "-p":
        return statement
    paths = [token for token in tokens[2:] if token and not token.startswith("-")]
    if not paths:
        return statement
    return "; ".join(
        "New-Item -ItemType Directory -Force -Path "
        f"{_windows_ps_single_quote(path)} | Out-Null"
        for path in paths
    )


def _windows_powershell_compat_command(command: str) -> str:
    statements = _windows_split_logical_and(command)
    if not statements:
        return command
    converted = [_windows_powershell_compat_statement(statement) for statement in statements]
    if len(converted) == 1:
        return converted[0]
    return " ; if (-not $?) { exit 1 }; ".join(converted)


def _windows_split_statements(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for char in script:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "`":
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            current.append(char)
            quote = char
            continue
        if char in ";&":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue
        current.append(char)
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def _windows_shell_command_name(token: str) -> str:
    name = ntpath.basename(token).lower()
    return name.removesuffix(".exe")


def _windows_shell_command_after_option(
    tokens: list[str],
    options: frozenset[str],
) -> str | None:
    for index, token in enumerate(tokens[1:], start=1):
        if token.lower() in options and index + 1 < len(tokens):
            return " ".join(tokens[index + 1 :])
    return None


def _windows_shell_token_looks_like_path(token: str) -> bool:
    if not token or token == "-":
        return False
    lowered = token.lower()
    if lowered.startswith(("http://", "https://")):
        return False
    return (
        lowered in {".venv", "venv"}
        or token.startswith(("/", "\\", "./", ".\\", "../", "..\\"))
        or ntpath.isabs(token)
        or "\\" in token
        or "/" in token
    )


def _windows_paths_from_tokens(tokens: list[str], *, positional: bool = True) -> list[str]:
    paths: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        if lowered in _WINDOWS_SHELL_PATH_FLAGS and index + 1 < len(tokens):
            paths.append(tokens[index + 1])
            index += 2
            continue
        if any(lowered.startswith(f"{flag}:") for flag in _WINDOWS_SHELL_PATH_FLAGS):
            paths.append(token.split(":", 1)[1])
            index += 1
            continue
        if lowered in _WINDOWS_SHELL_VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if positional and _windows_shell_token_looks_like_path(token):
            paths.append(token)
        index += 1
    return paths


def _windows_python_venv_targets(tokens: list[str]) -> list[str]:
    if len(tokens) < 4:
        return []
    command = _windows_shell_command_name(tokens[0])
    if not re.fullmatch(r"py|python(?:\d+(?:\.\d+)*)?", command):
        return []
    if tokens[1].lower() != "-m" or tokens[2].lower() != "venv":
        return []
    for token in tokens[3:]:
        if not token.startswith("-"):
            return [token]
    return []


def _windows_uv_venv_targets(tokens: list[str]) -> list[str]:
    if len(tokens) < 2 or _windows_shell_command_name(tokens[0]) != "uv":
        return []
    if tokens[1].lower() != "venv":
        return []
    index = 2
    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        if lowered in {"--python", "-p", "--seed", "--prompt"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return [token]
    return [".venv"]


def _windows_shell_write_targets(command: str) -> list[str]:
    targets: list[str] = []
    for target in _basic_shell_write_targets(command):
        if target not in targets:
            targets.append(target)
    for statement in _windows_split_statements(command):
        tokens = _windows_shell_tokens(statement)
        if not tokens:
            continue
        command_name = _windows_shell_command_name(tokens[0])
        nested: str | None = _windows_nested_powershell_command(tokens)
        if nested is None and command_name == "cmd":
            nested = _windows_shell_command_after_option(tokens, frozenset({"/c", "/k"}))
        if nested is not None:
            for target in _windows_shell_write_targets(_windows_strip_outer_quotes(nested)):
                if target not in targets:
                    targets.append(target)
            continue
        if command_name in _WINDOWS_SHELL_REMOVE_COMMANDS:
            for target in _windows_paths_from_tokens(tokens):
                if target not in targets:
                    targets.append(target)
            continue
        if command_name in _WINDOWS_SHELL_CREATE_COMMANDS:
            for target in _windows_paths_from_tokens(tokens):
                if target not in targets:
                    targets.append(target)
            continue
        if command_name in _WINDOWS_SHELL_CONTENT_COMMANDS:
            for target in _windows_paths_from_tokens(tokens):
                if target not in targets:
                    targets.append(target)
            continue
        for target in (*_windows_python_venv_targets(tokens), *_windows_uv_venv_targets(tokens)):
            if target not in targets:
                targets.append(target)
    return targets


def _active_sandbox_mounts() -> list[dict[str, object]]:
    return current_tool_mounts()


def _backend_denial_target_path(
    backend_notes: tuple[str, ...],
    fallback: Path,
) -> Path:
    for note in backend_notes:
        match = _BACKEND_NOTE_PATH_RE.search(note)
        if match is not None:
            return Path(match.group(0).rstrip(".,:"))
    return fallback


def _policy_with_active_tool_mounts(policy: SandboxPolicy) -> SandboxPolicy:
    if not hasattr(policy, "mounts"):
        return policy
    mounts_by_path = {str(mount.host_path): mount for mount in policy.mounts}
    for mount in _active_sandbox_mounts():
        raw_path = mount.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        access = str(mount.get("access") or "ro").strip()
        mode = "rw" if access == "rw" else "ro"
        host_path = Path(raw_path).expanduser().resolve(strict=False)
        mounts_by_path[str(host_path)] = MountSpec(
            host_path=host_path,
            sandbox_path=host_path,
            mode=mode,
            required=False,
        )
    return dataclasses.replace(policy, mounts=tuple(mounts_by_path.values()))


def _windows_shell_runtime_mount_paths() -> tuple[Path, ...]:
    paths: list[Path] = []
    for raw in (
        sys.prefix,
        sys.base_prefix,
        str(Path(sys.executable).parent),
        str(Path(getattr(sys, "_base_executable", "")).parent),
    ):
        if not raw:
            continue
        path = Path(raw).expanduser().resolve(strict=False)
        if not path.exists():
            continue
        if path not in paths:
            paths.append(path)
    return tuple(paths)


def _windows_runtime_readonly_roots() -> tuple[Path, ...]:
    if not _windows_sandbox_backend_active():
        return ()
    try:
        from opensquilla.sandbox.backend import windows_default

        roots = windows_default._runtime_readonly_roots()
    except Exception:
        return ()
    return tuple(Path(root).expanduser().resolve(strict=False) for root in roots)


def _policy_with_windows_shell_runtime_mounts(
    policy: SandboxPolicy,
    runtime: object | None,
) -> SandboxPolicy:
    if not _windows_sandbox_backend_active(runtime) or not hasattr(policy, "mounts"):
        return policy
    mounts_by_path = {str(mount.host_path): mount for mount in policy.mounts}
    for path in _windows_shell_runtime_mount_paths():
        existing = mounts_by_path.get(str(path))
        if existing is not None and existing.mode == "rw":
            continue
        mounts_by_path[str(path)] = MountSpec(
            host_path=path,
            sandbox_path=path,
            mode="ro",
            required=True,
        )
    return dataclasses.replace(policy, mounts=tuple(mounts_by_path.values()))


def _policy_with_wall_timeout(
    policy: SandboxPolicy,
    wall_timeout_s: float,
) -> SandboxPolicy:
    if not hasattr(policy, "limits"):
        return policy
    return dataclasses.replace(
        policy,
        limits=dataclasses.replace(
            policy.limits,
            wall_timeout_s=max(0.01, float(wall_timeout_s)),
        ),
    )


def _backend_denial_requires_write(
    backend_notes: tuple[str, ...],
    *,
    default: bool = False,
) -> bool:
    lowered = " ".join(backend_notes).lower()
    if any(marker in lowered for marker in _BACKEND_NOTE_WRITE_MARKERS):
        return True
    if any(marker in lowered for marker in _BACKEND_NOTE_READ_MARKERS):
        return False
    return default


def _trusted_path_recovery_retry_request(
    command: str,
    backend_request: SandboxRequest,
    backend_notes: tuple[str, ...],
    *,
    capability_profile: CapabilityProfile | None = None,
    write_default: bool = False,
) -> SandboxRequest | None:
    if not trusted_sandbox_active():
        return None

    target = _backend_denial_target_path(backend_notes, backend_request.cwd)
    workspace = _workspace_root_for_path_access()
    if capability_profile is None:
        capability_profile = capability_profile_for_command(("sh", "-lc", command))
    path_class = classify_path_target(target, workspace=workspace)
    recovery_decision = decide_dev_recovery(
        _context_run_mode() or "standard",
        capability_profile,
        path_class,
        network_class=NetworkTargetClass.NONE,
    )
    if (
        recovery_decision.kind is not DevPolicyDecisionKind.AUTO
        or not recovery_decision.retry_once
        or not recovery_decision.grant_rw_path
    ):
        return None

    mount_decision = decide_path_access(
        target,
        workspace=workspace,
        mounts=_active_sandbox_mounts(),
        write=_backend_denial_requires_write(backend_notes, default=write_default),
    )
    if mount_decision.status == "blocked":
        return None
    if mount_decision.status == "request" and not grant_temporary_mount_for_current_tool(
        mount_decision
    ):
        return None

    retry_policy = _policy_with_active_tool_mounts(backend_request.policy)
    if retry_policy.mounts == backend_request.policy.mounts:
        return None
    return backend_request.with_policy(retry_policy)


def _sandbox_workdir_access_envelope(
    workdir: str | None,
    *,
    write: bool = False,
    approval_id: str | None = None,
) -> dict[str, object] | None:
    if not workdir or not _sandbox_path_access_enabled():
        return None
    decision = decide_path_access(
        workdir,
        workspace=_workspace_root_for_path_access(),
        mounts=_active_sandbox_mounts(),
        write=write,
    )
    if decision.status == "allowed":
        return None
    if decision.status == "blocked":
        return _path_access_blocked_envelope(decision)
    if trusted_sandbox_active() and grant_temporary_mount_for_current_tool(decision):
        return None
    return _path_access_required_envelope(decision, approval_id=approval_id)


def _sandbox_read_path_access_envelope(
    profile: OperationProfile,
    workdir: str | None,
    *,
    approval_id: str | None = None,
) -> dict[str, object] | None:
    if not profile.requested_paths or not _sandbox_path_access_enabled():
        return None
    for raw_path in profile.requested_paths:
        decision = decide_path_access(
            _resolve_shell_write_target(raw_path, workdir),
            workspace=_workspace_root_for_path_access(),
            mounts=_active_sandbox_mounts(),
            write=False,
        )
        if decision.status == "allowed":
            continue
        if decision.status == "blocked":
            return _path_access_blocked_envelope(decision)
        if trusted_sandbox_active() and grant_temporary_mount_for_current_tool(decision):
            continue
        return _path_access_required_envelope(decision, approval_id=approval_id)
    return None


def _sandbox_write_path_access_envelope(
    profile: OperationProfile,
    workdir: str | None,
    command: str,
    *,
    stdin: str | None = None,
    approval_id: str | None = None,
) -> dict[str, object] | None:
    write_paths = _shell_write_access_targets(command, profile, stdin=stdin)
    if not write_paths or not _sandbox_path_access_enabled():
        return None
    shell_file_targets = frozenset(_shell_write_targets_from_inputs(command, stdin))
    for raw_path in write_paths:
        decision = decide_path_access(
            _resolve_shell_write_target(raw_path, workdir),
            workspace=_workspace_root_for_path_access(),
            mounts=_active_sandbox_mounts(),
            write=True,
        )
        if decision.status == "allowed":
            continue
        if decision.status == "blocked":
            return _path_access_blocked_envelope(decision)
        if trusted_sandbox_active() and grant_temporary_mount_for_current_tool(
            decision,
            prefer_file=_shell_write_target_prefers_file(raw_path, shell_file_targets),
        ):
            continue
        return _path_access_required_envelope(decision, approval_id=approval_id)
    return None


def _shell_write_access_targets(
    command: str,
    profile: OperationProfile,
    *,
    stdin: str | None = None,
) -> tuple[str, ...]:
    targets: list[str] = []
    for target in (
        *_shell_write_targets_from_inputs(command, stdin),
        *getattr(profile, "requested_write_paths", ()),
    ):
        if target not in targets:
            targets.append(target)
    return tuple(targets)


def _shell_write_target_prefers_file(
    raw_target: str,
    shell_file_targets: frozenset[str],
) -> bool:
    if raw_target in shell_file_targets:
        return True
    cleaned = raw_target.strip().strip("'\"")
    return bool(ntpath.splitext(cleaned)[1] or Path(cleaned).suffix)


def _resolve_shell_write_target(raw_target: str, workdir: str | None) -> Path:
    cleaned = raw_target.strip().strip("'\"")
    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        base = Path(workdir).expanduser() if workdir else Path.cwd()
        path = base / path
    return path.resolve(strict=False)


def _shell_target_is_relative(raw_target: str) -> bool:
    cleaned = raw_target.strip().strip("'\"")
    if not cleaned:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", cleaned):
        return False
    return not Path(cleaned).expanduser().is_absolute()


def _basic_shell_write_targets(command: str) -> list[str]:
    targets: list[str] = []
    redirection_pattern = r"(?:^|\s)(?:\d?>{1,2}|&>{1,2})\s*(['\"]?)([^'\"\s|&;]+)\1"
    targets.extend(match.group(2) for match in re.finditer(redirection_pattern, command))
    tee_pattern = r"(?:^|\s)tee(?:\s+-[A-Za-z]+)*\s+(['\"]?)([^'\"\s|&;]+)\1"
    targets.extend(match.group(2) for match in re.finditer(tee_pattern, command))
    return targets


def _shell_write_targets(command: str) -> list[str]:
    targets = _basic_shell_write_targets(command)
    if _windows_sandbox_backend_active():
        for target in _windows_shell_write_targets(command):
            if target not in targets:
                targets.append(target)
    return targets


def _shell_write_targets_from_inputs(command: str, stdin: str | None = None) -> list[str]:
    targets = _shell_write_targets(command)
    if stdin is not None:
        for stdin_chunk in _iter_stdin_guard_chunks(stdin):
            targets.extend(_shell_write_targets(stdin_chunk))
    return targets


def _shell_workdir_requires_write(
    command: str,
    profile: OperationProfile,
    stdin: str | None = None,
) -> bool:
    for target in _shell_write_targets_from_inputs(command, stdin):
        if _shell_target_is_relative(target):
            return True
    for target in getattr(profile, "requested_write_paths", ()):
        if _shell_target_is_relative(str(target)):
            return True
    return False


def _workspace_lockdown_shell_block(
    tool_name: str,
    command: str,
    workdir: str | None,
    *,
    stdin: str | None = None,
) -> dict[str, object] | None:
    roots = _workspace_lockdown_roots()
    if not roots:
        return None
    for target in _shell_write_targets_from_inputs(command, stdin):
        resolved = _resolve_shell_write_target(target, workdir)
        if _path_inside_any_root(resolved, roots):
            continue
        return {
            "status": "blocked",
            "reason": "workspace_lockdown",
            "tool": tool_name,
            "command": command,
            "target": target,
            "resolved_path": str(resolved),
            "allowed_roots": [str(root) for root in roots],
            "message": (
                f"{tool_name} blocked by workspace lockdown: shell write target "
                f"{resolved} is outside allowed roots."
            ),
            "retryable": False,
        }
    return None


def _windows_runtime_readonly_shell_block(
    tool_name: str,
    command: str,
    workdir: str | None,
    *,
    stdin: str | None = None,
) -> dict[str, object] | None:
    roots = _windows_runtime_readonly_roots()
    if not roots:
        return None
    for target in _shell_write_targets_from_inputs(command, stdin):
        resolved = _resolve_shell_write_target(target, workdir)
        candidate = resolved.expanduser().resolve(strict=False)
        for root in roots:
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            return {
                "status": "blocked",
                "reason": "runtime_readonly",
                "tool": tool_name,
                "command": command,
                "target": target,
                "resolved_path": str(candidate),
                "readonly_root": str(root),
                "message": (
                    f"{tool_name} blocked by sandbox runtime read-only policy: "
                    f"shell write target {candidate} is under read-only runtime root {root}."
                ),
                "retryable": False,
            }
    return None


def _workspace_write_deny_shell_block(
    tool_name: str,
    command: str,
    workdir: str | None,
    *,
    stdin: str | None = None,
) -> dict[str, object] | None:
    from opensquilla.tools.write_policy import (
        match_workspace_write_deny,
        workspace_write_deny_block,
    )

    ctx = current_tool_context.get()
    workspace = (
        Path(ctx.workspace_dir).expanduser().resolve(strict=False)
        if ctx is not None and ctx.workspace_dir
        else None
    )
    for target in _shell_write_targets_from_inputs(command, stdin):
        resolved = _resolve_shell_write_target(target, workdir)
        deny_match = match_workspace_write_deny(
            resolved,
            original_path=target,
            workspace=workspace,
            ctx=ctx,
        )
        if deny_match is not None:
            return workspace_write_deny_block(tool_name, deny_match, command=command)
    return None


def _approval_elevation_state() -> bool:
    return _host_once_current_call.get()


def _restore_approval_elevation(value: bool) -> None:
    _host_once_current_call.set(value)


def _resolve_exec_timeout(timeout: float | int | None) -> float:
    if timeout is None:
        return _DEFAULT_EXEC_TIMEOUT
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        return _DEFAULT_EXEC_TIMEOUT
    return max(0.01, min(value, _MAX_EXEC_TIMEOUT))


def _resolve_background_timeout(timeout: float | int | None) -> float:
    if timeout is None:
        return _DEFAULT_BACKGROUND_TIMEOUT
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        return _DEFAULT_BACKGROUND_TIMEOUT
    return max(0.01, min(value, _MAX_BACKGROUND_TIMEOUT))


def _effective_workdir(workdir: str | None) -> str | None:
    ctx = current_tool_context.get()
    if workdir:
        translated = (
            _windows_translate_posix_tmp_path(workdir)
            if _windows_sandbox_backend_active()
            else workdir
        )
        reject_foreign_host_path(translated, platform=os.name)
        raw = Path(translated).expanduser()
        if not raw.is_absolute() and ctx and ctx.workspace_dir:
            return str((Path(ctx.workspace_dir).expanduser().resolve() / raw).resolve())
        return str(raw.resolve())
    if ctx and ctx.workspace_dir:
        return str(Path(ctx.workspace_dir).expanduser().resolve())
    return None


def _bg_status(session: _BgSession) -> str:
    if session.killed:
        return "killed"
    if session.timed_out:
        return "timed_out"
    if session.done:
        return "done"
    return "running"


def _bg_session_payload(session: _BgSession) -> dict[str, object]:
    payload: dict[str, object] = {
        "session_id": session.session_id,
        "command": session.command,
        "status": _bg_status(session),
        "returncode": session.returncode,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "killed": session.killed,
        "timed_out": session.timed_out,
    }
    if session.local_urls:
        payload["local_urls"] = list(session.local_urls)
    return payload


def _local_server_urls_from_command(command: str) -> list[str]:
    urls: list[str] = []
    url_pattern = r"https?://(?:127\.0\.0\.1|localhost):\d{2,5}(?:/[^\s\"']*)?"
    for match in re.finditer(url_pattern, command):
        urls.append(match.group(0).rstrip(".,;)"))

    http_server = re.search(
        r"(?:^|[\s;&|])python(?:3(?:\.\d+)?)?\s+-m\s+http\.server(?:\s+(?P<port>\d{2,5}))?",
        command,
    )
    if http_server is not None:
        port = http_server.group("port") or "8000"
        urls.append(f"http://127.0.0.1:{port}/")

    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _background_process_result(session: _BgSession) -> str:
    lines = [
        f"session_id={session.session_id}",
        f"command: {session.command}",
        "status: running",
    ]
    if session.local_urls:
        lines.append("local_urls:")
        lines.extend(f"- {url}" for url in session.local_urls)
        lines.append(
            "note: If the user asked to view this in a browser, include the local URL "
            "in your reply."
        )
    return "\n".join(lines)


def _current_bg_context_is_admin() -> bool:
    ctx = current_tool_context.get()
    if ctx is None or not ctx.is_owner:
        return False
    if ctx.caller_kind in {CallerKind.CLI, CallerKind.WEB}:
        return True
    return ctx.caller_kind is CallerKind.CHANNEL and ctx.elevated in ("on", "bypass", "full")


def _current_bg_context_allows(session: _BgSession) -> bool:
    if _current_bg_context_is_admin():
        return True
    ctx = current_tool_context.get()
    if ctx is None or not ctx.session_key:
        return False
    return session.session_key is not None and session.session_key == ctx.session_key


def _iter_visible_bg_sessions() -> list[_BgSession]:
    visible: list[_BgSession] = []
    for session in _bg_sessions.values():
        if session.session_key is None:
            log.warning("shell.bg_session_untagged", session_id=session.session_id)
        if _current_bg_context_allows(session):
            visible.append(session)
    return visible


def _require_bg_session(session_id: str | None) -> _BgSession:
    if not session_id:
        raise ToolError("'session_id' required")
    session = _bg_sessions.get(session_id)
    if session is None:
        raise ToolError(f"Unknown process session: {session_id}")
    if not _current_bg_context_allows(session):
        raise ToolError(f"Process session not accessible: {session_id}")
    return session


async def _read_bg_output(session: _BgSession) -> None:
    stdout = session.process.stdout
    if stdout is None:
        return
    while chunk := await stdout.read(4096):
        session.output_lines.append(chunk.decode("utf-8", errors="replace"))


def _finalize_bg_session(session: _BgSession) -> None:
    session.returncode = session.process.returncode
    if session.ended_at is None:
        session.ended_at = time.time()
    session.done = True
    callbacks = list(session.cleanup_callbacks)
    session.cleanup_callbacks.clear()
    for callback in callbacks:
        with contextlib.suppress(Exception):
            callback()


async def _finalize_bg_session_async(session: _BgSession) -> None:
    _finalize_bg_session(session)
    callbacks = list(session.async_cleanup_callbacks)
    session.async_cleanup_callbacks.clear()
    for callback in callbacks:
        with contextlib.suppress(Exception):
            await callback()


def _signal_bg_process(session: _BgSession, sig: signal.Signals) -> None:
    proc = session.process
    if proc.returncode is not None:
        return
    if os.name == "posix":
        os_mod = cast(Any, os)
        try:
            os_mod.killpg(proc.pid, sig)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    if sig == signal.SIGTERM:
        proc.terminate()
    else:
        proc.kill()


async def _wait_bg_process(session: _BgSession, timeout: float) -> bool:
    try:
        await asyncio.wait_for(session.process.wait(), timeout=timeout)
    except TimeoutError:
        return False
    return True


async def _terminate_bg_session(session: _BgSession) -> None:
    if session.process.returncode is not None:
        return
    _signal_bg_process(session, signal.SIGTERM)
    if await _wait_bg_process(session, _BACKGROUND_TERMINATE_TIMEOUT):
        return
    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    _signal_bg_process(session, kill_signal)
    if not await _wait_bg_process(session, _BACKGROUND_KILL_TIMEOUT):
        log.warning("background_process_termination_timeout", session_id=session.session_id)


async def _wait_exec_process(proc: Any, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + max(0.0, timeout)
    while proc.returncode is None:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return proc.returncode is not None
        await asyncio.sleep(min(0.01, remaining))
    return True


def _signal_exec_process_tree(proc: Any, sig: signal.Signals) -> bool:
    if os.name == "posix":
        os_mod = cast(Any, os)
        try:
            os_mod.killpg(proc.pid, sig)
            return True
        except ProcessLookupError:
            return True
        except OSError:
            pass
    if proc.returncode is not None:
        return False
    if sig == signal.SIGTERM:
        proc.terminate()
    else:
        proc.kill()
    return True


async def _terminate_exec_process_tree(proc: Any) -> None:
    _signal_exec_process_tree(proc, signal.SIGTERM)
    if await _wait_exec_process(proc, _EXEC_TERMINATE_TIMEOUT):
        return
    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    _signal_exec_process_tree(proc, kill_signal)
    if not await _wait_exec_process(proc, _EXEC_KILL_TIMEOUT):
        log.warning("exec_command_termination_timeout", pid=proc.pid)


async def _write_exec_stdin(proc: Any, stdin_bytes: bytes | None) -> None:
    if stdin_bytes is None or proc.stdin is None:
        return
    try:
        for offset in range(0, len(stdin_bytes), _EXEC_STDIN_WRITE_CHUNK_BYTES):
            proc.stdin.write(stdin_bytes[offset : offset + _EXEC_STDIN_WRITE_CHUNK_BYTES])
            await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        if proc.stdin is not None and not proc.stdin.is_closing():
            proc.stdin.close()


async def _await_bg_output_task(output_task: asyncio.Task[None]) -> None:
    try:
        await asyncio.wait_for(output_task, timeout=_BACKGROUND_KILL_TIMEOUT)
    except TimeoutError:
        output_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await output_task


async def _run_host_shell_command(
    command: str,
    *,
    cwd: str | None,
    env: dict[str, str],
    stdin_bytes: bytes | None,
    effective_timeout: float,
) -> str:
    try:
        with tempfile.TemporaryFile() as output_file:
            subprocess_kwargs: dict[str, Any] = {
                "stdin": asyncio.subprocess.PIPE if stdin_bytes is not None else None,
                "stdout": output_file,
                "stderr": asyncio.subprocess.STDOUT,
                "cwd": cwd,
                "env": env,
            }
            if os.name == "posix":
                subprocess_kwargs["start_new_session"] = True
            else:
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                if creationflags:
                    subprocess_kwargs["creationflags"] = creationflags

            loop = asyncio.get_running_loop()
            deadline = loop.time() + effective_timeout
            timeout_result = f"[timeout after {effective_timeout}s]\ncommand: {command}"

            proc = await asyncio.create_subprocess_shell(command, **subprocess_kwargs)
            remaining = deadline - loop.time()
            if remaining <= 0:
                await _terminate_exec_process_tree(proc)
                return timeout_result
            try:
                await asyncio.wait_for(_write_exec_stdin(proc, stdin_bytes), timeout=remaining)
            except TimeoutError:
                await _terminate_exec_process_tree(proc)
                return timeout_result

            remaining = deadline - loop.time()
            if remaining <= 0 or not await _wait_exec_process(proc, remaining):
                await _terminate_exec_process_tree(proc)
                return timeout_result
            if os.name == "posix":
                _signal_exec_process_tree(proc, signal.SIGTERM)

            output_file.flush()
            output_file.seek(0)
            output = output_file.read().decode("utf-8", errors="replace")
            return f"exit_code={proc.returncode}\n{output}"
    except Exception as e:
        return f"[error] {e}"


@tool(
    name="exec_command",
    description="Execute a shell command and return stdout/stderr with exit code.",
    params={
        "command": {"type": "string", "description": "Shell command to execute."},
        "workdir": {"type": "string", "description": "Working directory (default: cwd)."},
        "timeout": {"type": "number", "description": "Timeout in seconds (default 60)."},
        "env": {
            "type": "object",
            "description": "Extra environment variable overrides.",
            "additionalProperties": {"type": "string"},
        },
        "stdin": {
            "type": "string",
            "description": "Data to write to the command's standard input.",
        },
        "approval_id": {
            "type": "string",
            "description": "Approval record to consume for warned commands.",
        },
    },
    required=["command"],
    execution_timeout_seconds=_DEFAULT_EXEC_TIMEOUT + _EXEC_TOOL_TIMEOUT_PADDING,
    execution_timeout_argument="timeout",
    execution_timeout_padding=_EXEC_TOOL_TIMEOUT_PADDING,
    sandbox=SandboxToolDescriptor.process(
        kind="shell.exec",
        argv_factory=lambda a: ("exec_command", str(a.get("command", ""))),
        cwd_factory=lambda a: a.get("workdir") if isinstance(a.get("workdir"), str) else None,
        env_factory=lambda a: a.get("env") if isinstance(a.get("env"), dict) else None,
        enforce=False,
        record_payload=False,
    ),
)
async def exec_command(
    command: str,
    workdir: str | None = None,
    timeout: float = _DEFAULT_EXEC_TIMEOUT,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    approval_id: str | None = None,
) -> str:
    import os

    runtime = get_runtime()
    windows_process_sandbox = _windows_sandbox_backend_active(runtime)
    if windows_process_sandbox:
        command = _windows_translate_posix_tmp_references(command)
        if workdir:
            workdir = _windows_translate_posix_tmp_path(workdir)

    result = check_safe_bin(command)
    cwd = _effective_workdir(workdir)
    profile = _profile_shell_command(command)

    # Denylist: hard-block, never bypassable
    if not result.allowed:
        raise ToolError(result.reason)

    sensitive_block = _sensitive_shell_block(
        "exec_command", command, workdir=cwd, stdin=stdin
    )
    if sensitive_block is not None:
        return sensitive_block
    runtime_readonly_block = _windows_runtime_readonly_shell_block(
        "exec_command", command, cwd, stdin=stdin
    )
    if runtime_readonly_block is not None:
        return json.dumps(runtime_readonly_block, ensure_ascii=False)
    path_access = _sandbox_workdir_access_envelope(
        cwd,
        write=_shell_workdir_requires_write(command, profile, stdin=stdin),
        approval_id=approval_id,
    )
    if path_access is not None:
        return json.dumps(path_access, ensure_ascii=False)
    path_access = _sandbox_read_path_access_envelope(profile, cwd, approval_id=approval_id)
    if path_access is not None:
        return json.dumps(path_access, ensure_ascii=False)
    path_access = _sandbox_write_path_access_envelope(
        profile,
        cwd,
        command,
        stdin=stdin,
        approval_id=approval_id,
    )
    if path_access is not None:
        return json.dumps(path_access, ensure_ascii=False)
    lockdown_block = _workspace_lockdown_shell_block(
        "exec_command", command, cwd, stdin=stdin
    )
    if lockdown_block is not None:
        return json.dumps(lockdown_block, ensure_ascii=False)
    deny_block = _workspace_write_deny_shell_block(
        "exec_command", command, cwd, stdin=stdin
    )
    if deny_block is not None:
        return json.dumps(deny_block, ensure_ascii=False)

    # Warnlist: two-step approval flow
    if result.needs_approval:
        approval_response = await _check_exec_approval(
            tool_name="exec_command",
            command=command,
            workdir=cwd,
            warning=result.reason,
            approval_id=approval_id,
            background=False,
        )
        if approval_response is not None:
            status = approval_response.get("status")
            if status == "approval_denied":
                await _record_shell_denial(
                    "exec_command", command, workdir, DenialReason.HUMAN_REJECTED
                )
            return json.dumps(approval_response)

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    effective_timeout = _resolve_exec_timeout(timeout)
    stdin_bytes = stdin.encode("utf-8") if stdin is not None else None

    host_execution = _host_execution_allowed()
    effective_timeout = _resolve_background_timeout(timeout)

    if runtime is not None and runtime.effective.sandbox_enabled and not host_execution:
        if windows_process_sandbox:
            _apply_windows_session_tmp_env(merged_env)
        decision, policy, request = await gate_action(
            action_kind="shell.exec",
            argv=("exec_command", command),
            cwd=_sandbox_shell_policy_cwd(cwd),
            env=merged_env,
            hints=_level_hints_for_shell_profile(
                profile,
                warnlist_handled=result.needs_approval,
            ),
        )
        if isinstance(decision, DenialResult):
            return json.dumps(decision.to_dict())
        backend_cwd = _sandbox_shell_backend_cwd(cwd, request)
        backend_policy = request.policy
        backend_policy = _policy_with_active_tool_mounts(backend_policy)
        backend_policy = _policy_with_windows_shell_runtime_mounts(backend_policy, runtime)
        backend_policy = _policy_with_wall_timeout(backend_policy, effective_timeout)
        backend_request = SandboxRequest(
            argv=_sandbox_shell_backend_argv(command, runtime, cwd=backend_cwd),
            cwd=backend_cwd,
            action_kind=request.action_kind,
            policy=backend_policy,
            stdin=stdin_bytes,
            env=dict(merged_env),
            reason=getattr(request, "reason", ""),
            session_id=getattr(request, "session_id", ""),
            run_mode=getattr(request, "run_mode", ""),
        )
        preflight = await preflight_subprocess_managed_network(backend_request, runtime)
        if isinstance(preflight, DenialResult):
            return json.dumps(preflight.to_dict())
        if isinstance(preflight, dict):
            return json.dumps(preflight)
        try:
            sandbox_result = await _run_backend_with_managed_network(
                backend_request,
                runtime=runtime,
            )
        except Exception as exc:
            raise ToolError(f"Sandboxed shell execution failed: {exc}") from exc
        if sandbox_result.backend_notes:
            retry_request = _trusted_path_recovery_retry_request(
                command,
                backend_request,
                sandbox_result.backend_notes,
                write_default=_shell_workdir_requires_write(command, profile, stdin=stdin),
            )
            if retry_request is not None:
                try:
                    sandbox_result = await _run_backend_with_managed_network(
                        retry_request,
                        runtime=runtime,
                    )
                except Exception as exc:
                    raise ToolError(f"Sandboxed shell execution failed: {exc}") from exc
                backend_request = retry_request
            if sandbox_result.backend_notes:
                escalation = await escalate_backend_denial(
                    sandbox_result, request, policy, runtime=runtime
                )
                if isinstance(escalation, DenialResult):
                    return json.dumps(escalation.to_dict())
                raise ToolError("Sandboxed shell execution denied; host fallback disabled")
        output = sandbox_result.stdout
        if sandbox_result.stderr:
            output += sandbox_result.stderr
        failure = classify_network_failure(output) if sandbox_result.returncode != 0 else None
        if (
            failure is not None
            and backend_request.policy.network is not NetworkMode.PROXY_ALLOWLIST
        ):
            capability_profile = capability_profile_for_command(("sh", "-lc", command))
            network_class = network_class_for_failure(
                failure.host,
                profile=capability_profile,
                default=NetworkTargetClass.UNKNOWN_PUBLIC,
                explicit_hosts=explicit_network_hosts_from_command(command),
            )
            recovery_decision = decide_dev_recovery(
                _context_run_mode() or "standard",
                capability_profile,
                PathTargetClass.NORMAL_USER_PATH,
                network_class,
            )
            if (
                recovery_decision.kind is DevPolicyDecisionKind.AUTO
                and recovery_decision.retry_once
            ):
                log.info(
                    "shell_runtime_recovery",
                    command=_audit_command(command),
                    decision=recovery_decision.kind.value,
                    reason=recovery_decision.reason,
                    run_mode=_context_run_mode(),
                )
                retry_request = backend_request
                if (
                    recovery_decision.use_managed_proxy
                    and retry_request.policy.network is not NetworkMode.PROXY_ALLOWLIST
                ):
                    retry_request = retry_request.with_policy(
                        dataclasses.replace(
                            retry_request.policy,
                            network=NetworkMode.PROXY_ALLOWLIST,
                            network_proxy=None,
                        )
                    )
                preflight = await preflight_subprocess_managed_network(
                    retry_request,
                    runtime,
                    consume_temporary_grants=False,
                )
                if isinstance(preflight, DenialResult):
                    return json.dumps(preflight.to_dict())
                if isinstance(preflight, dict):
                    return json.dumps(preflight)
                managed_network = await prepare_subprocess_managed_network_proxy(
                    retry_request,
                    runtime=runtime,
                )
                try:
                    sandbox_result = await run_under_backend(
                        managed_network.request,
                        runtime=runtime,
                    )
                except Exception as exc:
                    raise ToolError(f"Sandboxed shell execution failed: {exc}") from exc
                finally:
                    await managed_network.cleanup()
                output = sandbox_result.stdout
                if sandbox_result.stderr:
                    output += sandbox_result.stderr
            elif (
                recovery_decision.kind is DevPolicyDecisionKind.ASK
                and recovery_decision.use_managed_proxy
            ):
                log.info(
                    "shell_runtime_recovery",
                    command=_audit_command(command),
                    decision=recovery_decision.kind.value,
                    reason=recovery_decision.reason,
                    run_mode=_context_run_mode(),
                )
                approval_request = backend_request
                if approval_request.policy.network is not NetworkMode.PROXY_ALLOWLIST:
                    approval_request = approval_request.with_policy(
                        dataclasses.replace(
                            approval_request.policy,
                            network=NetworkMode.PROXY_ALLOWLIST,
                            network_proxy=None,
                        )
                    )
                preflight = await preflight_subprocess_managed_network(
                    approval_request,
                    runtime,
                    consume_temporary_grants=False,
                )
                if isinstance(preflight, DenialResult):
                    return json.dumps(preflight.to_dict())
                if isinstance(preflight, dict):
                    return json.dumps(preflight)
                managed_network = await prepare_subprocess_managed_network_proxy(
                    approval_request,
                    runtime=runtime,
                )
                try:
                    sandbox_result = await run_under_backend(
                        managed_network.request,
                        runtime=runtime,
                    )
                except Exception as exc:
                    raise ToolError(f"Sandboxed shell execution failed: {exc}") from exc
                finally:
                    await managed_network.cleanup()
                output = sandbox_result.stdout
                if sandbox_result.stderr:
                    output += sandbox_result.stderr
        output = _append_sandbox_network_hint(output)
        return f"exit_code={sandbox_result.returncode}\n{output}"

    if host_execution:
        log.info("shell_exec_host", command=_audit_command(command), run_mode=_context_run_mode())

    return await _run_host_shell_command(
        command,
        cwd=cwd,
        env=merged_env,
        stdin_bytes=stdin_bytes,
        effective_timeout=effective_timeout,
    )


@tool(
    name="background_process",
    description="Run a shell command in the background. Returns a session_id for polling.",
    params={
        "command": {"type": "string", "description": "Shell command to run in background."},
        "workdir": {"type": "string", "description": "Working directory (default: cwd)."},
        "timeout": {
            "type": "number",
            "description": "Timeout in seconds (default 1800, max 3600).",
        },
        "approval_id": {
            "type": "string",
            "description": "Approval record to consume for warned commands.",
        },
    },
    required=["command"],
    sandbox=SandboxToolDescriptor.process(
        kind="shell.background",
        argv_factory=lambda a: ("background_process", str(a.get("command", ""))),
        cwd_factory=lambda a: a.get("workdir") if isinstance(a.get("workdir"), str) else None,
        enforce=False,
        record_payload=False,
    ),
)
async def background_process(
    command: str,
    workdir: str | None = None,
    timeout: float = _DEFAULT_BACKGROUND_TIMEOUT,
    approval_id: str | None = None,
) -> str:
    runtime = get_runtime()
    windows_process_sandbox = _windows_sandbox_backend_active(runtime)
    if windows_process_sandbox:
        command = _windows_translate_posix_tmp_references(command)
        if workdir:
            workdir = _windows_translate_posix_tmp_path(workdir)

    result = check_safe_bin(command)
    cwd = _effective_workdir(workdir)
    profile = _profile_shell_command(command)
    if not result.allowed:
        raise ToolError(result.reason)
    sensitive_block = _sensitive_shell_block("background_process", command, workdir=cwd)
    if sensitive_block is not None:
        return sensitive_block
    runtime_readonly_block = _windows_runtime_readonly_shell_block(
        "background_process", command, cwd
    )
    if runtime_readonly_block is not None:
        return json.dumps(runtime_readonly_block, ensure_ascii=False)
    path_access = _sandbox_workdir_access_envelope(
        cwd,
        write=_shell_workdir_requires_write(command, profile),
        approval_id=approval_id,
    )
    if path_access is not None:
        return json.dumps(path_access, ensure_ascii=False)
    path_access = _sandbox_read_path_access_envelope(profile, cwd, approval_id=approval_id)
    if path_access is not None:
        return json.dumps(path_access, ensure_ascii=False)
    path_access = _sandbox_write_path_access_envelope(
        profile,
        cwd,
        command,
        approval_id=approval_id,
    )
    if path_access is not None:
        return json.dumps(path_access, ensure_ascii=False)
    lockdown_block = _workspace_lockdown_shell_block("background_process", command, cwd)
    if lockdown_block is not None:
        return json.dumps(lockdown_block, ensure_ascii=False)
    deny_block = _workspace_write_deny_shell_block("background_process", command, cwd)
    if deny_block is not None:
        return json.dumps(deny_block, ensure_ascii=False)
    if result.needs_approval:
        prior_elevation = _approval_elevation_state()
        approval_response: dict[str, object] | None = None
        approval_granted = False
        try:
            approval_response = await _check_exec_approval(
                tool_name="background_process",
                command=command,
                workdir=cwd,
                warning=result.reason,
                approval_id=approval_id,
                background=True,
            )
            approval_granted = approval_response is None and _approval_elevation_state()
        finally:
            if not approval_granted:
                _restore_approval_elevation(prior_elevation)
        if approval_response is not None:
            status = approval_response.get("status")
            if status == "approval_denied":
                await _record_shell_denial(
                    "background_process", command, workdir, DenialReason.HUMAN_REJECTED
                )
            return json.dumps(approval_response)

    host_execution = _host_execution_allowed()
    effective_timeout = _resolve_background_timeout(timeout)

    if runtime is not None and runtime.effective.sandbox_enabled and not host_execution:
        merged_env = dict(os.environ)
        if windows_process_sandbox:
            _apply_windows_session_tmp_env(merged_env)
        decision, policy, request = await gate_action(
            action_kind="shell.background",
            argv=("background_process", command),
            cwd=_sandbox_shell_policy_cwd(cwd),
            env=merged_env,
            hints=_level_hints_for_shell_profile(
                profile,
                warnlist_handled=result.needs_approval,
            ),
        )
        if isinstance(decision, DenialResult):
            return json.dumps(decision.to_dict())
        backend_cwd = _sandbox_shell_backend_cwd(cwd, request)
        backend_policy = policy
        backend_policy = _policy_with_active_tool_mounts(backend_policy)
        backend_policy = _policy_with_windows_shell_runtime_mounts(backend_policy, runtime)
        backend_policy = _policy_with_wall_timeout(backend_policy, effective_timeout)
        backend_request = SandboxRequest(
            argv=_sandbox_shell_backend_argv(command, runtime, cwd=backend_cwd),
            cwd=backend_cwd,
            action_kind=request.action_kind,
            policy=backend_policy,
            env=merged_env,
            session_id=getattr(request, "session_id", ""),
            run_mode=getattr(request, "run_mode", ""),
        )
        preflight = await preflight_subprocess_managed_network(backend_request, runtime)
        if isinstance(preflight, DenialResult):
            return json.dumps(preflight.to_dict())
        if isinstance(preflight, dict):
            return json.dumps(preflight)
        managed_network = await prepare_subprocess_managed_network_proxy(
            backend_request,
            runtime=runtime,
        )
        try:
            spawned = await _spawn_sandboxed_background_process(
                runtime=runtime,
                request=managed_network.request,
            )
        except Exception:
            await managed_network.cleanup()
            raise
        session_id = str(uuid.uuid4())[:8]
        ctx = current_tool_context.get()
        session = _BgSession(
            session_id=session_id,
            command=command,
            process=spawned.process,
            session_key=ctx.session_key if ctx is not None else None,
            agent_id=ctx.agent_id if ctx is not None else None,
            is_owner_run=bool(ctx.is_owner) if ctx is not None else False,
            local_urls=_local_server_urls_from_command(command),
            cleanup_callbacks=spawned.cleanup_callbacks,
            async_cleanup_callbacks=[
                *spawned.async_cleanup_callbacks,
                managed_network.cleanup,
            ],
        )
        _bg_sessions[session_id] = session
        async def _collect_restricted() -> None:
            output_task = asyncio.create_task(_read_bg_output(session))
            try:
                await asyncio.wait_for(spawned.process.wait(), timeout=effective_timeout)
            except TimeoutError:
                session.timed_out = True
                await _terminate_bg_session(session)
                session.output_lines.append(f"[timeout after {effective_timeout}s]\n")
            finally:
                await _await_bg_output_task(output_task)
                await _finalize_bg_session_async(session)

        session.collector_task = asyncio.create_task(_collect_restricted())
        return _background_process_result(session)

    if host_execution:
        log.info(
            "background_process_host",
            command=_audit_command(command),
            run_mode=_context_run_mode(),
        )

    session_id = str(uuid.uuid4())[:8]

    if os.name == "posix":
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=os.environ.copy(),
            start_new_session=True,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=os.environ.copy(),
        )

    ctx = current_tool_context.get()
    session = _BgSession(
        session_id=session_id,
        command=command,
        process=proc,
        session_key=ctx.session_key if ctx is not None else None,
        agent_id=ctx.agent_id if ctx is not None else None,
        is_owner_run=bool(ctx.is_owner) if ctx is not None else False,
        local_urls=_local_server_urls_from_command(command),
    )
    _bg_sessions[session_id] = session

    async def _collect_host() -> None:
        output_task = asyncio.create_task(_read_bg_output(session))
        try:
            await asyncio.wait_for(proc.wait(), timeout=effective_timeout)
        except TimeoutError:
            session.timed_out = True
            await _terminate_bg_session(session)
            session.output_lines.append(f"[timeout after {effective_timeout}s]\n")
        finally:
            await _await_bg_output_task(output_task)
            await _finalize_bg_session_async(session)

    session.collector_task = asyncio.create_task(_collect_host())

    return _background_process_result(session)


async def _spawn_sandboxed_background_process(
    *,
    runtime,
    request: SandboxRequest,
) -> _SpawnedBackgroundProcess:
    backend = runtime.backend
    if isinstance(backend, BubblewrapBackend):
        argv = build_bwrap_argv(request)
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        return _SpawnedBackgroundProcess(process=process)
    if isinstance(backend, NoopBackend):
        process = await asyncio.create_subprocess_exec(
            *request.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(request.cwd),
            env=request.env,
            start_new_session=True,
        )
        return _SpawnedBackgroundProcess(process=process)
    if isinstance(backend, SeatbeltBackend):
        tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
        profile_path: Path | None = None

        def cleanup() -> None:
            if profile_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(profile_path)
            if tmp_ctx is not None:
                tmp_ctx.cleanup()

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
            argv = build_seatbelt_argv(request, profile_path)
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(request.cwd),
                env=request.env,
                start_new_session=True,
            )
            return _SpawnedBackgroundProcess(process=process, cleanup_callbacks=[cleanup])
        except Exception:
            cleanup()
            raise
    raise ToolError(f"Sandbox backend {backend.name!r} does not support background shell")


def get_bg_session(session_id: str) -> _BgSession | None:
    session = _bg_sessions.get(session_id)
    if session is None or not _current_bg_context_allows(session):
        return None
    return session


@tool(
    name="process",
    description="Manage background_process sessions created by OpenSquilla.",
    params={
        "action": {
            "type": "string",
            "description": "Action: list, poll, log, kill, remove, write, submit, eof.",
        },
        "session_id": {
            "type": "string",
            "description": "Target background_process session id.",
        },
        "sessionId": {
            "type": "string",
            "description": "Compatibility alias for session_id.",
        },
        "data": {
            "type": "string",
            "description": "Data to write to stdin. submit appends a newline.",
        },
        "offset": {
            "type": "integer",
            "description": "For log, character offset to start reading from.",
        },
        "limit": {
            "type": "integer",
            "description": "For log, maximum characters to return.",
        },
    },
    required=["action"],
    sandbox=SandboxToolDescriptor.custom(kind="process", enforce=False),
)
async def process(
    action: str,
    session_id: str | None = None,
    sessionId: str | None = None,  # noqa: N803 - legacy camelCase alias.
    data: str | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    if action == "list":
        sessions = [_bg_session_payload(session) for session in _iter_visible_bg_sessions()]
        return json.dumps({"status": "ok", "action": action, "sessions": sessions})

    resolved_session_id = session_id or sessionId
    session = _require_bg_session(resolved_session_id)

    if action == "poll":
        return json.dumps(
            {"status": "ok", "action": action, "session": _bg_session_payload(session)}
        )

    if action == "log":
        output = "".join(session.output_lines)
        start = max(0, int(offset or 0))
        requested_limit = 20000 if limit is None else int(limit)
        max_chars = max(0, min(requested_limit, 100000))
        end = start + max_chars
        sliced = output[start:end]
        return json.dumps(
            {
                "status": "ok",
                "action": action,
                "session": _bg_session_payload(session),
                "output": sliced,
                "offset": start,
                "limit": max_chars,
                "truncated": start > 0 or end < len(output),
            }
        )

    if action == "kill":
        if session.done or session.process.returncode is not None:
            if session.collector_task is not None and not session.collector_task.done():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(session.collector_task),
                        timeout=_BACKGROUND_KILL_TIMEOUT,
                    )
            if not session.done:
                await _finalize_bg_session_async(session)
            status = _bg_status(session)
            return json.dumps(
                {
                    "status": status,
                    "action": action,
                    "session_id": session.session_id,
                    "session": _bg_session_payload(session),
                }
            )

        if session.process.returncode is None:
            session.killed = True
            await _terminate_bg_session(session)
        if session.collector_task is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(session.collector_task),
                    timeout=_BACKGROUND_KILL_TIMEOUT,
                )
        if not session.done:
            await _finalize_bg_session_async(session)
        status = _bg_status(session)
        return json.dumps(
            {
                "status": status,
                "action": action,
                "session_id": session.session_id,
                "session": _bg_session_payload(session),
            }
        )

    if action == "remove":
        if not session.done:
            raise ToolError(f"Cannot remove running session: {session.session_id}")
        del _bg_sessions[session.session_id]
        return json.dumps({"status": "removed", "action": action, "session_id": session.session_id})

    if action in {"write", "submit"}:
        if data is None:
            raise ToolError("'data' required")
        if session.done:
            raise ToolError(f"Cannot write to completed session: {session.session_id}")
        stdin = session.process.stdin
        if stdin is None or stdin.is_closing():
            raise ToolError(f"Session stdin is closed: {session.session_id}")
        write_data = data if action == "write" else f"{data}\n"
        encoded = write_data.encode("utf-8")
        try:
            stdin.write(encoded)
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ToolError(f"Session stdin is closed: {session.session_id}") from exc
        return json.dumps(
            {
                "status": "written" if action == "write" else "submitted",
                "action": action,
                "session_id": session.session_id,
                "bytes": len(encoded),
                "session": _bg_session_payload(session),
            }
        )

    if action == "eof":
        stdin = session.process.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()
            wait_closed = getattr(stdin, "wait_closed", None)
            if wait_closed is not None:
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await wait_closed()
        return json.dumps(
            {
                "status": "eof",
                "action": action,
                "session_id": session.session_id,
                "session": _bg_session_payload(session),
            }
        )

    raise ToolError("Invalid action: list|poll|log|kill|remove|write|submit|eof")


def _sandbox_request_for(
    tool_name: str, command: str, workdir: str | None
) -> tuple[SandboxRequest, SandboxPolicy, str] | None:
    """Build a SandboxRequest for the current shell command.

    Returns ``None`` when the sandbox runtime is not configured (tests that
    don't boot the gateway) so callers skip the §8.3/§8.5 hooks cleanly.
    """
    runtime = get_runtime()
    if runtime is None:
        return None
    action_kind = "shell.background" if tool_name == "background_process" else "shell.exec"
    ctx = current_tool_context.get()
    workspace = None
    if workdir:
        p = Path(workdir)
        if p.is_absolute():
            workspace = p
    if workspace is None and ctx is not None and ctx.workspace_dir:
        wp = Path(ctx.workspace_dir)
        if wp.is_absolute():
            workspace = wp
    if workspace is None:
        workspace = runtime.workspace if runtime.workspace.is_absolute() else Path.cwd()

    level = (
        select_level(action_kind)
        if runtime.effective.grading_enabled
        else runtime.effective.default_level
    )
    policy = build_policy(level, action_kind, workspace, runtime.settings, trusted=True)
    request = build_request(
        action_kind=action_kind,
        argv=(tool_name, command),
        cwd=workspace,
        policy=policy,
    )
    session_id = str(ctx.session_key) if ctx and ctx.session_key else "default"
    return request, policy, session_id


async def _record_shell_denial(
    tool_name: str, command: str, workdir: str | None, reason: DenialReason
) -> None:
    """Record a shell-layer denial into the sandbox ledger for §8.3/§8.5.

    Silently no-ops when the runtime is not configured. Failure to record
    is logged but never propagated — we prefer a missed bookkeeping entry
    over a new failure mode in the shell tool.
    """
    runtime = get_runtime()
    if runtime is None:
        return
    built = _sandbox_request_for(tool_name, command, workdir)
    if built is None:
        return
    request, _, session_id = built
    try:
        await runtime.ledger.record_denial(session_id, action_fingerprint(request), reason)
    except Exception:  # pragma: no cover - bookkeeping only
        log.exception("shell.denial_record_failed", command=_audit_command(command))


def _wait_for_inline_browser_approval(background: bool) -> bool:
    """Return True when the caller has an out-of-band browser approval UI.

    CLI/TUI approval prompts are driven by the ``approval_required`` tool result,
    so the first call must return immediately there. The Web UI polls the shared
    approval queue independently, which lets the tool call wait and continue as
    soon as the operator clicks Approve.
    """
    if background:
        return False
    ctx = current_tool_context.get()
    return ctx is not None and ctx.caller_kind is CallerKind.WEB


async def _check_exec_approval(
    tool_name: str,
    command: str,
    workdir: str | None,
    warning: str,
    approval_id: str | None,
    background: bool,
) -> dict[str, object] | None:
    queue = get_approval_queue()
    settings = queue.get_settings()
    ctx = current_tool_context.get()
    params = {
        "toolName": tool_name,
        "command": command,
        "args": {"command": command, "workdir": workdir},
        "sessionKey": ctx.session_key if ctx is not None and ctx.session_key else "",
        "agent": ctx.agent_id if ctx is not None else "",
        "mode": "background" if background else "foreground",
    }

    run_mode = _context_run_mode()
    run_mode_full = run_mode == "full"
    run_mode_trusted = run_mode == "trusted"
    sandbox_off_requires_approval = _sandbox_effectively_off() and not run_mode_full

    # Sensitive-path hard block. Only /elevated full bypasses; ordinary
    # approval cannot override.
    if not run_mode_full:
        from opensquilla.sandbox.sensitive_paths import (
            build_block_envelope,
            sensitive_target_in_command,
        )

        sensitive = sensitive_target_in_command(
            command,
            workspace=ctx.workspace_dir if ctx is not None else None,
            cwd=workdir,
        )
        if sensitive is not None:
            log.warning(
                "shell_sensitive_path_blocked",
                command=_audit_command(command),
                tool=tool_name,
                sensitive=sensitive,
            )
            return build_block_envelope(command, sensitive, tool_name=tool_name)

    lockdown_block = _workspace_lockdown_shell_block(tool_name, command, workdir)
    if lockdown_block is not None:
        log.warning(
            "shell_workspace_lockdown_blocked",
            command=_audit_command(command),
            tool=tool_name,
            resolved_path=lockdown_block.get("resolved_path"),
        )
        return lockdown_block

    deny_block = _workspace_write_deny_shell_block(tool_name, command, workdir)
    if deny_block is not None:
        log.warning(
            "shell_workspace_write_deny_blocked",
            command=_audit_command(command),
            tool=tool_name,
            resolved_path=deny_block.get("resolved_path"),
            matched_pattern=deny_block.get("matched_pattern"),
        )
        return deny_block

    # Full Host Access — trusted operator has taken explicit responsibility.
    # Approvals are skipped entirely and later execution is allowed on host.
    if run_mode_full:
        log.info(
            "shell_approval_skipped_run_mode_full",
            command=_audit_command(command),
            tool=tool_name,
        )
        return None

    # Trusted-Sandbox skips routine warnlist approval, while still executing
    # through the sandbox when the runtime has a backend enabled.
    if run_mode_trusted and not sandbox_off_requires_approval:
        log.info(
            "shell_approval_skipped_run_mode_trusted",
            command=_audit_command(command),
            tool=tool_name,
        )
        return None

    if settings.mode == "auto-deny":
        return {
            "status": "approval_denied",
            "approval_id": "",
            "command": command,
            "warning": warning,
            "message": "This command was denied by the active approval policy.",
        }

    if sandbox_off_requires_approval:
        log.warning(
            "shell_approval_forced_sandbox_off",
            command=_audit_command(command),
            tool=tool_name,
            mode=settings.mode,
            run_mode=run_mode,
        )

    if settings.mode == "auto-approve" and not sandbox_off_requires_approval:
        return None

    if ctx is not None and ctx.interaction_mode is InteractionMode.UNATTENDED:
        raise UnsupportedSurfaceError(
            f"Tool '{tool_name}' requires human approval, but this run is unattended. "
            "Use an interactive surface for approval-gated operations, or choose an "
            "operation that does not require approval."
        )

    # Intent-level short-circuit: if the user already approved the same
    # destructive intent recently (e.g. rm /x, and now os.remove("/x")),
    # skip the queue entirely. Keeps paraphrased retries from re-prompting.
    if approval_id is None and not sandbox_off_requires_approval:
        from opensquilla.sandbox.intent_cache import get_intent_cache

        if get_intent_cache().check(command):
            log.info(
                "shell_approval_intent_cached",
                command=_audit_command(command),
                tool=tool_name,
            )
            return None

    if approval_id is None:
        approval_id = queue.request(namespace="exec", params=params)
        if _wait_for_inline_browser_approval(background):
            try:
                await queue.wait(approval_id, timeout=_APPROVAL_RETRY_WAIT_SECONDS)
            except TimeoutError:
                pass
            entry = queue.get(approval_id)
            if entry.approved:
                try:
                    queue.consume(approval_id)
                except ValueError as exc:
                    raise ToolError(str(exc)) from exc
                log.info(
                    "shell_approval_granted",
                    approval_id=approval_id,
                    command=_audit_command(command),
                    inline=True,
                )
                return None
            return {
                "status": "approval_denied",
                "approval_id": approval_id,
                "command": command,
                "warning": warning,
                "message": "Approval was denied or timed out.",
            }
        status = "approval_required"
        message = (
            "Resolve this approval via exec.approval.resolve and retry with the returned "
            "approval_id."
        )
        log.warning(
            "shell_approval_required",
            command=_audit_command(command),
            pattern=warning,
            approval_id=approval_id,
            mode=settings.mode,
        )
        return {
            "status": status,
            "approval_id": approval_id,
            "command": command,
            "warning": warning,
            "message": message,
        }

    try:
        entry = queue.get(approval_id)
    except KeyError as exc:
        raise ToolError(str(exc)) from exc
    if entry.namespace != "exec":
        raise ToolError(f"Approval does not belong to exec namespace: {approval_id}")
    if entry.params.get("toolName") != tool_name or entry.params.get("command") != command:
        raise ToolError("Approval does not match the requested command")
    if not entry.resolved:
        # Block the retry waiting for the user's decision instead of bouncing
        # back approval_pending — otherwise the model sees pending and pivots
        # to a different tool before the human finishes clicking approve.
        try:
            await queue.wait(approval_id, timeout=_APPROVAL_RETRY_WAIT_SECONDS)
        except TimeoutError:
            pass
        entry = queue.get(approval_id)
        if not entry.resolved:
            return {
                "status": "approval_pending",
                "approval_id": approval_id,
                "command": command,
                "warning": warning,
                "message": (
                    "Approval is still pending after waiting "
                    f"{int(_APPROVAL_RETRY_WAIT_SECONDS)}s. Ask the user to approve."
                ),
            }
    if not entry.approved:
        return {
            "status": "approval_denied",
            "approval_id": approval_id,
            "command": command,
            "warning": warning,
            "message": "Approval was denied.",
        }
    try:
        queue.consume(approval_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    log.info("shell_approval_granted", approval_id=approval_id, command=_audit_command(command))
    return None
