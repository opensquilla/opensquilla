from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from opensquilla.tools.builtin import filesystem as fs
from opensquilla.tools.builtin import git, patch, shell
from opensquilla.tools.types import CallerKind, ToolContext, ToolError, current_tool_context


@contextmanager
def tool_context(
    workspace: Path,
    *,
    strict: bool = True,
) -> Iterator[None]:
    token = current_tool_context.set(
        ToolContext(
            caller_kind=CallerKind.CLI,
            channel_kind="cli",
            channel_id="cli:test",
            workspace_dir=str(workspace),
            workspace_strict=strict,
        )
    )
    try:
        yield
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_read_file_offset_limit_does_not_call_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "big.log"
    target.write_text("".join(f"line {i}\n" for i in range(1, 1001)), encoding="utf-8")

    def fail_read_bytes(self: Path) -> bytes:  # pragma: no cover - must not be called
        raise AssertionError("read_bytes should not be used for bounded read_file")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    output = await fs.read_file(str(target), offset=500, limit=2)

    assert "500\tline 500" in output
    assert "501\tline 501" in output
    assert "499\tline 499" not in output
    assert "502\tline 502" not in output


@pytest.mark.asyncio
async def test_read_file_binary_detection_samples_first_8192_bytes(tmp_path: Path) -> None:
    first_sample = tmp_path / "first.txt"
    first_sample.write_bytes(b"abc\x00def")
    with pytest.raises(ToolError, match="NUL"):
        await fs.read_file(str(first_sample), limit=1)

    later_nul = tmp_path / "later.txt"
    later_nul.write_bytes(("ok\n" * 4100).encode("utf-8") + b"\x00tail\n")
    output = await fs.read_file(str(later_nul), offset=1, limit=1)
    assert output == "1\tok\n"


@pytest.mark.asyncio
async def test_read_file_invalid_utf8_before_selected_window_errors(tmp_path: Path) -> None:
    target = tmp_path / "invalid.txt"
    target.write_bytes(b"ok\n\xff\nlater\n")
    with pytest.raises(ToolError, match="not valid UTF-8"):
        await fs.read_file(str(target), offset=3, limit=1)


@pytest.mark.asyncio
async def test_workspace_strict_allows_inside_workspace(tmp_path: Path) -> None:
    text_file = tmp_path / "inside.txt"
    text_file.write_text("needle\n", encoding="utf-8")
    csv_file = tmp_path / "inside.csv"
    csv_file.write_text("a,b\n1,2\n", encoding="utf-8")

    with tool_context(tmp_path):
        assert "1\tneedle" in await fs.read_file(str(text_file))
        assert "inside.csv" in await fs.read_spreadsheet(str(csv_file))
        assert "inside.txt" in await fs.list_dir(str(tmp_path))
        assert "inside.txt" in await fs.glob_search("*.txt", path=str(tmp_path))
        assert "needle" in await fs.grep_search("needle", path=str(tmp_path))


@pytest.mark.asyncio
async def test_workspace_strict_blocks_outside_base_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "outside.txt"
    outside_file.write_text("secret\n", encoding="utf-8")
    outside_csv = outside / "outside.csv"
    outside_csv.write_text("a,b\n1,2\n", encoding="utf-8")

    with tool_context(workspace):
        for call in (
            lambda: fs.read_file(str(outside_file)),
            lambda: fs.read_spreadsheet(str(outside_csv)),
            lambda: fs.list_dir(str(outside)),
            lambda: fs.glob_search("*.txt", path=str(outside)),
            lambda: fs.grep_search("secret", path=str(outside)),
        ):
            with pytest.raises(ToolError, match="outside active workspace"):
                await call()


@pytest.mark.asyncio
async def test_workspace_strict_blocks_nonexistent_outside_before_not_found(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_missing = tmp_path / "outside" / "missing.txt"
    outside_missing_dir = tmp_path / "outside" / "missing-dir"

    with tool_context(workspace):
        for call in (
            lambda: fs.read_file(str(outside_missing)),
            lambda: fs.list_dir(str(outside_missing_dir)),
            lambda: fs.glob_search("*.txt", path=str(outside_missing_dir)),
            lambda: fs.grep_search("needle", path=str(outside_missing_dir)),
        ):
            with pytest.raises(ToolError, match="outside active workspace"):
                await call()


@pytest.mark.asyncio
async def test_workspace_strict_disabled_allows_outside_read_when_not_sensitive(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")

    with tool_context(workspace, strict=False):
        assert "outside" in await fs.read_file(str(outside))


def _make_symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unsupported/unavailable: {exc}")


def test_local_execution_workdir_boundary_resolves_against_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    try:
        expected = str((workspace / "nested").resolve())
        assert str(fs._resolve_workdir("nested")) == expected
        assert shell._effective_workdir("nested") == expected
        assert git._effective_workdir("nested") == expected
        assert patch._default_patch_root() == workspace.resolve()
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_workspace_strict_blocks_read_file_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = workspace / "link.txt"
    _make_symlink(link, outside)

    with tool_context(workspace):
        with pytest.raises(ToolError, match="outside active workspace"):
            await fs.read_file(str(link))


@pytest.mark.asyncio
async def test_workspace_strict_surfaces_list_dir_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = workspace / "link.txt"
    _make_symlink(link, outside)

    with tool_context(workspace):
        output = await fs.list_dir(str(workspace))

    assert "[blocked]" in output
    assert "outside active workspace" in output


@pytest.mark.asyncio
async def test_workspace_strict_surfaces_glob_and_grep_symlink_escape(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("needle\n", encoding="utf-8")
    link = workspace / "link.txt"
    _make_symlink(link, outside)

    with tool_context(workspace):
        globbed = await fs.glob_search("*.txt", path=str(workspace))
        grepped = await fs.grep_search("needle", path=str(workspace))

    assert "[blocked]" in globbed
    assert "outside active workspace" in globbed
    assert "[blocked]" in grepped
    assert "outside active workspace" in grepped


@pytest.mark.asyncio
async def test_sensitive_path_priority_over_workspace_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret\n", encoding="utf-8")

    monkeypatch.setattr(
        "opensquilla.sandbox.sensitive_paths.is_sensitive_path",
        lambda path: "/secret" if "secret" in path else None,
    )

    with tool_context(workspace):
        file_result = json.loads(await fs.read_file(str(outside_file)))
        dir_result = json.loads(await fs.list_dir(str(outside)))

    assert file_result["reason"] == "sensitive_path"
    assert dir_result["reason"] == "sensitive_path"
    assert "workspace_strict" not in file_result.get("message", "")
    assert "workspace_strict" not in dir_result.get("message", "")
