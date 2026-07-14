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
