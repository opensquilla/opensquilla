from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.tools.source_edit_contract import (
    SourceEditContractError,
    apply_line_edits,
    build_diff_summary,
    build_line_receipt,
    source_revision_for_path,
)


def test_source_revision_changes_when_file_content_changes(tmp_path: Path) -> None:
    path = tmp_path / "src.py"
    path.write_text("alpha\n", encoding="utf-8")
    first = source_revision_for_path(path)

    path.write_text("beta\n", encoding="utf-8")
    second = source_revision_for_path(path)

    assert first.startswith("file_")
    assert second.startswith("file_")
    assert first != second


def test_build_line_receipt_returns_plain_lines_without_read_file_prefixes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "src.py"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    receipt = build_line_receipt(path, start_line=2, end_line=3, display_path="src.py")

    assert receipt["status"] == "success"
    assert receipt["path"] == "src.py"
    assert receipt["range"] == [2, 3]
    assert receipt["lines"] == [
        {"line": 2, "text": "two"},
        {"line": 3, "text": "three"},
    ]
    assert receipt["revision"].startswith("file_")


def test_apply_line_edits_replaces_inclusive_ranges_atomically() -> None:
    original = "a\nb\nc\nd\n"

    updated = apply_line_edits(
        original,
        [{"start_line": 2, "end_line": 3, "replacement": "B\nC\n"}],
    )

    assert updated == "a\nB\nC\nd\n"


def test_apply_line_edits_rejects_overlapping_ranges() -> None:
    with pytest.raises(SourceEditContractError, match="overlap"):
        apply_line_edits(
            "a\nb\nc\n",
            [
                {"start_line": 1, "end_line": 2, "replacement": "x\n"},
                {"start_line": 2, "end_line": 3, "replacement": "y\n"},
            ],
        )


def test_build_diff_summary_uses_readable_unified_diff_headers() -> None:
    summary = build_diff_summary("a\nb\n", "a\nB\n", path="src/app.py")

    assert summary.startswith("--- a/src/app.py\n+++ b/src/app.py\n@@")
    assert "\n-b\n+B\n" in summary
