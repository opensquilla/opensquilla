from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox import sensitive_paths
from opensquilla.sandbox.integration import reset_runtime
from opensquilla.tools.builtin import patch as patch_tool
from opensquilla.tools.registry import get_default_registry
from opensquilla.tools.types import (
    InteractionMode,
    ToolContext,
    ToolError,
    current_tool_context,
)


def _original_async(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    return fn.__wrapped__.__wrapped__  # type: ignore[attr-defined, no-any-return]


@pytest.fixture(autouse=True)
def _reset_approval_queue():
    reset_approval_queue()
    yield
    reset_approval_queue()


@pytest.fixture(autouse=True)
def _run_patch_executor_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run_in_executor_inline(self, executor, func, *args):
        future = self.create_future()
        try:
            future.set_result(func(*args))
        except Exception as exc:  # pragma: no cover - exercised by awaiting callers
            future.set_exception(exc)
        return future

    monkeypatch.setattr(
        patch_tool.asyncio.BaseEventLoop,
        "run_in_executor",
        _run_in_executor_inline,
    )


def test_apply_patch_schema_exposes_optional_approval_id() -> None:
    registered = get_default_registry().get("apply_patch")

    assert registered is not None
    assert "approval_id" in registered.spec.parameters
    assert "approval_id" not in registered.spec.required


@pytest.mark.asyncio
async def test_apply_patch_blocks_sensitive_path(tmp_path: Path) -> None:
    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Add File: .env
+TOKEN=secret
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "sensitive_path"
    assert not (tmp_path / ".env").exists()


@pytest.mark.asyncio
async def test_apply_patch_blocks_sensitive_key_file_suffix(tmp_path: Path) -> None:
    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Add File: id_rsa
+secret
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["sensitive_path"] == "/id_rsa"
    assert not (tmp_path / "id_rsa").exists()


@pytest.mark.asyncio
async def test_apply_patch_blocks_workspace_write_deny_glob(tmp_path: Path) -> None:
    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(tmp_path),
            workspace_write_deny_globs=["blocked/**"],
        )
    )
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Add File: blocked/generated.txt
+nope
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "workspace_write_deny"
    assert payload["matched_pattern"] == "blocked/**"
    assert not (tmp_path / "blocked" / "generated.txt").exists()


@pytest.mark.asyncio
async def test_apply_patch_allows_workspace_under_sensitive_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(sensitive_paths, "_SENSITIVE_PREFIXES", (str(tmp_path),))
    monkeypatch.setattr(
        sensitive_paths,
        "_WORKSPACE_PARENT_EXCEPTION_MARKERS",
        (str(tmp_path),),
    )
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Add File: docs/plan.md
+hello
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    assert result == "Applied patch: 1 file(s) added"
    assert (workspace / "docs" / "plan.md").read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_apply_patch_workspace_exception_keeps_leaf_secret_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(sensitive_paths, "_SENSITIVE_PREFIXES", (str(tmp_path),))
    monkeypatch.setattr(
        sensitive_paths,
        "_WORKSPACE_PARENT_EXCEPTION_MARKERS",
        (str(tmp_path),),
    )
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Add File: .env
+TOKEN=secret
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "sensitive_path"
    assert not (workspace / ".env").exists()


