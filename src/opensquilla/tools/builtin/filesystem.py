# Filesystem built-in tools: read_file, write_file, edit_file, list_dir, glob_search, grep_search.

from __future__ import annotations

import asyncio
import csv
import fnmatch
import json
import os
import posixpath
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from opensquilla.identity.workspace import BOOTSTRAP_FILENAMES
from opensquilla.sandbox.escalation import (
    build_path_approval_params,
    current_tool_mounts,
    current_tool_run_context,
    grant_temporary_mount_for_current_tool,
    request_sandbox_approval,
)
from opensquilla.sandbox.integration import get_runtime
from opensquilla.sandbox.operation_runtime import (
    FilesystemOperationRequest,
    SandboxOperation,
    SandboxOperationRuntime,
    SandboxToolDescriptor,
)
from opensquilla.sandbox.path_validation import MountDecision, decide_path_access
from opensquilla.tools.path_policy import reject_foreign_host_path
from opensquilla.tools.registry import tool
from opensquilla.tools.run_mode import (
    current_run_mode,
    full_host_access_active,
    trusted_sandbox_active,
)
from opensquilla.tools.types import ToolError, WorkspaceAccessError, current_tool_context
from opensquilla.tools.write_tracking import record_workspace_file_write

_SPREADSHEET_EXTENSIONS = {".csv", ".tsv", ".xlsx"}
_OFFICE_BINARY_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
_BINARY_EXTENSIONS = {
    ".7z",
    ".bin",
    ".bz2",
    ".dmg",
    ".exe",
    ".gz",
    ".rar",
    ".tar",
    ".zip",
    *_OFFICE_BINARY_EXTENSIONS,
}
_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_XLSX_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_BOOTSTRAP_SOURCE_FILENAMES = frozenset(BOOTSTRAP_FILENAMES)


def _tool_path_request(args: Mapping[str, Any]) -> FilesystemOperationRequest:
    raw_path = args.get("path")
    path = Path(str(raw_path)) if raw_path else None
    return FilesystemOperationRequest(
        path=path,
        paths=(path,) if path is not None else (),
    )


def _tool_search_request(args: Mapping[str, Any]) -> FilesystemOperationRequest:
    raw_path = args.get("path")
    path = Path(str(raw_path)) if raw_path else None
    return FilesystemOperationRequest(
        path=path,
        paths=(path,) if path is not None else (),
        pattern=str(args.get("pattern", "") or ""),
        include=str(args["include"]) if args.get("include") is not None else None,
        max_results=int(args["max_results"]) if args.get("max_results") is not None else None,
    )


def _workspace_root() -> Path | None:
    ctx = current_tool_context.get()
    if ctx is not None and ctx.workspace_dir:
        return Path(ctx.workspace_dir).expanduser().resolve()
    runtime = get_runtime()
    if runtime is not None and runtime.effective.sandbox_enabled:
        return runtime.workspace.expanduser().resolve()
    return None


def _memory_source_root() -> Path | None:
    ctx = current_tool_context.get()
    if ctx is None or not ctx.memory_source_dir:
        return None
    return Path(ctx.memory_source_dir).expanduser().resolve()


def _memory_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for root in (_workspace_root(), _memory_source_root()):
        if root is None or root in roots:
            continue
        roots.append(root)
    return tuple(roots)


def _resolve_path(path: str) -> Path:
    """Resolve *path* against the active workspace when relative.

    Reads are always allowed; any workspace enforcement for writes happens in
    :func:`_gate_out_of_workspace_write` via the approval queue, not here.

    Sandbox-visible alias paths (``/workspace/...`` from ``execute_code``
    stdout, ``default_workspace_dir()/...`` from LLM training priors)
    are translated back to the active host workspace before any
    sensitive-path / workspace-strict enforcement runs. Without this,
    model-guessed default-workspace paths are hard-blocked by the
    sensitive_path check even though the same file written under the
    gateway-configured workspace would be valid.
    """
    from opensquilla.tools.path_aliases import resolve_workspace_alias

    raw = Path(path).expanduser()
    root = _workspace_root()
    reject_foreign_host_path(str(path), platform=os.name, workspace=root)
    alias = resolve_workspace_alias(raw, root)
    if alias is not None:
        return alias
    if root is not None and not raw.is_absolute():
        return (root / raw).resolve(strict=False)
    return raw.resolve(strict=False) if raw.is_absolute() else raw


def _resolve_base(path: str | None) -> Path:
    if path:
        return _resolve_path(path)
    root = _workspace_root()
    return root if root is not None else Path.cwd()


def _memory_source_rel_path(path: Path) -> str | None:
    resolved = path.resolve(strict=False)
    for root in _memory_roots():
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            continue

        if rel.parts in {("MEMORY.md",), ("memory.md",)}:
            return rel.as_posix()
        if len(rel.parts) >= 2 and rel.parts[0] == "memory" and rel.suffix == ".md":
            return rel.as_posix()
    return None


