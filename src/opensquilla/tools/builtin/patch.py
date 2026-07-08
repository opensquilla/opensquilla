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
from opensquilla.tools.mutation_receipts import (
    fingerprint_path,
    record_semantic_mutation_receipt,
)
from opensquilla.tools.path_policy import reject_foreign_host_path
from opensquilla.tools.registry import tool
from opensquilla.tools.run_mode import full_host_access_active
from opensquilla.tools.types import (
    RetryableToolInputError,
    current_tool_context,
)
from opensquilla.tools.write_tracking import (
    record_workspace_file_write,
    summarize_workspace_write_notes,
    workspace_write_progress_note,
)

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


def _patch_request(args: Mapping[str, Any]) -> FilesystemOperationRequest:
    """Build the sandbox request, carrying resolved patch target paths for policy checks."""
    patch_text = str(args.get("patch", "") or "")
    root = _default_patch_root()
    raw_path = args.get("path")
    if not patch_text.strip() and raw_path:
        try:
            patch_text = _read_patch_text_from_file(str(raw_path), root)
        except Exception:
            patch_text = str(args.get("patch", "") or "")
    resolved_paths: list[Path] = []
    try:
        for op in _parse_patch(patch_text):
            resolved = _validate_path(op.path, root)
            if resolved not in resolved_paths:
                resolved_paths.append(resolved)
    except Exception:
        resolved_paths = []
    return FilesystemOperationRequest(
        path=resolved_paths[0] if resolved_paths else None,
        paths=tuple(resolved_paths),
        patch=patch_text,
        root=root,
    )


@dataclass
class PlannedPatchWrite:
    path: str
    resolved: Path
    before: dict[str, Any]
    after_content: str | None
    operation: str


@dataclass
class AggregatedPatchWrite:
    path: str
    resolved: Path
    before: dict[str, Any]
    after_content: str | None
    operation: str
    operations: list[str] = field(default_factory=list)