@pytest.mark.asyncio
async def test_apply_patch_workspace_escape_requests_patch_level_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "approval_required"
    assert payload["approval_id"]
    assert payload["outside_paths"] == [str(outside.resolve())]
    assert payload["ops"] == [
        {"op": "update", "path": "outside.txt", "resolved_path": str(outside.resolve())}
    ]
    assert payload["workspace"] == str(workspace.resolve())
    assert payload["patch_root"] == str(tmp_path.resolve())
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    params = pending[0]["params"]
    assert params["toolName"] == "apply_patch"
    assert params["args"]["fingerprint"]
    assert params["args"]["outside_paths"] == [str(outside.resolve())]
    assert outside.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_apply_patch_approved_reentry_applies_and_consumes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(workspace),
            session_key="agent:main:test",
            agent_id="main",
        )
    )
    patch = """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        first = json.loads(await apply_patch(patch))
        approval_id = first["approval_id"]
        get_approval_queue().resolve(approval_id, True)
        result = await apply_patch(patch, approval_id=approval_id)
        with pytest.raises(ToolError, match="already consumed"):
            await apply_patch(patch, approval_id=approval_id)
    finally:
        current_tool_context.reset(token)

    assert result == "Applied patch: 1 file(s) modified"
    assert outside.read_text(encoding="utf-8") == "new\n"
    assert get_approval_queue().get(approval_id).consumed is True


@pytest.mark.asyncio
async def test_apply_patch_rejects_mismatched_approval_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    patch = """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
    changed_patch = """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+evil
*** End Patch"""
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        first = json.loads(await apply_patch(patch))
        approval_id = first["approval_id"]
        get_approval_queue().resolve(approval_id, True)
        with pytest.raises(ToolError, match="does not match"):
            await apply_patch(changed_patch, approval_id=approval_id)
    finally:
        current_tool_context.reset(token)

    assert outside.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_apply_patch_pending_and_denied_approval_do_not_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    patch = """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        first = json.loads(await apply_patch(patch))
        approval_id = first["approval_id"]
        pending = json.loads(await apply_patch(patch, approval_id=approval_id))
        get_approval_queue().resolve(approval_id, False)
        denied = json.loads(await apply_patch(patch, approval_id=approval_id))
    finally:
        current_tool_context.reset(token)

    assert pending["status"] == "approval_pending"
    assert denied["status"] == "approval_denied"
    assert outside.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_apply_patch_rejects_foreign_namespace_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    patch = """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        first = json.loads(await apply_patch(patch))
        params = get_approval_queue().get(first["approval_id"]).params
        foreign_id = get_approval_queue().request("plugin", params=params)
        get_approval_queue().resolve(foreign_id, True)
        with pytest.raises(ToolError, match="exec namespace"):
            await apply_patch(patch, approval_id=foreign_id)
    finally:
        current_tool_context.reset(token)

    assert outside.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_apply_patch_sensitive_path_blocks_even_with_approval_id(tmp_path: Path) -> None:
    approval_id = get_approval_queue().request(
        "exec",
        {
            "toolName": "apply_patch",
            "command": "apply_patch pretend",
            "args": {},
        },
    )
    get_approval_queue().resolve(approval_id, True)
    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Add File: .env
+TOKEN=secret
*** End Patch""",
            approval_id=approval_id,
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "sensitive_path"
    assert not (tmp_path / ".env").exists()


@pytest.mark.asyncio
async def test_apply_patch_rejects_foreign_posix_path_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(patch_tool, "os", SimpleNamespace(name="nt"), raising=False)
    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        with pytest.raises(ToolError, match="foreign_host_path"):
            await apply_patch(
                """*** Begin Patch
*** Add File: /Users/a1/Desktop/report.txt
+new
*** End Patch"""
            )
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_apply_patch_rejects_foreign_windows_path_on_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(patch_tool, "os", SimpleNamespace(name="posix"), raising=False)
    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        with pytest.raises(ToolError, match="foreign_host_path"):
            await apply_patch(
                """*** Begin Patch
*** Add File: C:\\Users\\a1\\Desktop\\report.txt
+new
*** End Patch"""
            )
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_apply_patch_elevated_full_skips_outside_workspace_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace), elevated="full"))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    assert result == "Applied patch: 1 file(s) modified"
    assert outside.read_text(encoding="utf-8") == "new\n"
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_apply_patch_run_mode_full_skips_sandbox_wrapper_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_runtime()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            workspace_dir=str(workspace),
            run_mode="full",
            session_key="agent:main:test",
        )
    )
    try:
        result = await patch_tool.apply_patch(
            """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)
        reset_runtime()

    assert result == "Applied patch: 1 file(s) modified"
    assert outside.read_text(encoding="utf-8") == "new\n"
    assert get_approval_queue().list_pending("exec") == []


@pytest.mark.asyncio
async def test_apply_patch_unattended_bypass_requires_outside_workspace_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(patch_tool, "_default_patch_root", lambda: tmp_path.resolve())
    token = current_tool_context.set(
        ToolContext(
            workspace_dir=str(workspace),
            elevated="bypass",
            interaction_mode=InteractionMode.UNATTENDED,
        )
    )
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Update File: outside.txt
@@@ -1,1 +1,1 @@@
-old
+new
*** End Patch"""
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result)
    assert payload["status"] == "approval_required"
    assert outside.read_text(encoding="utf-8") == "old\n"
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
    assert pending[0]["params"]["toolName"] == "apply_patch"


@pytest.mark.asyncio
async def test_apply_patch_add_file_refuses_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("old\n", encoding="utf-8")
    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    apply_patch = _original_async(patch_tool.apply_patch)
    try:
        with pytest.raises(FileExistsError, match="File already exists"):
            await apply_patch(
                """*** Begin Patch
*** Add File: existing.txt
+new
*** End Patch"""
            )
    finally:
        current_tool_context.reset(token)
    assert target.read_text(encoding="utf-8") == "old\n"
