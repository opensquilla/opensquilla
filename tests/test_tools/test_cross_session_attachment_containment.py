"""Cross-session attachment read containment (F-WS-1 / #268).

Materialized attachments live under the shared per-agent workspace at
``.opensquilla/attachments/<session>/``. Strict-mode reads must allow the
current session's own subdir and shared authored files, but deny a sibling
session's subdir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.attachment_workspace import _safe_path_segment
from opensquilla.tools.builtin.filesystem import (
    _workspace_strict_candidate_marker,
    _workspace_strict_read_block,
)
from opensquilla.tools.types import ToolContext, current_tool_context


def _attach_dir(workspace: Path, session_id: str) -> Path:
    seg = _safe_path_segment(session_id, fallback="session")
    d = workspace / ".opensquilla" / "attachments" / seg
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ctx(workspace: Path, session_id: str) -> ToolContext:
    return ToolContext(
        is_owner=True,
        session_key=f"agent:main:webchat:{session_id}",
        workspace_dir=str(workspace),
        workspace_strict=True,
        artifact_session_id=session_id,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def test_foreign_session_attachment_read_is_blocked(workspace: Path) -> None:
    own = _attach_dir(workspace, "sid-a") / "own.pdf"
    own.write_bytes(b"%PDF-1.4\n")
    foreign = _attach_dir(workspace, "sid-b") / "secret.pdf"
    foreign.write_bytes(b"%PDF-1.4\n")

    token = current_tool_context.set(_ctx(workspace, "sid-a"))
    try:
        block = _workspace_strict_read_block("read_file", foreign, str(foreign))
        assert block is not None
        assert block["reason"] == "cross_session_attachment"
    finally:
        current_tool_context.reset(token)


def test_own_session_attachment_read_is_allowed(workspace: Path) -> None:
    own = _attach_dir(workspace, "sid-a") / "own.pdf"
    own.write_bytes(b"%PDF-1.4\n")

    token = current_tool_context.set(_ctx(workspace, "sid-a"))
    try:
        assert _workspace_strict_read_block("read_file", own, str(own)) is None
    finally:
        current_tool_context.reset(token)


def test_shared_authored_file_read_is_allowed(workspace: Path) -> None:
    # A file the agent authored at the workspace root is shared across sessions
    # on purpose ("many chats, one project") and must stay readable.
    authored = workspace / "notes.txt"
    authored.write_text("shared")
    _attach_dir(workspace, "sid-a")  # ensure attachments base exists

    token = current_tool_context.set(_ctx(workspace, "sid-a"))
    try:
        assert _workspace_strict_read_block("read_file", authored, str(authored)) is None
    finally:
        current_tool_context.reset(token)


def test_search_marker_blocks_foreign_attachment(workspace: Path) -> None:
    foreign = _attach_dir(workspace, "sid-b") / "secret.pdf"
    foreign.write_bytes(b"%PDF-1.4\n")

    token = current_tool_context.set(_ctx(workspace, "sid-a"))
    try:
        marker = _workspace_strict_candidate_marker("search_files", foreign, str(foreign))
        assert marker is not None
        assert "another session" in marker
    finally:
        current_tool_context.reset(token)
