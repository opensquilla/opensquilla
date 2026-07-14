from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from opensquilla.sandbox import filesystem_worker


def test_load_payload_reads_json_object_from_stdin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = {"kind": "read_file", "path": "/workspace/notes.txt"}
    (tmp_path / "-").write_text('{"source": "path"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(filesystem_worker.sys, "stdin", StringIO(json.dumps(expected)))

    assert filesystem_worker._load_payload("-") == expected


@pytest.mark.parametrize(
    ("payload", "message"),
    (("{", "valid JSON"), ("[]", "must be an object")),
)
def test_load_payload_rejects_invalid_stdin_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: str,
    message: str,
) -> None:
    (tmp_path / "-").write_text('{"source": "path"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(filesystem_worker.sys, "stdin", StringIO(payload))

    with pytest.raises(ValueError, match=message):
        filesystem_worker._load_payload("-")


def test_load_payload_retains_path_compatibility(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    expected = {"kind": "list_dir", "path": "/workspace"}
    payload_path.write_text(json.dumps(expected), encoding="utf-8")

    assert filesystem_worker._load_payload(payload_path) == expected


def test_list_dir_keeps_siblings_when_symlink_target_is_missing(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "dangling").symlink_to(tmp_path / "missing-target")

    result = filesystem_worker._list_dir(
        {"path": str(tmp_path), "displayPath": str(tmp_path)}
    )

    assert "[file] ok.txt (5 bytes)" in result["message"]
    assert "[link] dangling (broken symlink)" in result["message"]


def test_list_dir_keeps_siblings_when_one_stat_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "ok.txt").write_text("hello", encoding="utf-8")
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("secret", encoding="utf-8")
    original_stat = Path.stat

    def selective_stat(path: Path, *args: object, **kwargs: object):
        if path == blocked:
            raise PermissionError("blocked for test")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", selective_stat)

    result = filesystem_worker._list_dir({"path": str(tmp_path)})

    assert "ok.txt" in result["message"]
    assert "[file] blocked.txt (metadata unavailable)" in result["message"]


def test_list_dir_preserves_requested_directory_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_iterdir = Path.iterdir

    def selective_iterdir(path: Path):
        if path == tmp_path:
            raise PermissionError("directory denied for test")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", selective_iterdir)

    with pytest.raises(PermissionError, match="directory denied for test"):
        filesystem_worker._list_dir({"path": str(tmp_path)})
