"""apply_patch built-in tool: applies structured patches to files."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opensquilla.identity.workspace import BOOTSTRAP_FILENAMES
from opensquilla.sandbox.operation_runtime import (
    FilesystemOperationRequest,
    SandboxOperation,
    SandboxToolDescriptor,
)
from opensquilla.tools.path_policy import reject_foreign_host_path
from opensquilla.tools.registry import tool
from opensquilla.tools.run_mode import full_host_access_active
from opensquilla.tools.types import ToolError, current_tool_context
from opensquilla.tools.write_tracking import record_workspace_file_write

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Hunk:
    old_start: int  # 1-indexed
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)  # each line keeps its +/-/space prefix


@dataclass
class AddFile:
    path: str
    content: str  # final content (+ prefixes already stripped)


@dataclass
class UpdateFile:
    path: str
    hunks: list[Hunk] = field(default_factory=list)


@dataclass
class DeleteFile:
    path: str


PatchOp = AddFile | UpdateFile | DeleteFile
_BOOTSTRAP_SOURCE_FILENAMES = frozenset(BOOTSTRAP_FILENAMES)
_APPLY_PATCH_APPROVAL_TOOL = "apply_patch"
_APPLY_PATCH_APPROVAL_NAMESPACE = "exec"


def _patch_request(args: Mapping[str, Any]) -> FilesystemOperationRequest:
    return FilesystemOperationRequest(patch=str(args.get("patch", "") or ""))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_patch(patch_text: str) -> list[PatchOp]:
    """Parse patch text into a list of PatchOp objects."""
    lines = patch_text.splitlines()

    # Validate markers
    if not any(line.strip() == "*** Begin Patch" for line in lines):
        raise ValueError("Missing '*** Begin Patch' marker")
    if not any(line.strip() == "*** End Patch" for line in lines):
        raise ValueError("Missing '*** End Patch' marker")

    # Trim to content between markers
    start_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "*** Begin Patch")
    end_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "*** End Patch")
    body = lines[start_idx + 1 : end_idx]

    ops: list[PatchOp] = []
    i = 0

    while i < len(body):
        line = body[i]

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: ") :].strip()
            i += 1
            content_lines: list[str] = []
            while i < len(body) and not body[i].startswith("*** "):
                raw = body[i]
                if raw.startswith("+"):
                    content_lines.append(raw[1:])
                i += 1
            ops.append(AddFile(path=path, content="\n".join(content_lines)))

        elif line.startswith("*** Update File: "):
            path = line[len("*** Update File: ") :].strip()
            i += 1
            hunks: list[Hunk] = []
            while i < len(body) and not body[i].startswith("*** "):
                hunk_line = body[i]
                if hunk_line.startswith("@@@ "):
                    hunk = _parse_hunk_header(hunk_line)
                    i += 1
                    while (
                        i < len(body)
                        and not body[i].startswith("@@@ ")
                        and not body[i].startswith("*** ")
                    ):
                        hunk.lines.append(body[i])
                        i += 1
                    hunks.append(hunk)
                else:
                    i += 1
            ops.append(UpdateFile(path=path, hunks=hunks))

        elif line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: ") :].strip()
            ops.append(DeleteFile(path=path))
            i += 1

        else:
            i += 1

    return ops


def _parse_hunk_header(header: str) -> Hunk:
    """Parse '@@@ -old_start,old_count +new_start,new_count @@@'."""
    # Format: @@@ -10,3 +10,4 @@@
    import re

    m = re.match(r"@@@\s+-(\d+),(\d+)\s+\+(\d+),(\d+)\s+@@@", header.strip())
    if not m:
        raise ValueError(f"Invalid hunk header: {header!r}")
    return Hunk(
        old_start=int(m.group(1)),
        old_count=int(m.group(2)),
        new_start=int(m.group(3)),
        new_count=int(m.group(4)),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _default_patch_root() -> Path:
    ctx = current_tool_context.get()
    if ctx and ctx.workspace_dir:
        return Path(ctx.workspace_dir).expanduser().resolve()
    return Path.cwd().resolve()


def _validate_path(path: str, root: Path | None = None) -> Path:
    """Resolve path and ensure it stays within the active patch root."""
    root = root if root is not None else _default_patch_root()
    reject_foreign_host_path(path, platform=os.name, workspace=root)
    raw = Path(path).expanduser()
    resolved = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path traversal detected: {path!r} resolves outside patch root")
    return resolved


def _memory_source_rel_path(path: str, root: Path) -> str | None:
    resolved = _validate_path(path, root)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None

    if rel.parts == ("MEMORY.md",):
        return "MEMORY.md"
    if len(rel.parts) >= 2 and rel.parts[0] == "memory" and rel.suffix == ".md":
        return rel.as_posix()
    return None


def _bootstrap_source_rel_path(path: str, root: Path) -> str | None:
    resolved = _validate_path(path, root)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    rel_path = rel.as_posix()
    if len(rel.parts) == 1 and rel_path in _BOOTSTRAP_SOURCE_FILENAMES:
        return rel_path
    return None


def _notify_memory_source_writes(ops: list[PatchOp], root: Path) -> None:
    ctx = current_tool_context.get()
    if ctx is None or ctx.on_memory_source_write is None:
        return

    seen: set[str] = set()
    for op in ops:
        rel = _memory_source_rel_path(op.path, root)
        if rel is None or rel in seen:
            continue
        seen.add(rel)
        ctx.on_memory_source_write(ctx.agent_id or "main", rel)


def _notify_bootstrap_source_writes(ops: list[PatchOp], root: Path) -> None:
    ctx = current_tool_context.get()
    if ctx is None or ctx.on_bootstrap_source_write is None:
        return

    seen: set[str] = set()
    for op in ops:
        rel = _bootstrap_source_rel_path(op.path, root)
        if rel is None or rel in seen:
            continue
        seen.add(rel)
        ctx.on_bootstrap_source_write(ctx.agent_id or "main", rel)


def _record_workspace_file_writes(ops: list[PatchOp], root: Path) -> None:
    for op in ops:
        if isinstance(op, AddFile):
            record_workspace_file_write(_validate_path(op.path, root))


@dataclass(frozen=True)
class _PatchApprovalPlan:
    command: str
    args: dict[str, object]
    params: dict[str, object]
    warning: str


def _normalize_patch_text(patch: str) -> str:
    return patch.replace("\r\n", "\n").replace("\r", "\n")


def _patch_fingerprint(patch: str) -> str:
    normalized = _normalize_patch_text(patch)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _op_name(op: PatchOp) -> str:
    if isinstance(op, AddFile):
        return "add"
    if isinstance(op, UpdateFile):
        return "update"
    return "delete"


def _patch_approval_plan(
    patch: str,
    ops: list[PatchOp],
    root: Path,
) -> tuple[dict[str, object] | None, _PatchApprovalPlan | None]:
    """Return a hard block or a patch-level approval plan when one is needed."""

    from opensquilla.sandbox.sensitive_paths import build_block_envelope, sensitive_path_marker
    from opensquilla.tools.builtin import filesystem
    from opensquilla.tools.write_policy import (
        match_workspace_write_deny,
        workspace_write_deny_block,
    )

    elevated_full = full_host_access_active()
    op_summary: list[dict[str, str]] = []
    outside_paths: list[str] = []
    workspace = filesystem._workspace_root()

    for op in ops:
        resolved = _validate_path(op.path, root)
        op_summary.append(
            {
                "op": _op_name(op),
                "path": op.path,
                "resolved_path": str(resolved),
            }
        )
        if not elevated_full:
            sensitive = sensitive_path_marker(str(resolved), workspace=workspace)
            if sensitive is not None:
                return (
                    build_block_envelope(
                        f"apply_patch {op.path}",
                        sensitive,
                        tool_name="apply_patch",
                    ),
                    None,
                )

        deny_match = match_workspace_write_deny(
            resolved,
            original_path=op.path,
            workspace=workspace,
        )
        if deny_match is not None:
            return workspace_write_deny_block("apply_patch", deny_match), None

        outside_workspace = filesystem._is_outside_workspace(resolved)
        memory_source_path = filesystem._memory_source_rel_path(resolved)
        if not elevated_full and outside_workspace and memory_source_path is None:
            outside_paths.append(str(resolved))

    if not outside_paths:
        return None, None

    fingerprint = _patch_fingerprint(patch)
    command = f"apply_patch {fingerprint}"
    warning = (
        f"apply_patch writes outside active workspace ({workspace})"
        if workspace is not None
        else "apply_patch writes to absolute paths outside the active workspace"
    )
    args: dict[str, object] = {
        "fingerprint": fingerprint,
        "ops": op_summary,
        "outside_paths": outside_paths,
        "workspace": str(workspace) if workspace is not None else None,
        "patch_root": str(root),
        "patch_length": len(patch),
    }
    ctx = current_tool_context.get()
    params: dict[str, object] = {
        "toolName": _APPLY_PATCH_APPROVAL_TOOL,
        "command": command,
        "args": args,
        "warning": warning,
        "sessionKey": ctx.session_key if ctx is not None and ctx.session_key else "",
        "agent": ctx.agent_id if ctx is not None else "",
        "mode": "patch",
    }
    return None, _PatchApprovalPlan(command=command, args=args, params=params, warning=warning)


def _approval_payload(
    status: str,
    approval_id: str,
    plan: _PatchApprovalPlan,
    message: str,
) -> dict[str, object]:
    return {
        "status": status,
        "approval_id": approval_id,
        "command": plan.command,
        "warning": plan.warning,
        "outside_paths": plan.args.get("outside_paths", []),
        "ops": plan.args.get("ops", []),
        "workspace": plan.args.get("workspace"),
        "patch_root": plan.args.get("patch_root"),
        "message": message,
    }


def _validate_patch_approval(
    approval_id: str,
    plan: _PatchApprovalPlan,
) -> dict[str, object] | None:
    from opensquilla.gateway.approval_queue import get_approval_queue

    queue = get_approval_queue()
    try:
        entry = queue.get(approval_id)
    except KeyError as exc:
        raise ToolError(str(exc)) from exc
    if entry.namespace != _APPLY_PATCH_APPROVAL_NAMESPACE:
        raise ToolError(f"Approval does not belong to exec namespace: {approval_id}")
    if entry.params.get("toolName") != _APPLY_PATCH_APPROVAL_TOOL:
        raise ToolError(f"Approval does not belong to apply_patch: {approval_id}")
    if entry.params.get("command") != plan.command or entry.params.get("args") != plan.args:
        raise ToolError("Approval does not match the requested patch")
    if entry.consumed:
        raise ToolError(f"Approval already consumed: {approval_id}")
    if not entry.resolved:
        return _approval_payload(
            "approval_pending",
            approval_id,
            plan,
            "Approval is still pending. Ask the user to approve.",
        )
    if not entry.approved:
        return _approval_payload(
            "approval_denied",
            approval_id,
            plan,
            "Approval was denied.",
        )
    try:
        queue.consume(approval_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return None


def _request_patch_approval(plan: _PatchApprovalPlan) -> dict[str, object] | None:
    from opensquilla.gateway.approval_queue import get_approval_queue

    queue = get_approval_queue()
    settings = queue.get_settings()
    approval_id = queue.request(
        namespace=_APPLY_PATCH_APPROVAL_NAMESPACE,
        params=plan.params,
    )
    if settings.mode == "auto-approve":
        queue.resolve(approval_id, True)
        queue.consume(approval_id)
        return None
    if settings.mode == "auto-deny":
        queue.resolve(approval_id, False)
        return _approval_payload(
            "approval_denied",
            approval_id,
            plan,
            "This patch was denied by the active approval policy.",
        )
    return _approval_payload(
        "approval_required",
        approval_id,
        plan,
        "Resolve this approval via exec.approval.resolve and retry with the returned approval_id.",
    )


def _gate_patch_ops(
    patch: str,
    ops: list[PatchOp],
    root: Path,
    approval_id: str | None,
) -> dict[str, object] | None:
    blocked, approval_plan = _patch_approval_plan(patch, ops, root)
    if blocked is not None:
        return blocked
    if approval_plan is None:
        return None
    if approval_id is not None:
        return _validate_patch_approval(approval_id, approval_plan)
    return _request_patch_approval(approval_plan)


# ---------------------------------------------------------------------------
# Apply operations
# ---------------------------------------------------------------------------


def _apply_hunk(file_lines: list[str], hunk: Hunk) -> list[str]:
    """Apply a single hunk to file_lines (0-indexed list of lines with newlines).

    Returns the new list of lines.
    """
    # old_start is 1-indexed; convert to 0-indexed
    pos = hunk.old_start - 1
    result = list(file_lines)

    # Verify context and deleted lines match
    check_pos = pos
    for raw in hunk.lines:
        if not raw:
            continue
        prefix = raw[0]
        content = raw[1:]
        if prefix in (" ", "-"):
            if check_pos >= len(result):
                raise ValueError(f"Hunk context/delete at line {check_pos + 1} exceeds file length")
            actual = result[check_pos].rstrip("\n")
            expected = content.rstrip("\n")
            if actual != expected:
                raise ValueError(
                    f"Context mismatch at line {check_pos + 1}: "
                    f"expected {expected!r}, got {actual!r}"
                )
            check_pos += 1

    # Now build new lines
    new_lines: list[str] = []
    src_pos = pos
    for raw in hunk.lines:
        if not raw:
            continue
        prefix = raw[0]
        content = raw[1:]
        if prefix == " ":
            new_lines.append(result[src_pos])
            src_pos += 1
        elif prefix == "-":
            src_pos += 1  # skip (delete)
        elif prefix == "+":
            # Preserve newline style: add \n if original lines have it
            if content.endswith("\n"):
                new_lines.append(content)
            else:
                new_lines.append(content + "\n")

    # Splice: replace [pos : pos + old_count] with new_lines
    return result[:pos] + new_lines + result[pos + hunk.old_count :]


def _apply_update(path: str, hunks: list[Hunk], root: Path | None = None) -> None:
    resolved = _validate_path(path, root)
    if not resolved.exists():
        raise FileNotFoundError(f"File not found for update: {path}")

    text = resolved.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Apply hunks in reverse order so earlier line numbers stay valid
    for hunk in sorted(hunks, key=lambda h: h.old_start, reverse=True):
        lines = _apply_hunk(lines, hunk)

    resolved.write_text("".join(lines), encoding="utf-8")


def _apply_add(path: str, content: str, root: Path | None = None) -> None:
    resolved = _validate_path(path, root)
    if resolved.exists():
        raise FileExistsError(f"File already exists: {path}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")


def _apply_delete(path: str, root: Path | None = None) -> None:
    resolved = _validate_path(path, root)
    if not resolved.exists():
        raise FileNotFoundError(f"File not found for deletion: {path}")
    resolved.unlink()


def _apply_ops(ops: list[PatchOp], root: Path | None = None) -> tuple[int, int, int]:
    """Execute all patch operations. Returns (added, modified, deleted) counts."""
    added = modified = deleted = 0
    for op in ops:
        if isinstance(op, AddFile):
            _apply_add(op.path, op.content, root)
            added += 1
        elif isinstance(op, UpdateFile):
            _apply_update(op.path, op.hunks, root)
            modified += 1
        elif isinstance(op, DeleteFile):
            _apply_delete(op.path, root)
            deleted += 1
    return added, modified, deleted


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@tool(
    name="apply_patch",
    description=(
        "Apply a structured patch to files. Supports adding, modifying, and deleting files "
        "using Begin Patch / End Patch markers with @@@ hunk headers."
    ),
    params={
        "patch": {
            "type": "string",
            "description": (
                "Patch text in Begin Patch format. "
                "Use '*** Begin Patch' / '*** End Patch' markers. "
                "Sections: '*** Add File: path', '*** Update File: path' with @@@ hunks, "
                "'*** Delete File: path'."
            ),
        },
        "approval_id": {
            "type": "string",
            "description": "Approval record to consume for patch writes outside the workspace.",
        },
    },
    required=["patch"],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="patch.apply",
        argv_factory=lambda a: ("patch.apply", str(len(a.get("patch", "") or ""))),
        request_factory=_patch_request,
        record_payload=False,
    ),
)
async def apply_patch(patch: str, approval_id: str | None = None) -> str:
    loop = asyncio.get_event_loop()
    root = _default_patch_root()
    ops = _parse_patch(patch)
    blocked = _gate_patch_ops(patch, ops, root, approval_id)
    if blocked is not None:
        return json.dumps(blocked, ensure_ascii=False)
    from opensquilla.tools.builtin import filesystem

    paths = tuple(_validate_path(op.path, root) for op in ops)
    sandbox_result = await filesystem._run_sandbox_operation_if_required(
        SandboxOperation.filesystem(
            kind="apply_patch",
            workspace=filesystem._filesystem_operation_workspace() or root,
            run_mode=filesystem._active_filesystem_run_mode(),
            root=root,
            paths=paths,
            patch=patch,
        )
    )
    if sandbox_result is not None:
        _record_workspace_file_writes(ops, root)
        _notify_memory_source_writes(ops, root)
        _notify_bootstrap_source_writes(ops, root)
        return str(getattr(sandbox_result, "message"))

    def _run() -> tuple[int, int, int]:
        return _apply_ops(ops, root)

    added, modified, deleted = await loop.run_in_executor(None, _run)
    _record_workspace_file_writes(ops, root)
    _notify_memory_source_writes(ops, root)
    _notify_bootstrap_source_writes(ops, root)
    parts = []
    if added:
        parts.append(f"{added} file(s) added")
    if modified:
        parts.append(f"{modified} file(s) modified")
    if deleted:
        parts.append(f"{deleted} file(s) deleted")
    summary = ", ".join(parts) if parts else "no changes"
    return f"Applied patch: {summary}"
