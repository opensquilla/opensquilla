"""Code execution tool — sandboxed Python execution via subprocess."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from opensquilla.sandbox.denial_attribution import is_likely_sandbox_denied
from opensquilla.sandbox.elevation import ElevationAction, gate_elevated_action
from opensquilla.sandbox.integration import (
    SandboxRuntime,
    consume_backend_denial_retry,
    escalate_backend_denial,
    escalate_unavailable_backend_in_managed_mode,
    gate_action,
    get_runtime,
    preflight_subprocess_managed_network,
    prepare_subprocess_managed_network_proxy,
    run_under_backend,
)
from opensquilla.sandbox.operation_runtime import SandboxToolDescriptor
from opensquilla.sandbox.policy import LevelHints
from opensquilla.sandbox.types import (
    DenialResult,
    NetworkMode,
    SandboxBackendError,
    SandboxRequest,
)
from opensquilla.subprocess_encoding import apply_utf8_child_env, decode_subprocess_output
from opensquilla.tools.registry import tool
from opensquilla.tools.run_mode import full_host_access_active, trusted_sandbox_active
from opensquilla.tools.types import ToolError, current_tool_context
from opensquilla.tools.write_tracking import (
    mutation_ledger_text_hash,
    record_observed_workspace_mutations,
    snapshot_current_workspace_mutations,
)

# Destructive Python patterns that must be surfaced to the unified sandbox gate.
# Matching is intentionally shallow (regex, not AST): the goal is to classify
# obvious high-impact intent, not to prove safety.
_DESTRUCTIVE_PY_PATTERNS: list[tuple[str, str]] = [
    (r"\bos\.remove\s*\(", "os.remove()"),
    (r"\bos\.unlink\s*\(", "os.unlink()"),
    (r"\bos\.rmdir\s*\(", "os.rmdir()"),
    (r"\bos\.removedirs\s*\(", "os.removedirs()"),
    (r"\bshutil\.rmtree\s*\(", "shutil.rmtree()"),
    (r"\.unlink\s*\(", "Path.unlink()"),
    (r"\.rmdir\s*\(", "Path.rmdir()"),
    (r"\bos\.system\s*\([^)]*\brm\b", "os.system with rm"),
    (
        r"\bsubprocess\.(run|call|Popen|check_output|check_call)[^\n;]{0,200}\brm\b",
        "subprocess invoking rm",
    ),
    (
        r"\bsubprocess\.(run|call|Popen|check_output|check_call)[^\n;]{0,200}\brmdir\b",
        "subprocess invoking rmdir",
    ),
]


def _check_code_destructive(code: str) -> str | None:
    """Return a human-readable warning if *code* triggers a destructive pattern, else None."""
    for pattern, label in _DESTRUCTIVE_PY_PATTERNS:
        if re.search(pattern, code):
            return f"destructive Python operation detected: {label}"
    return None


_CODE_SENSITIVE_READ_TOKENS = (
    "open(",
    ".open(",
    ".read_text(",
    ".read_bytes(",
    "listdir(",
    "scandir(",
    "walk(",
    ".glob(",
    ".rglob(",
    "copyfile(",
    "copy2(",
    "copy(",
    "subprocess.",
    "os.system(",
    "os.popen(",
)
_CODE_NETWORK_TOKENS = (
    "httpx.",
    "requests.",
    "urllib.request",
    "http.client",
    "socket.",
    ".post(",
    ".put(",
    ".patch(",
)
_CODE_OUTBOUND_TRANSFER_RE = re.compile(
    r"\b(?:requests|httpx|aiohttp)(?:\.[A-Za-z_][A-Za-z0-9_]*)?\."
    r"(?:post|put|patch)\s*\(|"
    r"\burllib\.request\.(?:urlopen|Request)\s*\([^\n]{0,500}\bdata\s*=|"
    r"\bhttp\.client\b[^\n]{0,500}\.request\s*\(\s*['\"](?:POST|PUT|PATCH)|"
    r"\b(?:socket|sock)\.(?:send|sendall|sendto)\s*\(|"
    r"\b(?:ftp|ftps)\.storbinary\s*\(",
    flags=re.IGNORECASE,
)
_CODE_SENSITIVE_REFERENCE_RE = re.compile(
    r"(?:^|[/\\'\"])(?:\.ssh|\.aws|\.gnupg|\.kube|\.azure)(?:[/\\'\"]|$)|"
    r"\b(?:id_rsa|id_ed25519|credentials|login data|cookies|web data)\b|"
    r"(?:^|[/\\'\"])\.env(?:[./\\'\"]|$)",
    flags=re.IGNORECASE | re.MULTILINE,
)


def _iter_code_string_literals(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return re.findall(r"""["']([^"']{1,500})["']""", code)

    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
            if parts:
                values.append("".join(parts))
    return values


def _check_code_sensitive_access(code: str) -> tuple[str, str] | None:
    """Return (reason, marker) if Python code is trying to touch sensitive data."""
    runtime = get_runtime()
    if runtime is not None and runtime.effective.sandbox_enabled:
        return None
    lowered = code.lower()
    has_read_or_shell = any(token in lowered for token in _CODE_SENSITIVE_READ_TOKENS)

    ctx = current_tool_context.get()
    workspace = ctx.workspace_dir if ctx is not None else None

    from opensquilla.sandbox.sensitive_paths import sensitive_path_in_text, sensitive_path_marker

    for literal in _iter_code_string_literals(code):
        marker = sensitive_path_marker(literal, workspace=workspace) or sensitive_path_in_text(
            literal,
            workspace=workspace,
        )
        stripped_literal = literal.strip()
        path_like_literal = stripped_literal.startswith(("/", "~", ".", "\\\\")) or bool(
            re.match(r"^[A-Za-z]:[\\/]", stripped_literal)
        )
        if marker is not None and (has_read_or_shell or path_like_literal):
            return "sensitive_path", marker

    from opensquilla.tools.builtin.web import _sensitive_body_marker, _sensitive_url_marker

    has_network = any(token in lowered for token in _CODE_NETWORK_TOKENS)
    if has_network:
        for literal in _iter_code_string_literals(code):
            marker = _sensitive_url_marker(literal)
            if marker is not None:
                return "sensitive_payload", marker
        marker = _sensitive_body_marker(code)
        if marker is not None:
            return "sensitive_payload", marker

    return None


def _check_code_sensitive_external_transfer(code: str) -> str | None:
    """Return a marker for high-confidence Python secret exfiltration."""

    if not _CODE_OUTBOUND_TRANSFER_RE.search(code):
        return None
    ctx = current_tool_context.get()
    workspace = ctx.workspace_dir if ctx is not None else None
    from opensquilla.sandbox.sensitive_paths import sensitive_path_in_text, sensitive_path_marker

    for literal in _iter_code_string_literals(code):
        marker = sensitive_path_marker(literal, workspace=workspace) or sensitive_path_in_text(
            literal,
            workspace=workspace,
        )
        if marker is not None:
            return marker
    match = _CODE_SENSITIVE_REFERENCE_RE.search(code)
    if match is not None:
        return match.group(0).strip("/\\'\"") or "sensitive_local_data"
    from opensquilla.tools.builtin.web import _sensitive_body_marker

    return _sensitive_body_marker(code)


def _code_needs_network(code: str) -> bool:
    lowered = code.lower()
    return any(token in lowered for token in _CODE_NETWORK_TOKENS)


def _code_elevation_effects(
    code: str,
    *,
    workdir: Path,
    destructive_warning: str | None,
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]]:
    """Return conservative static effects without persisting the code body."""

    network_targets: list[str] = []
    target_paths: list[tuple[str, str]] = []
    risk_markers = ["arbitrary_python_host_execution"]
    if destructive_warning is not None:
        risk_markers.append(destructive_warning)
    if _code_needs_network(code):
        risk_markers.append("network_capable_code")

    access = "delete" if destructive_warning is not None else "read"
    lowered = code.lower()
    if any(token in lowered for token in ("write_text(", "write_bytes(", ".write(")) or re.search(
        r"\bopen\s*\([^\n]{0,300},\s*['\"][wax+]",
        code,
        flags=re.IGNORECASE,
    ):
        access = "write"

    for literal in _iter_code_string_literals(code):
        parsed = urlparse(literal)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
            host = parsed.hostname.casefold()
            if host not in network_targets:
                network_targets.append(host)
            continue
        stripped = literal.strip()
        if not (
            stripped.startswith(("/", "~", ".", "\\\\"))
            or re.match(r"^[A-Za-z]:[\\/]", stripped)
        ):
            continue
        candidate = Path(stripped).expanduser()
        if not candidate.is_absolute():
            candidate = workdir / candidate
        resolved = str(candidate.resolve(strict=False))
        item = (resolved, access)
        if item not in target_paths:
            target_paths.append(item)

    return tuple(target_paths), tuple(network_targets), tuple(risk_markers)


def _code_elevation_action(
    code: str,
    *,
    workdir: Path,
    destructive_warning: str | None,
    justification: str,
    prefix_rule: list[str] | None = None,
) -> ElevationAction:
    target_paths, network_targets, risk_markers = _code_elevation_effects(
        code,
        workdir=workdir,
        destructive_warning=destructive_warning,
    )
    return ElevationAction(
        tool_name="execute_code",
        action_kind="code.exec",
        argv=("execute_code",),
        cwd=str(workdir),
        sandbox_permissions="require_escalated",
        justification=justification,
        target_paths=target_paths,
        network_targets=network_targets,
        content_digest=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        content_length=len(code),
        risk_markers=risk_markers,
        prefix_rule=tuple(prefix_rule) if prefix_rule is not None else None,
    )


def _windows_sandbox_backend_active(runtime: object | None) -> bool:
    backend = getattr(runtime, "backend", None) if runtime is not None else None
    backend_name = str(getattr(backend, "name", "") or "")
    return backend_name.startswith("windows_")


def _trusted_managed_network_policy(policy, runtime: object | None):
    if getattr(policy, "network", None) is NetworkMode.PROXY_ALLOWLIST:
        return policy
    settings = getattr(runtime, "settings", None) if runtime is not None else None
    if getattr(settings, "network_default", None) != "proxy_allowlist":
        return policy
    if not trusted_sandbox_active():
        return policy
    ctx = current_tool_context.get()
    if getattr(policy, "network", None) is NetworkMode.NONE and (
        ctx is None or getattr(ctx, "sandbox_run_context", None) is None
    ):
        return policy
    return dataclasses.replace(policy, network=NetworkMode.PROXY_ALLOWLIST, network_proxy=None)


_trusted_windows_managed_network_policy = _trusted_managed_network_policy


def _windows_environment_subprocess_misuse(code: str) -> str | None:
    lowered = code.lower()
    if "subprocess." not in lowered and "os.system" not in lowered and "os.popen" not in lowered:
        return None
    if re.search(r"\bpython(?:\d+(?:\.\d+)*)?\b[^\"'\n;]{0,120}-m[^\"'\n;]{0,40}venv", lowered):
        return "python -m venv"
    if re.search(r"\buv\b[^\"'\n;]{0,80}\bvenv\b", lowered):
        return "uv venv"
    if re.search(r"\b(?:pip|pip3)\b[^\"'\n;]{0,80}\binstall\b", lowered):
        return "pip install"
    if re.search(r"\buv\b[^\"'\n;]{0,80}\bpip\b[^\"'\n;]{0,80}\binstall\b", lowered):
        return "uv pip install"
    if re.search(r"\b(?:npm|pnpm|yarn)\b[^\"'\n;]{0,80}\b(?:add|ci|install)\b", lowered):
        return "node package install"
    if "venv" in lowered:
        return "venv"
    return None


def _unsupported_windows_environment_subprocess_payload(reason: str) -> str:
    return json.dumps(
        {
            "status": "unsupported_tool_use",
            "tool": "execute_code",
            "recommended_tool": "exec_command",
            "reason": "windows_sandbox_environment_subprocess",
            "message": (
                "execute_code is for short Python calculations and import checks. "
                f"Windows sandbox detected {reason} through a Python subprocess; "
                "use exec_command so the Windows shell path translation, sandbox filesystem "
                "grants, and managed network approvals run before the process starts."
            ),
        },
        ensure_ascii=False,
    )


_MAX_TIMEOUT = 120
_DEFAULT_TIMEOUT = 30
_MAX_OUTPUT_CHARS = 50_000
_SANDBOX_PYTHON_CANDIDATES: tuple[Path, ...] = (
    Path("/usr/bin/python3"),
    Path("/bin/python3"),
    Path("/usr/bin/python"),
    Path("/bin/python"),
)

# Only these env vars are forwarded to the sandbox subprocess.
# Secrets (API keys, tokens) are explicitly excluded.
_SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "USER",
        "SHELL",
        "TERM",
        "PYTHONPATH",
    }
)

async def _run_backend_with_managed_network_if_needed(
    request: SandboxRequest,
    *,
    runtime: SandboxRuntime | None,
):
    if (
        runtime is None
        or getattr(request.policy, "network", None) is not NetworkMode.PROXY_ALLOWLIST
    ):
        return await run_under_backend(request, runtime=runtime)
    managed_network = await prepare_subprocess_managed_network_proxy(
        request,
        runtime=runtime,
    )
    try:
        return await run_under_backend(managed_network.request, runtime=runtime)
    finally:
        await managed_network.cleanup()


def _execution_result_json(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    timed_out: bool,
    elapsed_ms: int,
) -> str:
    return json.dumps(
        {
            "exit_code": returncode,
            "stdout": stdout[:_MAX_OUTPUT_CHARS],
            "stderr": stderr[:_MAX_OUTPUT_CHARS],
            "timed_out": timed_out,
            "elapsed_ms": elapsed_ms,
        },
        ensure_ascii=False,
    )


def _append_code_exec_sandbox_network_hint(*, stdout: str, stderr: str) -> str:
    from opensquilla.tools.builtin.shell import (
        _append_sandbox_network_hint,
        _looks_like_sandbox_network_failure,
        _sandbox_network_hint,
    )

    if not _looks_like_sandbox_network_failure(stdout + "\n" + stderr):
        return stderr
    if stderr:
        return _append_sandbox_network_hint(stderr, force=True)
    return _sandbox_network_hint()


def _resolve_python_bin(*, sandbox_enabled: bool) -> str:
    """Resolve a Python executable that is visible from the execution mode."""
    backend_name = ""
    if sandbox_enabled:
        runtime = get_runtime()
        backend = getattr(runtime, "backend", None) if runtime is not None else None
        backend_name = str(getattr(backend, "name", "") or "")

    if sandbox_enabled and backend_name == "bubblewrap":
        # The bubblewrap backend exposes host /usr and /bin inside the sandbox,
        # but not the caller's project venv. `uv run` commonly puts
        # .venv/bin/python3 first on PATH, which is invisible after isolation.
        for candidate in _SANDBOX_PYTHON_CANDIDATES:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

    if not sandbox_enabled or backend_name != "bubblewrap":
        current_python = Path(sys.executable)
        if current_python.is_file():
            return str(current_python)

    python_bin = shutil.which("python3") or shutil.which("python")
    if python_bin is None:
        raise ToolError("Python interpreter not found on PATH")
    return python_bin


@tool(
    name="execute_code",
    description=(
        "Execute Python code in an isolated subprocess and return stdout/stderr. "
        "When an active workspace is configured, code runs with that workspace "
        "as cwd; otherwise each invocation runs in a fresh temporary directory. "
        "Use for calculations, data processing, and validation. Prefer the file "
        "editing tools for project file changes."
    ),
    params={
        "code": {
            "type": "string",
            "description": "Python code to execute.",
        },
        "timeout": {
            "type": "number",
            "description": (
                f"Execution timeout in seconds (1-{_MAX_TIMEOUT}, default {_DEFAULT_TIMEOUT})."
            ),
        },
        "sandbox_permissions": {
            "type": "string",
            "enum": ["use_default", "require_escalated"],
            "description": "Use require_escalated only for one exact host Python run.",
        },
        "justification": {
            "type": "string",
            "description": "Short user-facing reason for the exact elevated code run.",
        },
        "prefix_rule": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional narrow prefix suggestion; never persisted by auto review.",
        },
        "approval_id": {
            "type": "string",
            "description": "Deprecated; sandbox approvals are handled by the runtime.",
        },
    },
    required=["code"],
    runtime_only_arguments=("approval_id",),
    sandbox=SandboxToolDescriptor.process(
        kind="code.exec",
        argv_factory=lambda a: ("execute_code", str(a.get("code", ""))),
        enforce=False,
        record_payload=False,
    ),
)
async def execute_code(
    code: str,
    timeout: float = _DEFAULT_TIMEOUT,
    approval_id: str | None = None,
    sandbox_permissions: str = "use_default",
    justification: str = "",
    prefix_rule: list[str] | None = None,
) -> str:
    if not code.strip():
        raise ToolError("Code must not be empty")

    full_host = full_host_access_active()
    external_transfer = None if full_host else _check_code_sensitive_external_transfer(code)
    if external_transfer is not None:
        return json.dumps(
            {
                "status": "blocked",
                "reason": "sensitive_external_transfer",
                "tool": "execute_code",
                "sensitive_reference": external_transfer,
            },
            ensure_ascii=False,
        )
    sensitive_access = None if full_host else _check_code_sensitive_access(code)
    if sensitive_access is not None:
        reason, marker = sensitive_access
        if reason == "sensitive_payload":
            from opensquilla.tools.builtin.web import _sensitive_body_block

            return _sensitive_body_block("execute_code", marker)

        from opensquilla.sandbox.sensitive_paths import build_block_envelope

        return json.dumps(
            build_block_envelope(
                "execute_code <python>",
                marker,
                tool_name="execute_code",
            ),
            ensure_ascii=False,
        )

    destructive_warning = None if full_host else _check_code_destructive(code)

    timeout = max(1.0, min(float(timeout), _MAX_TIMEOUT))

    ctx = current_tool_context.get()
    runtime = get_runtime()
    from opensquilla.tools.builtin.shell import (
        _apply_windows_session_tmp_env,
        _host_execution_allowed,
    )

    host_execution = _host_execution_allowed()
    sandbox_enabled = bool(
        runtime is not None and runtime.effective.sandbox_enabled and not host_execution
    )
    workspace = (
        Path(ctx.workspace_dir).expanduser().resolve() if ctx and ctx.workspace_dir else None
    )
    cleanup_dir: str | None = None
    if workspace is not None:
        workspace.mkdir(parents=True, exist_ok=True)
        workdir_path = workspace
    elif runtime is not None and runtime.effective.sandbox_enabled:
        workdir_path = runtime.workspace.expanduser().resolve()
        workdir_path.mkdir(parents=True, exist_ok=True)
    else:
        workdir = tempfile.mkdtemp(prefix="opensquilla_exec_")
        workdir_path = Path(workdir)
        cleanup_dir = workdir

    elevated_code_execution = False
    if sandbox_enabled and sandbox_permissions not in {"use_default", "require_escalated"}:
        return json.dumps(
            {"status": "invalid_request", "reason": "invalid_sandbox_permissions"}
        )
    if sandbox_enabled and sandbox_permissions == "require_escalated":
        if not justification.strip():
            return json.dumps(
                {
                    "status": "elevation_required",
                    "reason": "justification_required",
                    "message": "A precise justification is required for elevated execution.",
                }
            )
        action = _code_elevation_action(
            code,
            workdir=workdir_path,
            destructive_warning=destructive_warning,
            justification=justification,
            prefix_rule=prefix_rule,
        )
        gate = gate_elevated_action(
            action,
            approval_id=approval_id,
            session_key=ctx.session_key if ctx is not None else None,
        )
        if not gate.allowed:
            return json.dumps(gate.to_envelope(), ensure_ascii=False)
        host_execution = True
        sandbox_enabled = False
        elevated_code_execution = True

    if sandbox_enabled and _windows_sandbox_backend_active(runtime):
        misuse = _windows_environment_subprocess_misuse(code)
        if misuse is not None:
            return _unsupported_windows_environment_subprocess_payload(misuse)
    python_bin = _resolve_python_bin(sandbox_enabled=sandbox_enabled)
    start_ns = time.monotonic_ns()

    safe_env = (
        os.environ.copy()
        if host_execution and not elevated_code_execution
        else {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    )
    apply_utf8_child_env(safe_env)
    if sandbox_enabled and _windows_sandbox_backend_active(runtime):
        _apply_windows_session_tmp_env(safe_env)
    hints = (
        LevelHints()
        if full_host
        else LevelHints(
            needs_network=_code_needs_network(code),
            high_impact=destructive_warning is not None,
        )
    )
    mutation_before = {} if full_host else snapshot_current_workspace_mutations()

    def finish(output: str) -> str:
        if full_host:
            return output
        record_observed_workspace_mutations(
            tool_name="execute_code",
            before=mutation_before,
            metadata={"code_hash": mutation_ledger_text_hash(code)},
        )
        return output

    if not full_host and (
        runtime is None or (runtime.effective.sandbox_enabled and not host_execution)
    ):
        decision, _policy, request = await gate_action(
            action_kind="code.exec",
            argv=(python_bin, "-c", code),
            cwd=workdir_path,
            env=safe_env,
            hints=hints,
        )
        if isinstance(decision, DenialResult):
            return finish(json.dumps(decision.to_dict()))
        retry_gate = consume_backend_denial_retry(
            approval_id,
            request,
            _policy,
            runtime=runtime,
        )
        if retry_gate is not None:
            if not retry_gate.allowed:
                return finish(json.dumps(retry_gate.to_envelope(), ensure_ascii=False))
            host_execution = True
            sandbox_enabled = False
            elevated_code_execution = True
        else:
            backend_request = SandboxRequest(
                argv=(python_bin, "-c", code),
                cwd=request.cwd,
                action_kind=request.action_kind,
                policy=_trusted_managed_network_policy(request.policy, runtime),
                env=safe_env,
                reason=getattr(request, "reason", ""),
                session_id=getattr(request, "session_id", ""),
                run_mode=getattr(request, "run_mode", ""),
            )
            if runtime is not None:
                preflight = await preflight_subprocess_managed_network(backend_request, runtime)
                if isinstance(preflight, DenialResult):
                    return finish(json.dumps(preflight.to_dict()))
                if isinstance(preflight, dict):
                    return finish(json.dumps(preflight))
            try:
                sandbox_result = await _run_backend_with_managed_network_if_needed(
                    backend_request,
                    runtime=runtime,
                )
            except SandboxBackendError as exc:
                review_action = _code_elevation_action(
                    code,
                    workdir=workdir_path,
                    destructive_warning=destructive_warning,
                    justification="Sandbox backend unavailable; retry this exact code on host.",
                    prefix_rule=prefix_rule,
                )
                escalation = await escalate_unavailable_backend_in_managed_mode(
                    exc,
                    request,
                    _policy,
                    runtime=runtime,
                    review_action=review_action,
                )
                if escalation is not None:
                    if isinstance(escalation, DenialResult):
                        return finish(json.dumps(escalation.to_dict(), ensure_ascii=False))
                    return finish(json.dumps(escalation.to_envelope(), ensure_ascii=False))
                return finish(
                    _execution_result_json(
                        returncode=-1,
                        stdout="",
                        stderr=f"Execution error: {exc}",
                        timed_out=False,
                        elapsed_ms=0,
                    )
                )
            except Exception as exc:
                return finish(
                    _execution_result_json(
                        returncode=-1,
                        stdout="",
                        stderr=f"Execution error: {exc}",
                        timed_out=False,
                        elapsed_ms=0,
                    )
                )
            if is_likely_sandbox_denied(sandbox_result):
                review_action = _code_elevation_action(
                    code,
                    workdir=workdir_path,
                    destructive_warning=destructive_warning,
                    justification="Sandbox denied this exact code; retry it on host.",
                    prefix_rule=prefix_rule,
                )
                escalation = await escalate_backend_denial(
                    sandbox_result,
                    request,
                    _policy,
                    runtime=runtime,
                    review_action=review_action,
                )
                if isinstance(escalation, DenialResult):
                    return finish(json.dumps(escalation.to_dict()))
                return finish(json.dumps(escalation.to_envelope(), ensure_ascii=False))
            elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            stdout = sandbox_result.stdout
            stderr = sandbox_result.stderr
            stderr = _append_code_exec_sandbox_network_hint(stdout=stdout, stderr=stderr)
            return finish(
                _execution_result_json(
                    returncode=sandbox_result.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    timed_out=sandbox_result.timed_out,
                    elapsed_ms=elapsed_ms,
                )
            )

    try:
        proc = await asyncio.create_subprocess_exec(
            python_bin,
            "-c",
            code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir_path),
            env=safe_env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            return finish(
                _execution_result_json(
                    returncode=-1,
                    stdout="",
                    stderr=f"Execution timed out after {timeout}s",
                    timed_out=True,
                    elapsed_ms=elapsed_ms,
                )
            )

        elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        stdout = decode_subprocess_output(stdout_bytes)
        stderr = decode_subprocess_output(stderr_bytes)

        return finish(
            _execution_result_json(
                returncode=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
                elapsed_ms=elapsed_ms,
            )
        )
    except Exception as exc:
        return finish(
            _execution_result_json(
                returncode=-1,
                stdout="",
                stderr=f"Execution error: {exc}",
                timed_out=False,
                elapsed_ms=0,
            )
        )
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
