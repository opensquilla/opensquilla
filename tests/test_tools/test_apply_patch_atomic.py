from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from opensquilla.tools.builtin import patch as patch_tool
from opensquilla.tools.mutation_receipts import fingerprint_file
from opensquilla.tools.types import ToolContext, current_tool_context


def _original_async(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    return fn.__wrapped__.__wrapped__  # type: ignore[attr-defined, no-any-return]


@pytest.fixture
def patch_context(
    tmp_path: Path,
) -> Iterator[tuple[Path, ToolContext, list[dict[str, Any]]]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[dict[str, Any]] = []
    ctx = ToolContext(
        workspace_dir=str(workspace),
        session_key="agent:main:test",
        on_runtime_event=events.append,
    )
    token = current_tool_context.set(ctx)
    try:
        yield workspace, ctx, events
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_apply_patch_failure_does_not_leave_partial_mutation(
    patch_context: tuple[Path, ToolContext, list[dict[str, Any]]],
) -> None:
    workspace, ctx, _events = patch_context
    first = workspace / "src" / "first.py"
    second = workspace / "src" / "second.py"
    first.parent.mkdir(parents=True)
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two\n", encoding="utf-8")
    apply_patch = _original_async(patch_tool.apply_patch)

    patch = """*** Begin Patch
*** Update File: src/first.py
@@ -1,1 +1,1 @@
-one
+ONE
*** Update File: src/second.py
@@ -1,1 +1,1 @@
-wrong
+TWO
*** End Patch"""

    with pytest.raises(Exception):
        await apply_patch(patch=patch)

    assert first.read_text(encoding="utf-8") == "one\n"
    assert second.read_text(encoding="utf-8") == "two\n"
    assert ctx.workspace_mutation_receipts == []


@pytest.mark.asyncio
async def test_apply_patch_success_records_semantic_mutation_receipt(
    patch_context: tuple[Path, ToolContext, list[dict[str, Any]]],
) -> None:
    workspace, ctx, events = patch_context
    target = workspace / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("one\n", encoding="utf-8")
    apply_patch = _original_async(patch_tool.apply_patch)

    result = await apply_patch(
        patch="""*** Begin Patch
*** Update File: src/app.py
@@ -1,1 +1,1 @@
-one
+ONE
*** End Patch"""
    )

    assert "1 file(s) modified" in result
    assert target.read_text(encoding="utf-8") == "ONE\n"
    receipt = ctx.workspace_mutation_receipts[-1]
    assert receipt["tool"] == "apply_patch"
    assert receipt["changed"] is True
    assert receipt["relative_path"] == "src/app.py"
    assert any(
        event.get("name") == "workspace.semantic_mutation_receipt" for event in events
    )


@pytest.mark.asyncio
async def test_apply_patch_commit_preflight_parent_file_conflict_is_atomic(
    patch_context: tuple[Path, ToolContext, list[dict[str, Any]]],
) -> None:
    workspace, ctx, _events = patch_context
    target = workspace / "first.txt"
    blocked_parent = workspace / "blocked_parent"
    target.write_text("one\n", encoding="utf-8")
    blocked_parent.write_text("not a directory\n", encoding="utf-8")
    apply_patch = _original_async(patch_tool.apply_patch)

    patch = """*** Begin Patch
*** Update File: first.txt
@@ -1,1 +1,1 @@
-one
+ONE
*** Add File: blocked_parent/new.txt
+new
*** End Patch"""

    with pytest.raises(Exception):
        await apply_patch(patch=patch)

    assert target.read_text(encoding="utf-8") == "one\n"
    assert blocked_parent.read_text(encoding="utf-8") == "not a directory\n"
    assert ctx.workspace_mutation_receipts == []


@pytest.mark.asyncio
async def test_apply_patch_commit_preflight_child_first_parent_file_conflict_is_atomic(
    patch_context: tuple[Path, ToolContext, list[dict[str, Any]]],
) -> None:
    workspace, ctx, _events = patch_context
    apply_patch = _original_async(patch_tool.apply_patch)

    patch = """*** Begin Patch
*** Add File: a/b.txt
+child
*** Add File: a
+parent
*** End Patch"""

    with pytest.raises(Exception):
        await apply_patch(patch=patch)

    assert not (workspace / "a").exists()
    assert not (workspace / "a" / "b.txt").exists()
    assert ctx.workspace_mutation_receipts == []


@pytest.mark.asyncio
async def test_apply_patch_repeated_updates_to_same_file_compose_in_memory(
    patch_context: tuple[Path, ToolContext, list[dict[str, Any]]],
) -> None:
    workspace, ctx, _events = patch_context
    target = workspace / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    before = fingerprint_file(target)
    apply_patch = _original_async(patch_tool.apply_patch)

    await apply_patch(
        patch="""*** Begin Patch
*** Update File: src/app.py
@@ -1,1 +1,1 @@
-alpha
+ALPHA
*** Update File: src/app.py
@@ -2,1 +2,1 @@
-beta
+BETA
*** End Patch"""
    )

    assert target.read_text(encoding="utf-8") == "ALPHA\nBETA\n"
    after = fingerprint_file(target)
    assert len(ctx.workspace_mutation_receipts) == 1
    receipt = ctx.workspace_mutation_receipts[0]
    assert receipt["tool"] == "apply_patch"
    assert receipt["operation"] == "apply_patch"
    assert receipt["relative_path"] == "src/app.py"
    assert receipt["before"] == before
    assert receipt["after"] == after
    assert receipt["operation_count"] == 2
