"""Shell built-in tools: exec_command, background_process, process."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
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
from opensquilla.sandbox.governance import action_fingerprint
from opensquilla.sandbox.integration import (
    build_request,
    escalate_backend_denial,
    gate_action,
    get_runtime,
    run_under_backend,
)
from opensquilla.sandbox.policy import build_policy, select_level
from opensquilla.sandbox.types import DenialReason, DenialResult, SandboxPolicy, SandboxRequest
from opensquilla.tools.builtin.shell_policy import check_safe_bin
from opensquilla.tools.path_policy import reject_foreign_host_path
from opensquilla.tools.registry import tool
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
_COMMAND_AUDIT_MAX_CHARS = 4096
_SANDBOX_NETWORK_HINT = (
    "Hint: sandboxed shell/code has no network. Use http_request or web_fetch, "
    "or run trusted benchmark work with --permissions bypass."
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


@dataclass(frozen=True)
class _SpawnedBackgroundProcess:
    process: asyncio.subprocess.Process
    cleanup_callbacks: list[Callable[[], None]] = field(default_factory=list)


# Task-local flag: set inside _check_exec_approval when the user actually
# approved (once / always / auto-approve / intent-cache). Implies
# "permission to run this specific call on the host", bypassing the sandbox
# backend for the current tool invocation. Does NOT leak to subsequent
# tool calls — contextvars are async-task scoped.
_elevate_current_call: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_elevate_current_call", default=False
)


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


def _sandbox_effectively_off() -> bool:
    runtime = get_runtime()
    effective = getattr(runtime, "effective", None) if runtime is not None else None
    return runtime is None or not bool(getattr(effective, "sandbox_enabled", False))


def _context_elevated_mode() -> str | None:
    ctx = current_tool_context.get()
    if ctx is None:
        return None
    if ctx.elevated in ("on", "bypass", "full"):
        return ctx.elevated
    if ctx.session_key:
        with contextlib.suppress(Exception):
            mode = get_approval_queue().get_elevated_mode(ctx.session_key)
            if mode in ("on", "bypass", "full"):
                ctx.elevated = mode
                return mode
    return None


def _elevated_mode() -> str | None:
    """Return the active elevation, preferring the per-call approval grant.

    Precedence (highest first):
    1. Approval-granted elevation (per-call contextvar)
    2. ``ToolContext.elevated`` (``/elevated on|full`` slash command)
    """
    if _elevate_current_call.get():
        _elevate_current_call.set(False)
        return "on"
    return _context_elevated_mode()


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


def _sensitive_shell_block(
    tool_name: str,
    command: str,
    *,
    workdir: str | None = None,
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

    from opensquilla.tools.builtin.web import (
        _sensitive_body_block,
        _sensitive_body_marker,
        _sensitive_url_marker,
    )

    for token in checked_text.split():
        stripped = token.strip("'\"")
        if stripped.startswith(("http://", "https://")):
            marker = _sensitive_url_marker(stripped)
            if marker is not None:
                return _sensitive_body_block(tool_name, marker)
    marker = _sensitive_body_marker(checked_text)
    if marker is not None:
        return _sensitive_body_block(tool_name, marker)
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


def _resolve_shell_write_target(raw_target: str, workdir: str | None) -> Path:
    cleaned = raw_target.strip().strip("'\"")
    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        base = Path(workdir).expanduser() if workdir else Path.cwd()
        path = base / path
    return path.resolve(strict=False)


def _shell_write_targets(command: str) -> list[str]:
    targets: list[str] = []
    redirection_pattern = r"(?:^|\s)(?:\d?>{1,2}|&>{1,2})\s*(['\"]?)([^'\"\s|&;]+)\1"
    targets.extend(match.group(2) for match in re.finditer(redirection_pattern, command))
    tee_pattern = r"(?:^|\s)tee(?:\s+-[A-Za-z]+)*\s+(['\"]?)([^'\"\s|&;]+)\1"
    targets.extend(match.group(2) for match in re.finditer(tee_pattern, command))
    return targets


def _workspace_lockdown_shell_block(
    tool_name: str,
    command: str,
    workdir: str | None,
) -> dict[str, object] | None:
    roots = _workspace_lockdown_roots()
    if not roots:
        return None
    for target in _shell_write_targets(command):
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


def _workspace_write_deny_shell_block(
    tool_name: str,
    command: str,
    workdir: str | None,
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
    for target in _shell_write_targets(command):
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
    return _elevate_current_call.get()


def _restore_approval_elevation(value: bool) -> None:
    _elevate_current_call.set(value)


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
        reject_foreign_host_path(workdir, platform=os.name)
        raw = Path(workdir).expanduser()
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


async def _await_bg_output_task(output_task: asyncio.Task[None]) -> None:
    try:
        await asyncio.wait_for(output_task, timeout=_BACKGROUND_KILL_TIMEOUT)
    except TimeoutError:
        output_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await output_task


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
        "approval_id": {
            "type": "string",
            "description": "Approval record to consume for warned commands.",
        },
    },
    required=["command"],
    execution_timeout_seconds=_DEFAULT_EXEC_TIMEOUT + _EXEC_TOOL_TIMEOUT_PADDING,
    execution_timeout_argument="timeout",
    execution_timeout_padding=_EXEC_TOOL_TIMEOUT_PADDING,
)
async def exec_command(
    command: str,
    workdir: str | None = None,
    timeout: float = _DEFAULT_EXEC_TIMEOUT,
    env: dict[str, str] | None = None,
    approval_id: str | None = None,
) -> str:
    import os

    result = check_safe_bin(command)
    cwd = _effective_workdir(workdir)

    # Denylist: hard-block, never bypassable
    if not result.allowed:
        raise ToolError(result.reason)

    sensitive_block = _sensitive_shell_block("exec_command", command, workdir=cwd)
    if sensitive_block is not None:
        return sensitive_block
    lockdown_block = _workspace_lockdown_shell_block("exec_command", command, cwd)
    if lockdown_block is not None:
        return json.dumps(lockdown_block, ensure_ascii=False)
    deny_block = _workspace_write_deny_shell_block("exec_command", command, cwd)
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

    # /elevated on|bypass|full — route exec around the sandbox backend so host
    # paths are actually reachable. Approval is still handled above (elevated
    # on still goes through approval; bypass and full skip it at
    # _check_exec_approval).
    elevated_bypass = _elevated_mode() in ("on", "bypass", "full")

    runtime = get_runtime()
    if runtime is not None and runtime.effective.sandbox_enabled and not elevated_bypass:
        decision, policy, request = await gate_action(
            action_kind="shell.exec",
            argv=("exec_command", command),
            cwd=Path(workdir) if workdir else None,
            env=merged_env,
        )
        if isinstance(decision, DenialResult):
            return json.dumps(decision.to_dict())
        backend_request = SandboxRequest(
            argv=("sh", "-lc", command),
            cwd=request.cwd,
            action_kind=request.action_kind,
            policy=request.policy,
            stdin=None,
            env=dict(merged_env),
            reason=request.reason,
        )
        try:
            sandbox_result = await run_under_backend(backend_request, runtime=runtime)
        except Exception as exc:
            raise ToolError(f"Sandboxed shell execution failed: {exc}") from exc
        if sandbox_result.backend_notes:
            escalation = await escalate_backend_denial(
                sandbox_result, request, policy, runtime=runtime
            )
            if isinstance(escalation, DenialResult):
                return json.dumps(escalation.to_dict())
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=cwd,
                    env=merged_env,
                )
                try:
                    stdout_bytes, _ = await asyncio.wait_for(
                        proc.communicate(), timeout=effective_timeout
                    )
                except TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    return f"[timeout after {effective_timeout}s]\ncommand: {command}"
                output = stdout_bytes.decode("utf-8", errors="replace")
                return f"exit_code={proc.returncode}\n{output}"
            except Exception as e:
                return f"[error] {e}"
        output = sandbox_result.stdout
        if sandbox_result.stderr:
            output += sandbox_result.stderr
        output = _append_sandbox_network_hint(output)
        return f"exit_code={sandbox_result.returncode}\n{output}"

    if elevated_bypass:
        log.info("shell_exec_elevated_host", command=_audit_command(command))

    try:
        with tempfile.TemporaryFile() as output_file:
            subprocess_kwargs: dict[str, Any] = {
                "stdout": output_file,
                "stderr": asyncio.subprocess.STDOUT,
                "cwd": cwd,
                "env": merged_env,
            }
            if os.name == "posix":
                subprocess_kwargs["start_new_session"] = True
            else:
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                if creationflags:
                    subprocess_kwargs["creationflags"] = creationflags

            proc = await asyncio.create_subprocess_shell(command, **subprocess_kwargs)
            if not await _wait_exec_process(proc, effective_timeout):
                await _terminate_exec_process_tree(proc)
                return f"[timeout after {effective_timeout}s]\ncommand: {command}"
            if os.name == "posix":
                _signal_exec_process_tree(proc, signal.SIGTERM)

            output_file.flush()
            output_file.seek(0)
            output = output_file.read().decode("utf-8", errors="replace")
            return f"exit_code={proc.returncode}\n{output}"
    except Exception as e:
        return f"[error] {e}"


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
)
async def background_process(
    command: str,
    workdir: str | None = None,
    timeout: float = _DEFAULT_BACKGROUND_TIMEOUT,
    approval_id: str | None = None,
) -> str:
    result = check_safe_bin(command)
    cwd = _effective_workdir(workdir)
    if not result.allowed:
        raise ToolError(result.reason)
    sensitive_block = _sensitive_shell_block("background_process", command, workdir=cwd)
    if sensitive_block is not None:
        return sensitive_block
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

    elevated_bypass = _elevated_mode() in ("on", "bypass", "full")

    runtime = get_runtime()
    if runtime is not None and runtime.effective.sandbox_enabled and not elevated_bypass:
        decision, policy, request = await gate_action(
            action_kind="shell.background",
            argv=("background_process", command),
            cwd=Path(workdir) if workdir else None,
            env=dict(os.environ),
        )
        if isinstance(decision, DenialResult):
            return json.dumps(decision.to_dict())
        spawned = await _spawn_sandboxed_background_process(
            runtime=runtime,
            request=SandboxRequest(
                argv=("sh", "-lc", command),
                cwd=request.cwd,
                action_kind=request.action_kind,
                policy=policy,
                env=dict(os.environ),
            ),
        )
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
        )
        _bg_sessions[session_id] = session
        effective_timeout = _resolve_background_timeout(timeout)

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
                _finalize_bg_session(session)

        session.collector_task = asyncio.create_task(_collect_restricted())
        return _background_process_result(session)

    if elevated_bypass:
        log.info("background_process_elevated_host", command=_audit_command(command))

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
    effective_timeout = _resolve_background_timeout(timeout)

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
            _finalize_bg_session(session)

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
                _finalize_bg_session(session)
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
            _finalize_bg_session(session)
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


def _apply_approval_elevated_mode(entry: object) -> None:
    params = getattr(entry, "params", None)
    if not isinstance(params, dict):
        return
    mode = params.get("elevatedMode")
    if mode not in ("on", "bypass", "full"):
        return
    ctx = current_tool_context.get()
    if ctx is not None and ctx.is_owner:
        ctx.elevated = mode


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

    elevated_mode = _context_elevated_mode()
    elevated_full = elevated_mode == "full"
    elevated_bypass = elevated_mode == "bypass"
    sandbox_off_requires_approval = (
        _sandbox_effectively_off() and not elevated_full and not elevated_bypass
    )

    # Sensitive-path hard block. Only /elevated full bypasses; ordinary
    # approval cannot override.
    if not elevated_full:
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

    # /elevated full — trusted operator has taken explicit responsibility.
    # Approvals are skipped entirely.
    if elevated_full:
        log.info(
            "shell_approval_skipped_elevated_full",
            command=_audit_command(command),
            tool=tool_name,
        )
        _elevate_current_call.set(True)
        return None

    # /elevated bypass — auto-approve all warned commands, but the sensitive
    # path block above still applies (so SSH keys, /etc, etc. remain
    # protected). This is the user-friendly "trust me for normal stuff" mode.
    if elevated_bypass:
        log.info(
            "shell_approval_skipped_elevated_bypass",
            command=_audit_command(command),
            tool=tool_name,
        )
        _elevate_current_call.set(True)
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
            elevated_mode=elevated_mode,
        )

    if settings.mode == "auto-approve" and not sandbox_off_requires_approval:
        _elevate_current_call.set(True)
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
            _elevate_current_call.set(True)
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
                _apply_approval_elevated_mode(entry)
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
                _elevate_current_call.set(True)
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
        _apply_approval_elevated_mode(entry)
        queue.consume(approval_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    log.info("shell_approval_granted", approval_id=approval_id, command=_audit_command(command))
    # User explicitly approved this call — grant per-call host execution so
    # the approved rm/destructive op can actually reach the host target.
    _elevate_current_call.set(True)
    return None