def _bootstrap_source_rel_path(path: Path) -> str | None:
    root = _workspace_root()
    if root is None:
        return None
    resolved = path.resolve(strict=False)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    rel_path = rel.as_posix()
    if len(rel.parts) == 1 and rel_path in _BOOTSTRAP_SOURCE_FILENAMES:
        return rel_path
    return None


def _notify_memory_source_write(path: Path) -> None:
    ctx = current_tool_context.get()
    if ctx is None or ctx.on_memory_source_write is None:
        return
    rel = _memory_source_rel_path(path)
    if rel is None:
        return
    ctx.on_memory_source_write(ctx.agent_id or "main", rel)


def _notify_bootstrap_source_write(path: Path) -> None:
    ctx = current_tool_context.get()
    if ctx is None or ctx.on_bootstrap_source_write is None:
        return
    rel = _bootstrap_source_rel_path(path)
    if rel is None:
        return
    ctx.on_bootstrap_source_write(ctx.agent_id or "main", rel)


def _binary_file_error(path: str, p: Path, *, reason: str | None = None) -> ToolError:
    hint = ""
    if p.suffix.lower() in _SPREADSHEET_EXTENSIONS:
        hint = " Use read_spreadsheet(path=...) for CSV/TSV/Excel workbook data."
    detail = f" ({reason})" if reason else ""
    return ToolError(f"Cannot read binary file as text: {path}{detail}.{hint}")


def _looks_binary(raw: bytes, p: Path) -> str | None:
    ext = p.suffix.lower()
    if ext in _OFFICE_BINARY_EXTENSIONS:
        return f"{ext} Office document"
    if ext in _BINARY_EXTENSIONS:
        return f"{ext} binary/container file"
    sample = raw[:8192]
    if b"\x00" in sample:
        return "contains NUL bytes"
    return None


def _read_binary_sample(p: Path, size: int = 8192) -> bytes:
    with p.open("rb") as fh:
        return fh.read(size)