_BOOTSTRAP_SOURCE_FILENAMES_FALLBACK = frozenset(
    {
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "TOOLS.md",
        "USER.md",
        "BOOTSTRAP.md",
        "HEARTBEAT.md",
    }
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_patch(patch_text: str) -> list[PatchOp]:
    """Parse patch text into a list of PatchOp objects."""
    lines = patch_text.splitlines()

    # Validate markers
    if not any(line.strip() == "*** Begin Patch" for line in lines):
        raise RetryableToolInputError(
            "apply_patch needs a patch beginning with '*** Begin Patch'. "
            "Retry with the exact Begin/End Patch wrapper."
        )
    if not any(line.strip() == "*** End Patch" for line in lines):
        raise RetryableToolInputError(
            "apply_patch needs a patch ending with '*** End Patch'. "
            "Retry with the exact Begin/End Patch wrapper."
        )

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
                if _is_hunk_header(hunk_line):
                    hunk = _parse_hunk_header(hunk_line)
                    i += 1
                    while (
                        i < len(body)
                        and not _is_hunk_header(body[i])
                        and not body[i].startswith("*** ")
                    ):
                        hunk.lines.append(body[i])
                        i += 1
                    hunks.append(hunk)
                else:
                    i += 1
            if not hunks:
                raise RetryableToolInputError(
                    f"Update File patch for {path!r} did not contain any hunk headers. "
                    "Use a standard unified hunk like '@@ -1,1 +1,1 @@' or "
                    "OpenSquilla's '@@@ -1,1 +1,1 @@@' format."
                )
            ops.append(UpdateFile(path=path, hunks=hunks))

        elif line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: ") :].strip()
            ops.append(DeleteFile(path=path))
            i += 1

        else:
            i += 1

    if not ops:
        raise RetryableToolInputError(
            "apply_patch did not find any file operations. Include at least one "
            "'*** Add File:', '*** Update File:', or '*** Delete File:' section."
        )

    return ops


def _is_hunk_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("@@ ") or stripped.startswith("@@@ ")


def _parse_hunk_header(header: str) -> Hunk:
    """Parse '@@ -old,count +new,count @@' or '@@@ -old,count +new,count @@@'."""
    import re

    m = re.match(
        r"@@@?\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@@?",
        header.strip(),
    )
    if not m:
        raise RetryableToolInputError(
            "Invalid apply_patch hunk header. Use '@@ -old,count +new,count @@' "
            "or '@@@ -old,count +new,count @@@'."
        )
    return Hunk(
        old_start=int(m.group(1)),
        old_count=int(m.group(2) or "1"),
        new_start=int(m.group(3)),
        new_count=int(m.group(4) or "1"),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _default_patch_root() -> Path:
    ctx = current_tool_context.get()
    if ctx and ctx.workspace_dir:
        return Path(ctx.workspace_dir).expanduser().resolve()
    return Path.cwd().resolve()


def _patch_file_read_roots(root: Path) -> list[Path]:
    roots = [root]
    ctx = current_tool_context.get()
    scratch_dir = getattr(ctx, "scratch_dir", None) if ctx is not None else None
    if scratch_dir:
        roots.append(Path(scratch_dir).expanduser().resolve(strict=False))
    return roots


def _read_patch_text_from_file(path: str, root: Path) -> str:
    raw = Path(path).expanduser()
    resolved = (
        (root / raw).resolve(strict=False)
        if not raw.is_absolute()
        else raw.resolve(strict=False)
    )
    allowed_roots = _patch_file_read_roots(root)
    if not any(resolved.is_relative_to(allowed_root) for allowed_root in allowed_roots):
        allowed = ", ".join(str(allowed_root) for allowed_root in allowed_roots)
        raise RetryableToolInputError(
            "apply_patch path must point to a UTF-8 patch file under the workspace "
            f"or configured scratch directory. Allowed roots: {allowed}."
        )
    if not resolved.is_file():
        raise RetryableToolInputError(
            f"apply_patch path does not exist or is not a file: {path}. "
            "Retry with patch text or a valid patch file path."
        )
    return resolved.read_text(encoding="utf-8")


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
    try:
        from opensquilla.identity.workspace import BOOTSTRAP_FILENAMES

        bootstrap_source_filenames = frozenset(BOOTSTRAP_FILENAMES)
    except Exception:
        bootstrap_source_filenames = _BOOTSTRAP_SOURCE_FILENAMES_FALLBACK

    if len(rel.parts) == 1 and rel_path in bootstrap_source_filenames:
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
            record_workspace_file_write(
                _validate_path(op.path, root),
                operation="apply_patch_add",
                created=True,
            )
        elif isinstance(op, UpdateFile):
            record_workspace_file_write(
                _validate_path(op.path, root),
                operation="apply_patch_update",
                created=False,
            )
        elif isinstance(op, DeleteFile):
            record_workspace_file_write(
                _validate_path(op.path, root),
                operation="apply_patch_delete",
                created=False,
            )


def _workspace_write_note_summary(ops: list[PatchOp], root: Path) -> str:
    paths = [_validate_path(op.path, root) for op in ops]
    return summarize_workspace_write_notes(paths)


def _gate_patch_ops(
    ops: list[PatchOp],
    root: Path,
    approval_id: str | None,
) -> dict[str, object] | None:
    """Return a hard block / sandbox approval payload, or None to proceed."""

    from opensquilla.sandbox.sensitive_paths import build_block_envelope, sensitive_path_marker
    from opensquilla.tools.builtin import filesystem
    from opensquilla.tools.write_policy import (
        match_workspace_write_deny,
        workspace_write_deny_block,
    )

    elevated_full = full_host_access_active()
    workspace = filesystem._workspace_root()

    for op in ops:
        resolved = _validate_path(op.path, root)
        if not elevated_full:
            sensitive = sensitive_path_marker(str(resolved), workspace=workspace)
            if sensitive is not None:
                return build_block_envelope(
                    f"apply_patch {op.path}",
                    sensitive,
                    tool_name="apply_patch",
                )

        deny_match = match_workspace_write_deny(
            resolved,
            original_path=op.path,
            workspace=workspace,
        )
        if deny_match is not None:
            return workspace_write_deny_block("apply_patch", deny_match)

        path_access = filesystem._sandbox_path_access_envelope(
            resolved,
            write=True,
            approval_id=approval_id,
        )
        if path_access is not None:
            return path_access

        if filesystem._is_outside_workspace(resolved):
            if filesystem._memory_source_rel_path(resolved) is not None:
                continue
            if filesystem._active_sandbox_mount_allows(resolved, write=True):
                continue
            if elevated_full:
                continue
            return filesystem._outside_workspace_write_block(
                "apply_patch",
                resolved,
                op.path,
            )

    return None


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
                raise RetryableToolInputError(
                    "apply_patch hunk context/delete exceeds file length at "
                    f"line {check_pos + 1}. Read the current file content and retry "
                    "with hunk line numbers and context that match the file."
                )
            actual = result[check_pos].rstrip("\n")
            expected = content.rstrip("\n")
            if actual != expected:
                raise RetryableToolInputError(
                    f"apply_patch context mismatch at line {check_pos + 1}: "
                    f"expected {expected!r}, got {actual!r}. Read the current file "
                    "content and retry with exact surrounding context."
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


def _fingerprint_content(content: str | None) -> dict[str, Any]:
    if content is None:
        return {"exists": False, "size": 0, "sha256": None}
    data = content.encode("utf-8")
    return {
        "exists": True,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _apply_update_content(content: str, hunks: list[Hunk]) -> str:
    lines = content.splitlines(keepends=True)

    # Apply hunks in reverse order so earlier line numbers stay valid
    for hunk in sorted(hunks, key=lambda h: h.old_start, reverse=True):
        lines = _apply_hunk(lines, hunk)

    return "".join(lines)


def _plan_add(op: AddFile, root: Path | None = None) -> PlannedPatchWrite:
    resolved = _validate_path(op.path, root)
    if resolved.exists():
        raise RetryableToolInputError(
            f"apply_patch Add File target already exists: {op.path}. "
            "Retry with Update File for existing files."
        )
    return PlannedPatchWrite(
        path=op.path,
        resolved=resolved,
        before=fingerprint_path(resolved),
        after_content=op.content,
        operation="apply_patch_add",
    )


def _plan_update(op: UpdateFile, root: Path | None = None) -> PlannedPatchWrite:
    resolved = _validate_path(op.path, root)
    if not resolved.exists():
        raise RetryableToolInputError(
            f"apply_patch could not find file to update: {op.path}. "
            "Check the target path, then retry with an existing file or use Add File."
        )

    before = fingerprint_path(resolved)
    text = resolved.read_text(encoding="utf-8")

    return PlannedPatchWrite(
        path=op.path,
        resolved=resolved,
        before=before,
        after_content=_apply_update_content(text, op.hunks),
        operation="apply_patch_update",
    )


def _plan_delete(op: DeleteFile, root: Path | None = None) -> PlannedPatchWrite:
    resolved = _validate_path(op.path, root)
    if not resolved.exists():
        raise RetryableToolInputError(
            f"apply_patch could not find file to delete: {op.path}. "
            "Check the target path or remove this Delete File operation."
        )
    return PlannedPatchWrite(
        path=op.path,
        resolved=resolved,
        before=fingerprint_path(resolved),
        after_content=None,
        operation="apply_patch_delete",
    )


def _plan_ops(ops: list[PatchOp], root: Path | None = None) -> list[PlannedPatchWrite]:
    planned: list[PlannedPatchWrite] = []
    virtual_content: dict[Path, str | None] = {}
    for op in ops:
        resolved = _validate_path(op.path, root)
        if resolved not in virtual_content:
            if isinstance(op, AddFile):
                item = _plan_add(op, root)
            elif isinstance(op, UpdateFile):
                item = _plan_update(op, root)
            else:
                item = _plan_delete(op, root)
        else:
            current_content = virtual_content[resolved]
            before = _fingerprint_content(current_content)
            if isinstance(op, AddFile):
                if current_content is not None:
                    raise RetryableToolInputError(
                        f"apply_patch Add File target already exists: {op.path}. "
                        "Retry with Update File for existing files."
                    )
                item = PlannedPatchWrite(
                    path=op.path,
                    resolved=resolved,
                    before=before,
                    after_content=op.content,
                    operation="apply_patch_add",
                )
            elif isinstance(op, UpdateFile):
                if current_content is None:
                    raise RetryableToolInputError(
                        f"apply_patch could not find file to update: {op.path}. "
                        "Check the target path, then retry with an existing file or use "
                        "Add File."
                    )
                item = PlannedPatchWrite(
                    path=op.path,
                    resolved=resolved,
                    before=before,
                    after_content=_apply_update_content(current_content, op.hunks),
                    operation="apply_patch_update",
                )
            else:
                if current_content is None:
                    raise RetryableToolInputError(
                        f"apply_patch could not find file to delete: {op.path}. "
                        "Check the target path or remove this Delete File operation."
                    )
                item = PlannedPatchWrite(
                    path=op.path,
                    resolved=resolved,
                    before=before,
                    after_content=None,
                    operation="apply_patch_delete",
                )
        planned.append(item)
        virtual_content[item.resolved] = item.after_content
    return planned


def _path_ancestors(path: Path) -> list[Path]:
    ancestors: list[Path] = []
    current = path
    while current != current.parent:
        ancestors.append(current)
        current = current.parent
    ancestors.append(current)
    return list(reversed(ancestors))


def _preflight_write_parent(path: Path, states: dict[Path, str]) -> None:
    for ancestor in _path_ancestors(path.parent):
        state = states.get(ancestor)
        if state == "file":
            raise FileExistsError(str(ancestor))
        if state == "dir":
            continue
        if state is None and ancestor.exists() and not ancestor.is_dir():
            raise FileExistsError(str(ancestor))
        states[ancestor] = "dir"


def _preflight_planned_writes(planned: list[PlannedPatchWrite]) -> None:
    states: dict[Path, str] = {}
    for item in planned:
        state = states.get(item.resolved)
        if item.after_content is None:
            if state is None:
                if not item.resolved.exists():
                    raise FileNotFoundError(str(item.resolved))
                if item.resolved.is_dir() and not item.resolved.is_symlink():
                    raise IsADirectoryError(str(item.resolved))
            elif state == "absent":
                raise FileNotFoundError(str(item.resolved))
            elif state == "dir":
                raise IsADirectoryError(str(item.resolved))
            states[item.resolved] = "absent"
            continue

        _preflight_write_parent(item.resolved, states)
        state = states.get(item.resolved)
        if state == "dir":
            raise IsADirectoryError(str(item.resolved))
        if state is None and item.resolved.is_dir() and not item.resolved.is_symlink():
            raise IsADirectoryError(str(item.resolved))
        states[item.resolved] = "file"


def _aggregate_planned_writes(
    planned: list[PlannedPatchWrite],
) -> list[AggregatedPatchWrite]:
    aggregated: dict[Path, AggregatedPatchWrite] = {}
    ordered: list[AggregatedPatchWrite] = []
    for item in planned:
        existing = aggregated.get(item.resolved)
        if existing is None:
            existing = AggregatedPatchWrite(
                path=item.path,
                resolved=item.resolved,
                before=item.before,
                after_content=item.after_content,
                operation="apply_patch",
                operations=[item.operation],
            )
            aggregated[item.resolved] = existing
            ordered.append(existing)
        else:
            existing.after_content = item.after_content
            existing.operations.append(item.operation)
    return ordered


def _commit_planned_writes(planned: list[PlannedPatchWrite]) -> tuple[int, int, int]:
    _preflight_planned_writes(planned)
    added = modified = deleted = 0
    for item in planned:
        if item.after_content is None:
            item.resolved.unlink()
            deleted += 1
        else:
            item.resolved.parent.mkdir(parents=True, exist_ok=True)
            item.resolved.write_text(item.after_content, encoding="utf-8")
            if item.operation == "apply_patch_add":
                added += 1
            else:
                modified += 1
    return added, modified, deleted


def _apply_ops(
    ops: list[PatchOp],
    root: Path | None = None,
) -> tuple[int, int, int, list[PlannedPatchWrite]]:
    """Execute all patch operations after planning them in memory."""
    planned = _plan_ops(ops, root)
    added, modified, deleted = _commit_planned_writes(planned)
    return added, modified, deleted, planned


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@tool(
    name="apply_patch",
    description=(
        "Apply a structured patch to files. Supports adding, modifying, and deleting files "
        "using Begin Patch / End Patch markers with unified @@ or @@@ hunk headers. "
        "Prefer this for multi-line or larger source edits where edit_file JSON would "
        "be long or fragile."
    ),
    params={
        "patch": {
            "type": "string",
            "description": (
                "Patch text in Begin Patch format. "
                "Use '*** Begin Patch' / '*** End Patch' markers. "
                "Sections: '*** Add File: path', '*** Update File: path' with "
                "standard @@ hunks or @@@ hunks, and '*** Delete File: path'."
            ),
        },
        "path": {
            "type": "string",
            "description": (
                "Optional path to a UTF-8 file containing patch text. "
                "The file must be under the active workspace or configured scratch directory. "
                "Use this only when patch text was already written to a scratch file."
            ),
        },
        "approval_id": {
            "type": "string",
            "description": "Sandbox path approval record for patch writes outside the workspace.",
        },
    },
    required=[],
    sandbox=SandboxToolDescriptor.filesystem(
        kind="patch.apply",
        argv_factory=lambda a: (
            "patch.apply",
            str(len(a.get("patch", "") or "")),
            "path" if a.get("path") else "inline",
        ),
        request_factory=_patch_request,
        record_payload=False,
    ),
)
async def apply_patch(
    patch: str | None = None,
    approval_id: str | None = None,
    path: str | None = None,
) -> str:
    loop = asyncio.get_event_loop()
    root = _default_patch_root()
    if (patch is None or not patch.strip()) and path:
        patch = _read_patch_text_from_file(path, root)
    if patch is None or not patch.strip():
        raise RetryableToolInputError(
            "apply_patch requires either patch text or path to a UTF-8 patch file. "
            "Retry with the `patch` argument, or write the patch under the scratch "
            "directory and pass its `path`."
        )
    ops = _parse_patch(patch)
    blocked = _gate_patch_ops(ops, root, approval_id)
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

    def _run() -> tuple[int, int, int, list[PlannedPatchWrite]]:
        return _apply_ops(ops, root)

    added, modified, deleted, planned = await loop.run_in_executor(None, _run)
    _record_workspace_file_writes(ops, root)
    write_note_summary = _workspace_write_note_summary(ops, root)
    ctx = current_tool_context.get()
    write_progress_note = (
        workspace_write_progress_note() if ctx is not None and ctx.is_owner else ""
    )
    for item in _aggregate_planned_writes(planned):
        record_semantic_mutation_receipt(
            tool_name="apply_patch",
            path=item.resolved,
            operation=item.operation,
            before=item.before,
            after=fingerprint_path(item.resolved),
            partial=False,
            metadata={
                "patch_path": item.path,
                "operations": item.operations,
                "operation_count": len(item.operations),
            },
        )
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
    return (
        f"Applied patch: {summary}"
        f"{write_note_summary}"
        f"{write_progress_note}"
    )