def _stream_numbered_lines_from_file(
    p: Path,
    original_path: str,
    *,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read a numbered UTF-8 line window without loading the whole file.

    Counting offsets still requires decoding prior lines; invalid UTF-8 before
    the selected window therefore raises the same text/binary error style.
    """

    start_line = offset if offset and offset > 0 else 1
    selected: list[str] = []
    emitted = 0
    try:
        with p.open("rb") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.decode("utf-8")
                if lineno < start_line:
                    continue
                if limit is not None and emitted >= limit:
                    break
                selected.append(f"{lineno}\t{line}")
                emitted += 1
    except UnicodeDecodeError as exc:
        raise _binary_file_error(original_path, p, reason="not valid UTF-8") from exc
    return "".join(selected)


def _is_outside_workspace(resolved: Path) -> bool:
    """True when *resolved* is not contained in the active workspace.

    No workspace configured → writes aren't gated at all (no root to compare).
    """
    root = _workspace_root()
    if root is None:
        return False
    try:
        resolved.relative_to(root)
        return False
    except ValueError:
        return True


def _sandbox_path_access_enabled() -> bool:
    runtime = get_runtime()
    if runtime is None or not runtime.effective.sandbox_enabled:
        return False
    if full_host_access_active():
        return False
    return True


def _active_sandbox_mounts() -> list[dict[str, object]]:
    return current_tool_mounts()


def _path_access_required_envelope(
    decision: MountDecision,
    *,
    approval_id: str | None = None,
) -> dict[str, object]:
    ctx = current_tool_context.get()
    workspace_root = _workspace_root()
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


def _sandbox_path_access_envelope(
    resolved: Path,
    *,
    write: bool,
    approval_id: str | None = None,
) -> dict[str, object] | None:
    if not _sandbox_path_access_enabled():
        return None
    if _memory_source_rel_path(resolved) is not None:
        return None
    decision = decide_path_access(
        resolved,
        workspace=_workspace_root(),
        mounts=_active_sandbox_mounts(),
        write=write,
    )
    if decision.status == "allowed":
        return None
    if decision.status == "blocked":
        return _path_access_blocked_envelope(decision)
    if trusted_sandbox_active():
        if grant_temporary_mount_for_current_tool(decision):
            return None
    return _path_access_required_envelope(decision, approval_id=approval_id)


def _sandbox_path_access_marker(candidate: Path, *, write: bool) -> str | None:
    envelope = _sandbox_path_access_envelope(
        candidate.resolve(strict=False),
        write=write,
    )
    if envelope is None:
        return None
    if envelope.get("status") == "blocked":
        return f"[blocked] {candidate}: {envelope.get('message') or 'sensitive path'}"
    return f"[blocked] {candidate}: outside current sandbox view"


def _active_sandbox_mount_allows(resolved: Path, *, write: bool) -> bool:
    if not _sandbox_path_access_enabled():
        return False
    decision = decide_path_access(
        resolved,
        workspace=_workspace_root(),
        mounts=_active_sandbox_mounts(),
        write=write,
    )
    return decision.status == "allowed"


def _active_filesystem_run_mode() -> str:
    context = current_tool_run_context()
    if context is not None:
        return context.run_mode.value
    return current_run_mode() or "standard"


async def _run_sandbox_operation_if_required(
    operation: SandboxOperation,
) -> object | None:
    return await SandboxOperationRuntime(
        get_runtime(),
        host_execution_active=full_host_access_active(),
    ).run(operation)


def _filesystem_operation_workspace() -> Path | None:
    root = _workspace_root()
    if root is not None:
        return root
    runtime = get_runtime()
    if runtime is not None and runtime.effective.sandbox_enabled:
        return runtime.workspace.expanduser().resolve(strict=False)
    return None


def _strict_read_workspace_root() -> Path | None:
    """Return the read-containment root when workspace-strict mode is active.

    Unlike :func:`_workspace_root`, strict read containment is intentionally
    opt-in through the entry-point ``ToolContext``. Runtime sandbox workspaces
    still provide relative-path resolution, but they do not by themselves turn
    every read into a strict containment check.
    """

    ctx = current_tool_context.get()
    if ctx is None or not ctx.workspace_strict or not ctx.workspace_dir:
        return None
    return Path(ctx.workspace_dir).expanduser().resolve(strict=False)


def _strict_read_material_root() -> Path | None:
    ctx = current_tool_context.get()
    if (
        ctx is None
        or not ctx.workspace_strict
        or not ctx.artifact_media_root
        or not ctx.artifact_session_id
    ):
        return None

    from opensquilla.attachment_refs import transcript_material_dir

    return transcript_material_dir(
        Path(ctx.artifact_media_root).expanduser(),
        ctx.artifact_session_id,
    ).resolve(strict=False)


def _strict_read_mount_roots() -> tuple[Path, ...]:
    ctx = current_tool_context.get()
    if ctx is None or not ctx.workspace_strict:
        return tuple()
    roots: list[Path] = []
    for mount in _active_sandbox_mounts():
        if not isinstance(mount, dict):
            continue
        raw_path = mount.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        try:
            root = Path(raw_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _strict_read_roots() -> tuple[Path, ...]:
    if full_host_access_active():
        return tuple()
    roots: list[Path] = []
    workspace_root = _strict_read_workspace_root()
    if workspace_root is not None:
        roots.append(workspace_root)
    material_root = _strict_read_material_root()
    if material_root is not None:
        roots.append(material_root)
    for mount_root in _strict_read_mount_roots():
        if mount_root not in roots:
            roots.append(mount_root)
    return tuple(roots)


def _is_within_any_root(candidate: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _workspace_strict_read_block(
    tool_name: str,
    resolved: Path,
    original_path: str,
) -> dict[str, object] | None:
    """Return a block envelope when *resolved* escapes the strict workspace."""

    roots = _strict_read_roots()
    if not roots:
        return None
    candidate = resolved.expanduser().resolve(strict=False)
    if not _is_within_any_root(candidate, roots):
        root_labels = ", ".join(str(root) for root in roots)
        return {
            "status": "blocked",
            "reason": "workspace_strict",
            "tool": tool_name,
            "path": original_path,
            "resolved_path": str(candidate),
            "workspace": str(roots[0]),
            "allowed_roots": [str(root) for root in roots],
            "message": (
                f"{tool_name} blocked: {candidate} is outside active read roots "
                f"({root_labels})."
            ),
            "retryable": False,
        }
    return None


def _gate_workspace_strict_read(tool_name: str, resolved: Path, original_path: str) -> None:
    """Raise when a read target/base escapes the strict workspace.

    Call this after sensitive-path checks so sensitive hard-blocks keep higher
    priority, and before existence/metadata checks so strict mode does not
    become an existence oracle for outside paths.
    """

    blocked = _workspace_strict_read_block(tool_name, resolved, original_path)
    if blocked is not None:
        raise WorkspaceAccessError(str(blocked["message"]))


def _workspace_strict_candidate_marker(
    tool_name: str,
    candidate: Path,
    original_path: str | None = None,
    strict_root: Path | None = None,
    strict_roots: tuple[Path, ...] | None = None,
) -> str | None:
    """Return a per-candidate blocked marker for directory/search tools."""

    roots = (strict_root,) if strict_root is not None else (strict_roots or _strict_read_roots())
    if not roots:
        return None
    resolved = candidate.expanduser().resolve(strict=False)
    if not _is_within_any_root(resolved, roots):
        root_labels = ", ".join(str(root) for root in roots)
        return f"[blocked] {candidate}: outside active read roots ({root_labels})"
    return None


def _sensitive_access_block(tool_name: str, resolved: Path, original_path: str) -> dict | None:
    """Return a hard-block envelope for sensitive host paths, unless fully elevated."""
    from opensquilla.sandbox.sensitive_paths import build_block_envelope, sensitive_path_marker

    if full_host_access_active():
        return None
    sensitive = sensitive_path_marker(str(resolved), workspace=_workspace_root())
    if sensitive is None:
        return None
    return build_block_envelope(f"{tool_name} {original_path}", sensitive, tool_name=tool_name)


def _is_sensitive_access_path(resolved: Path, workspace: Path | None = None) -> bool:
    from opensquilla.sandbox.sensitive_paths import sensitive_path_marker

    root = workspace if workspace is not None else _workspace_root()
    return (
        not full_host_access_active()
        and sensitive_path_marker(str(resolved), workspace=root) is not None
    )


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


def _inside_any_root(candidate: Path, roots: list[Path]) -> bool:
    resolved = candidate.expanduser().resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _gate_workspace_lockdown_write(tool_name: str, resolved: Path, original_path: str) -> None:
    roots = _workspace_lockdown_roots()
    if not roots or _inside_any_root(resolved, roots):
        return
    allowed = ", ".join(str(root) for root in roots)
    raise ToolError(
        f"{tool_name} blocked by workspace lockdown: {original_path} resolves to "
        f"{resolved}, outside allowed roots: {allowed}."
    )


async def _gate_out_of_workspace_write(
    tool_name: str,
    resolved: Path,
    original_path: str,
    approval_id: str | None,
) -> dict | None:
    """Return an approval-required/denied/blocked dict, or None to proceed.

    Writes that stay inside the workspace pass through immediately. Writes
    that target absolute paths outside the workspace get routed through the
    same approval queue that shell warnlist hits use. Writes targeting
    sensitive host paths (SSH keys, /etc, etc.) are hard-blocked regardless
    of approval.
    """
    # Sensitive-path hard block — takes precedence over approval flow.
    from opensquilla.sandbox.sensitive_paths import build_block_envelope, sensitive_path_marker

    elevated_full = full_host_access_active()
    if not elevated_full:
        sensitive = sensitive_path_marker(str(resolved), workspace=_workspace_root())
        if sensitive is not None:
            return build_block_envelope(
                f"{tool_name} {original_path}", sensitive, tool_name=tool_name
            )
    path_access = _sandbox_path_access_envelope(
        resolved,
        write=True,
        approval_id=approval_id,
    )
    if path_access is not None:
        return path_access

    _gate_workspace_lockdown_write(tool_name, resolved, original_path)
    from opensquilla.tools.write_policy import gate_workspace_write_deny

    gate_workspace_write_deny(
        tool_name,
        resolved,
        original_path=original_path,
        workspace=_workspace_root(),
    )

    if not _is_outside_workspace(resolved):
        return None
    if _memory_source_rel_path(resolved) is not None:
        return None
    if _active_sandbox_mount_allows(resolved, write=True):
        return None
    from opensquilla.tools.builtin.shell import (
        _approval_elevation_state,
        _check_exec_approval,
        _restore_approval_elevation,
    )

    workspace = _workspace_root()
    warning = (
        f"writing outside active workspace ({workspace}): {resolved}"
        if workspace is not None
        else f"writing to absolute path: {resolved}"
    )
    prior_elevation = _approval_elevation_state()
    try:
        return await _check_exec_approval(
            tool_name=tool_name,
            command=f"{tool_name} {original_path}",
            workdir=None,
            warning=warning,
            approval_id=approval_id,
            background=False,
        )
    finally:
        _restore_approval_elevation(prior_elevation)


@tool(
    name="read_file",
    description=(
        "Read UTF-8 text file contents with line numbers. Supports offset and limit. "
        "For CSV/TSV/Excel workbook data, use read_spreadsheet."
    ),
    params={
        "path": {"type": "string", "description": "Absolute path to the file."},
        "offset": {
            "type": "integer",
            "description": "Line offset to start reading from (1-indexed).",
        },
        "limit": {"type": "integer", "description": "Maximum number of lines to read."},
    },
    required=["path"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="read_file",
        argv_factory=lambda a: ("read_file", str(a.get("path", ""))),
        request_factory=_tool_path_request,
        enforce=False,
        record_payload=False,
    ),
)
async def read_file(path: str, offset: int | None = None, limit: int | None = None) -> str:
    p = _resolve_path(path)
    blocked = _sensitive_access_block("read_file", p, path)
    if blocked is not None:
        return json.dumps(blocked)
    path_access = _sandbox_path_access_envelope(p, write=False)
    if path_access is not None:
        return json.dumps(path_access)
    _gate_workspace_strict_read("read_file", p, path)
    workspace = _filesystem_operation_workspace()
    if workspace is not None:
        sandbox_result = await _run_sandbox_operation_if_required(
            SandboxOperation.filesystem(
                kind="read_file",
                workspace=workspace,
                run_mode=_active_filesystem_run_mode(),
                path=p,
                paths=(p,),
                display_path=path,
                offset=offset,
                limit=limit,
            )
        )
        if sandbox_result is not None:
            return str(getattr(sandbox_result, "message"))
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not p.is_file():
        raise IsADirectoryError(f"Path is a directory: {path}")

    loop = asyncio.get_event_loop()
    sample: bytes = await loop.run_in_executor(None, _read_binary_sample, p)
    if not sample:
        return ""

    binary_reason = _looks_binary(sample, p)
    if binary_reason:
        raise _binary_file_error(path, p, reason=binary_reason)

    return await loop.run_in_executor(
        None,
        lambda: _stream_numbered_lines_from_file(p, path, offset=offset, limit=limit),
    )


@tool(
    name="read_spreadsheet",
    description=(
        "Read CSV, TSV, or Excel .xlsx files as structured text tables. "
        "When reading .xlsx, all sheets are returned by default; pass sheet as "
        "a sheet name or 1-based index to read one sheet."
    ),
    params={
        "path": {"type": "string", "description": "Path to a .csv, .tsv, or .xlsx file."},
        "sheet": {
            "type": "string",
            "description": "Optional sheet name or 1-based sheet index for .xlsx files.",
        },
        "offset": {
            "type": "integer",
            "description": "Row offset to start reading from (1-indexed, default 1).",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum rows per sheet to return (default 200).",
        },
    },
    required=["path"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="read_spreadsheet",
        argv_factory=lambda a: ("read_spreadsheet", str(a.get("path", ""))),
        request_factory=_tool_path_request,
        enforce=False,
        record_payload=False,
    ),
)
async def read_spreadsheet(
    path: str,
    sheet: str | int | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    p = _resolve_path(path)
    blocked = _sensitive_access_block("read_spreadsheet", p, path)
    if blocked is not None:
        return json.dumps(blocked)
    path_access = _sandbox_path_access_envelope(p, write=False)
    if path_access is not None:
        return json.dumps(path_access)
    _gate_workspace_strict_read("read_spreadsheet", p, path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not p.is_file():
        raise IsADirectoryError(f"Path is a directory: {path}")

    ext = p.suffix.lower()
    row_offset = offset if offset and offset > 0 else 1
    row_limit = limit if limit and limit > 0 else 200
    loop = asyncio.get_event_loop()

    if ext in {".csv", ".tsv"}:
        delimiter = "\t" if ext == ".tsv" else ","
        sheets = await loop.run_in_executor(None, _read_delimited_rows, p, delimiter)
    elif ext == ".xlsx":
        sheets = await loop.run_in_executor(None, _read_xlsx_sheets, p)
    else:
        raise ToolError(
            f"Unsupported spreadsheet format: {ext or '(none)'}. Use .csv, .tsv, or .xlsx."
        )

    selected = _select_spreadsheet_sheets(sheets, sheet)
    return _format_spreadsheet(path=p, sheets=selected, offset=row_offset, limit=row_limit)


def _read_delimited_rows(path: Path, delimiter: str) -> list[tuple[str, list[list[str]]]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ToolError(f"Cannot read spreadsheet as UTF-8 text: {path}") from exc
    rows = [[cell for cell in row] for row in csv.reader(text.splitlines(), delimiter=delimiter)]
    return [(path.name, rows)]


def _read_xlsx_sheets(path: Path) -> list[tuple[str, list[list[str]]]]:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "xl/workbook.xml" not in names:
                raise ToolError(f"Invalid .xlsx workbook: missing xl/workbook.xml in {path}")
            shared_strings = _read_xlsx_shared_strings(zf, names)
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = _read_xlsx_workbook_relationships(zf, names)
            sheets: list[tuple[str, list[list[str]]]] = []
            for sheet_el in workbook.findall(f".//{{{_XLSX_MAIN_NS}}}sheet"):
                sheet_name = sheet_el.attrib.get("name") or f"Sheet{len(sheets) + 1}"
                rel_id = sheet_el.attrib.get(f"{{{_XLSX_OFFICE_REL_NS}}}id")
                target = rels.get(rel_id or "")
                if not target:
                    continue
                worksheet_path = _normalize_xlsx_target(target)
                if worksheet_path not in names:
                    continue
                rows = _read_xlsx_worksheet(zf.read(worksheet_path), shared_strings)
                sheets.append((sheet_name, rows))
            if not sheets:
                raise ToolError(f"No readable worksheets found in {path}")
            return sheets
    except zipfile.BadZipFile as exc:
        raise ToolError(f"Invalid .xlsx workbook: {path}") from exc
    except ET.ParseError as exc:
        raise ToolError(f"Invalid .xlsx XML content in {path}: {exc}") from exc


def _read_xlsx_shared_strings(zf: zipfile.ZipFile, names: set[str]) -> list[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    shared: list[str] = []
    for si in root.findall(f".//{{{_XLSX_MAIN_NS}}}si"):
        texts = [node.text or "" for node in si.findall(f".//{{{_XLSX_MAIN_NS}}}t")]
        shared.append("".join(texts))
    return shared


def _read_xlsx_workbook_relationships(
    zf: zipfile.ZipFile,
    names: set[str],
) -> dict[str, str]:
    rels_path = "xl/_rels/workbook.xml.rels"
    if rels_path not in names:
        return {}
    root = ET.fromstring(zf.read(rels_path))
    rels: dict[str, str] = {}
    for rel in root.findall(f".//{{{_XLSX_PACKAGE_REL_NS}}}Relationship"):
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            rels[rel_id] = target
    return rels


def _normalize_xlsx_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def _read_xlsx_worksheet(raw_xml: bytes, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(raw_xml)
    rows: list[list[str]] = []
    for row_el in root.findall(f".//{{{_XLSX_MAIN_NS}}}row"):
        row: list[str] = []
        for cell_el in row_el.findall(f"{{{_XLSX_MAIN_NS}}}c"):
            column_index = _xlsx_column_index(cell_el.attrib.get("r", ""))
            while len(row) < column_index:
                row.append("")
            row.append(_xlsx_cell_value(cell_el, shared_strings))
        while row and row[-1] == "":
            row.pop()
        rows.append(row)
    return rows


def _xlsx_column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Za-z]+)", cell_ref)
    if not match:
        return 0
    index = 0
    for char in match.group(1).upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return max(0, index - 1)


def _xlsx_cell_value(cell_el: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell_el.attrib.get("t")
    if cell_type == "inlineStr":
        texts = [node.text or "" for node in cell_el.findall(f".//{{{_XLSX_MAIN_NS}}}t")]
        return "".join(texts)

    value_el = cell_el.find(f"{{{_XLSX_MAIN_NS}}}v")
    raw = value_el.text if value_el is not None else ""
    if cell_type == "s" and raw:
        try:
            return shared_strings[int(raw)]
        except (IndexError, ValueError):
            return ""
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw or ""


def _select_spreadsheet_sheets(
    sheets: list[tuple[str, list[list[str]]]],
    requested: str | int | None,
) -> list[tuple[str, list[list[str]]]]:
    if requested is None or requested == "":
        return sheets

    if isinstance(requested, int) or (isinstance(requested, str) and requested.isdigit()):
        index = int(requested) - 1
        if 0 <= index < len(sheets):
            return [sheets[index]]

    requested_name = str(requested)
    for name, rows in sheets:
        if name == requested_name:
            return [(name, rows)]
    for name, rows in sheets:
        if name.lower() == requested_name.lower():
            return [(name, rows)]

    available = ", ".join(name for name, _ in sheets)
    raise ToolError(f"Sheet not found: {requested_name}. Available sheets: {available}")


def _format_spreadsheet(
    *,
    path: Path,
    sheets: list[tuple[str, list[list[str]]]],
    offset: int,
    limit: int,
) -> str:
    parts = [f"Workbook: {path.name}"]
    start = max(0, offset - 1)
    for sheet_name, rows in sheets:
        width = max((len(row) for row in rows), default=0)
        parts.append("")
        parts.append(f"Sheet: {sheet_name} ({len(rows)} rows x {width} columns)")
        selected = rows[start : start + limit]
        for idx, row in enumerate(selected, start=start + 1):
            parts.append(f"{idx}\t" + "\t".join(row))
        if start + limit < len(rows):
            end = start + len(selected)
            parts.append(
                f"(Showing rows {offset}-{end} of {len(rows)}. "
                f"Use offset={end + 1} to continue.)"
            )
    return "\n".join(parts)


@tool(
    name="write_file",
    description="Write content to a file, creating directories as needed.",
    params={
        "path": {"type": "string", "description": "Absolute path to write to."},
        "content": {"type": "string", "description": "File content to write."},
        "approval_id": {
            "type": "string",
            "description": "Approval record to consume for writes outside the workspace.",
        },
    },
    required=["path", "content"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="fs.write",
        argv_factory=lambda a: ("fs.write", str(a.get("path", ""))),
        request_factory=_tool_path_request,
        record_payload=False,
    ),
)
async def write_file(path: str, content: str, approval_id: str | None = None) -> str:
    p = _resolve_path(path)
    approval = await _gate_out_of_workspace_write("write_file", p, path, approval_id)
    if approval is not None:
        return json.dumps(approval)
    workspace = _filesystem_operation_workspace()
    if workspace is not None:
        sandbox_result = await _run_sandbox_operation_if_required(
            SandboxOperation.filesystem(
                kind="write_text",
                workspace=workspace,
                run_mode=_active_filesystem_run_mode(),
                path=p,
                paths=(p,),
                content=content,
            )
        )
        if sandbox_result is not None:
            if getattr(sandbox_result, "created", False):
                record_workspace_file_write(p)
            _notify_memory_source_write(p)
            _notify_bootstrap_source_write(p)
            return str(getattr(sandbox_result, "message"))

    loop = asyncio.get_event_loop()
    created = not p.exists()

    def _write() -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    await loop.run_in_executor(None, _write)
    if created:
        record_workspace_file_write(p)
    _notify_memory_source_write(p)
    _notify_bootstrap_source_write(p)
    return f"Written {len(content)} bytes to {p}"


@tool(
    name="edit_file",
    description="Edit a file by replacing old_text with new_text (exact string replacement).",
    params={
        "path": {"type": "string", "description": "Absolute path to the file to edit."},
        "old_text": {"type": "string", "description": "Text to find and replace."},
        "new_text": {"type": "string", "description": "Replacement text."},
        "approval_id": {
            "type": "string",
            "description": "Approval record to consume for edits outside the workspace.",
        },
    },
    required=["path", "old_text", "new_text"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="fs.edit",
        argv_factory=lambda a: ("fs.edit", str(a.get("path", ""))),
        request_factory=_tool_path_request,
        record_payload=False,
    ),
)
async def edit_file(
    path: str, old_text: str, new_text: str, approval_id: str | None = None
) -> str:
    p = _resolve_path(path)
    approval = await _gate_out_of_workspace_write("edit_file", p, path, approval_id)
    if approval is not None:
        return json.dumps(approval)
    workspace = _filesystem_operation_workspace()
    if workspace is not None:
        sandbox_result = await _run_sandbox_operation_if_required(
            SandboxOperation.filesystem(
                kind="edit_text",
                workspace=workspace,
                run_mode=_active_filesystem_run_mode(),
                path=p,
                paths=(p,),
                old_text=old_text,
                new_text=new_text,
            )
        )
        if sandbox_result is not None:
            _notify_memory_source_write(p)
            _notify_bootstrap_source_write(p)
            return str(getattr(sandbox_result, "message"))
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    loop = asyncio.get_event_loop()
    original = await loop.run_in_executor(None, p.read_text, "utf-8")

    if old_text not in original:
        raise ValueError(f"old_text not found in {path}")

    count = original.count(old_text)
    if count > 1:
        raise ValueError(f"old_text matches {count} locations in {path}; be more specific")

    updated = original.replace(old_text, new_text, 1)

    def _write() -> None:
        p.write_text(updated, encoding="utf-8")

    await loop.run_in_executor(None, _write)
    _notify_memory_source_write(p)
    _notify_bootstrap_source_write(p)
    return f"Edited {p}: replaced {len(old_text)} chars with {len(new_text)} chars"


@tool(
    name="list_dir",
    description="List directory contents with type and size.",
    params={
        "path": {"type": "string", "description": "Directory path to list."},
        "approval_id": {
            "type": "string",
            "description": "Approval record to consume after granting sandbox path access.",
        },
    },
    required=["path"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="list_dir",
        argv_factory=lambda a: ("list_dir", str(a.get("path", ""))),
        request_factory=_tool_path_request,
        enforce=False,
        record_payload=False,
    ),
)
async def list_dir(path: str, approval_id: str | None = None) -> str:
    p = _resolve_path(path)
    blocked = _sensitive_access_block("list_dir", p, path)
    if blocked is not None:
        return json.dumps(blocked)
    path_access = _sandbox_path_access_envelope(p, write=False, approval_id=approval_id)
    if path_access is not None:
        return json.dumps(path_access)
    _gate_workspace_strict_read("list_dir", p, path)
    workspace = _filesystem_operation_workspace()
    if workspace is not None:
        sandbox_result = await _run_sandbox_operation_if_required(
            SandboxOperation.filesystem(
                kind="list_dir",
                workspace=workspace,
                run_mode=_active_filesystem_run_mode(),
                path=p,
                paths=(p,),
                display_path=path,
            )
        )
        if sandbox_result is not None:
            return str(getattr(sandbox_result, "message"))
    if not p.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    loop = asyncio.get_event_loop()
    strict_roots = _strict_read_roots()
    workspace_root = _workspace_root()

    def _list() -> list[str]:
        dirs: list[str] = []
        files: list[str] = []
        blocked_entries: list[str] = []
        for entry in sorted(p.iterdir(), key=lambda e: e.name):
            marker = _workspace_strict_candidate_marker(
                "list_dir",
                entry,
                strict_roots=strict_roots,
            )
            if marker is not None:
                blocked_entries.append(marker)
                continue
            if _is_sensitive_access_path(entry.resolve(strict=False), workspace=workspace_root):
                continue
            if entry.is_dir():
                dirs.append(f"[dir]  {entry.name}/")
            else:
                size = entry.stat().st_size
                files.append(f"[file] {entry.name} ({size} bytes)")
        return dirs + files + blocked_entries

    entries = await loop.run_in_executor(None, _list)
    if not entries:
        return f"{path}: (empty directory)"
    return "\n".join(entries)


@tool(
    name="glob_search",
    description="Find files matching a glob pattern.",
    params={
        "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py')."},
        "path": {"type": "string", "description": "Base directory to search from (default: cwd)."},
    },
    required=["pattern"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="glob_search",
        argv_factory=lambda a: (
            "glob_search",
            str(a.get("pattern", "")),
            str(a.get("path", "")),
        ),
        request_factory=_tool_search_request,
        enforce=False,
        record_payload=False,
    ),
)
async def glob_search(pattern: str, path: str | None = None) -> str:
    base = _resolve_base(path)
    blocked = _sensitive_access_block("glob_search", base, path or str(base))
    if blocked is not None:
        return json.dumps(blocked)
    path_access = _sandbox_path_access_envelope(base, write=False)
    if path_access is not None:
        return json.dumps(path_access)
    _gate_workspace_strict_read("glob_search", base, path or str(base))
    workspace = _filesystem_operation_workspace()
    if workspace is not None:
        sandbox_result = await _run_sandbox_operation_if_required(
            SandboxOperation.filesystem(
                kind="glob_search",
                workspace=workspace,
                run_mode=_active_filesystem_run_mode(),
                path=base,
                paths=(base,),
                display_path=path or str(base),
                pattern=pattern,
            )
        )
        if sandbox_result is not None:
            return str(getattr(sandbox_result, "message"))

    loop = asyncio.get_event_loop()
    strict_roots = _strict_read_roots()
    workspace_root = _workspace_root()

    def _glob() -> list[str]:
        matches: list[str] = []
        for candidate in sorted(base.glob(pattern), key=lambda item: str(item)):
            marker = _workspace_strict_candidate_marker(
                "glob_search",
                candidate,
                strict_roots=strict_roots,
            )
            if marker is not None:
                matches.append(marker)
                continue
            if _is_sensitive_access_path(candidate.resolve(strict=False), workspace=workspace_root):
                continue
            matches.append(str(candidate))
        return matches

    matches = await loop.run_in_executor(None, _glob)
    if not matches:
        return f"No files matched pattern '{pattern}' in {base}"
    return "\n".join(matches)


@tool(
    name="grep_search",
    description="Search file contents for a regex pattern.",
    params={
        "pattern": {"type": "string", "description": "Regex pattern to search for."},
        "path": {"type": "string", "description": "File or directory to search (default: cwd)."},
        "include": {"type": "string", "description": "Glob pattern to filter files (e.g. '*.py')."},
        "max_results": {
            "type": "integer",
            "description": "Maximum number of matches to return (default 100).",
        },
    },
    required=["pattern"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="grep_search",
        argv_factory=lambda a: (
            "grep_search",
            str(a.get("pattern", "")),
            str(a.get("path", "")),
        ),
        request_factory=_tool_search_request,
        enforce=False,
        record_payload=False,
    ),
)
async def grep_search(
    pattern: str,
    path: str | None = None,
    include: str | None = None,
    max_results: int = 100,
) -> str:
    base = _resolve_base(path)
    blocked = _sensitive_access_block("grep_search", base, path or str(base))
    if blocked is not None:
        return json.dumps(blocked)
    path_access = _sandbox_path_access_envelope(base, write=False)
    if path_access is not None:
        return json.dumps(path_access)
    _gate_workspace_strict_read("grep_search", base, path or str(base))
    workspace = _filesystem_operation_workspace()
    if workspace is not None:
        sandbox_result = await _run_sandbox_operation_if_required(
            SandboxOperation.filesystem(
                kind="grep_search",
                workspace=workspace,
                run_mode=_active_filesystem_run_mode(),
                path=base,
                paths=(base,),
                display_path=path or str(base),
                pattern=pattern,
                include=include,
                max_results=max_results,
            )
        )
        if sandbox_result is not None:
            return str(getattr(sandbox_result, "message"))

    loop = asyncio.get_event_loop()
    strict_roots = _strict_read_roots()
    workspace_root = _workspace_root()

    def _search() -> list[str]:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e

        results: list[str] = []

        def search_file(fp: Path) -> None:
            marker = _sandbox_path_access_marker(fp, write=False)
            if marker is not None:
                results.append(marker)
                return
            if _is_sensitive_access_path(fp.resolve(strict=False), workspace=workspace_root):
                return
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{fp}:{lineno}: {line.rstrip()}")
                        if len(results) >= max_results:
                            return
            except (PermissionError, OSError):
                pass

        if base.is_file():
            search_file(base)
        else:
            for fp in base.rglob("*"):
                if len(results) >= max_results:
                    break
                marker = _workspace_strict_candidate_marker(
                    "grep_search",
                    fp,
                    strict_roots=strict_roots,
                )
                if marker is not None:
                    results.append(marker)
                    continue
                if not fp.is_file():
                    continue
                if include and not fnmatch.fnmatch(fp.name, include):
                    continue
                search_file(fp)

        return results

    matches = await loop.run_in_executor(None, _search)
    if not matches:
        return f"No matches for '{pattern}'"
    return "\n".join(matches)
