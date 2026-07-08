"""collect_bundle: zip contents, redaction bar, desktop derivation, best-effort.

All fixture data is synthetic. The fixture builds a fake OpenSquilla home +
log dir so no real state is ever read.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from opensquilla.observability.bundle import collect_bundle
from opensquilla.persistence.migrator import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

FAKE_KEY = "sk-FAKE1234567890abcdef"


def _make_home(tmp_path: Path, *, desktop: bool = False) -> tuple[Path, Path]:
    """Return (home_dir, log_dir) with synthetic state."""
    if desktop:
        user_data = tmp_path / "user-data"
        home = user_data / "opensquilla" / "state"
        (user_data / "logs").mkdir(parents=True)
        (user_data / "logs" / "desktop.log").write_text(
            '{"at":"2026-07-07T00:00:00Z","event":"launch"}\n', encoding="utf-8"
        )
        (user_data / "logs" / "gateway.log").write_text("gateway child out\n", encoding="utf-8")
        (user_data / "desktop-credential.json").write_text("{}", encoding="utf-8")
    else:
        home = tmp_path / "home"
    log_dir = home / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "debug.log").write_text(
        f"2026-07-07 [ERROR] opensquilla: boom api_key={FAKE_KEY}\n", encoding="utf-8"
    )
    day = datetime.now(UTC).strftime("%Y%m%d")
    (log_dir / f"decisions-{day}.jsonl").write_text('{"model":"fake"}\n', encoding="utf-8")
    (log_dir / f"traces-{day}.jsonl").write_text('{"kind":"turn_start"}\n', encoding="utf-8")
    (log_dir / f"turn-calls-{day}.jsonl").write_text('{"kind":"llm_request"}\n', encoding="utf-8")

    db = home / "sessions.db"
    apply_pending(str(db), MIGRATIONS_DIR)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO turn_errors (error_id, session_key, ts_ms, message) VALUES (?, ?, ?, ?)",
        ("abcd1234", "agent:main:test", int(datetime.now(UTC).timestamp() * 1000), "boom"),
    )
    conn.commit()
    conn.close()
    return home, log_dir


def _read_zip(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_default_bundle_contents_and_redaction(tmp_path) -> None:
    home, log_dir = _make_home(tmp_path)
    dest = tmp_path / "bundle.zip"

    result = collect_bundle(dest, home_dir=home, log_dir=log_dir)

    assert result.path == dest
    entries = _read_zip(dest)
    assert "manifest.json" in entries
    assert "logs/debug.log" in entries
    assert "errors.jsonl" in entries
    assert any(name.startswith("decisions/") for name in entries)
    assert any(name.startswith("traces/") for name in entries)
    # Default tier: no raw turn-call capture, no transcript content.
    assert not any("turn-calls" in name for name in entries)
    # Redaction bar: the fake key must not appear anywhere in the zip.
    blob = b"".join(entries.values())
    assert FAKE_KEY.encode() not in blob

    manifest = json.loads(entries["manifest.json"])
    assert manifest["bundle_schema"] == 1
    assert manifest["content_tier"] is False
    assert "opensquilla_version" in manifest
    errors = json.loads(b"[" + entries["errors.jsonl"].replace(b"\n", b",").rstrip(b",") + b"]")
    assert errors[0]["error_id"] == "abcd1234"


def test_content_tier_includes_turn_calls(tmp_path) -> None:
    home, log_dir = _make_home(tmp_path)
    dest = tmp_path / "bundle.zip"

    collect_bundle(dest, home_dir=home, log_dir=log_dir, include_content=True)

    entries = _read_zip(dest)
    assert any("turn-calls" in name for name in entries)
    manifest = json.loads(entries["manifest.json"])
    assert manifest["content_tier"] is True


def test_desktop_logs_are_derived_and_credential_excluded(tmp_path) -> None:
    home, log_dir = _make_home(tmp_path, desktop=True)
    dest = tmp_path / "bundle.zip"

    collect_bundle(dest, home_dir=home, log_dir=log_dir)

    entries = _read_zip(dest)
    assert "desktop/desktop.log" in entries
    assert "desktop/gateway.log" in entries
    assert not any("desktop-credential" in name for name in entries)


def test_missing_artifacts_become_collection_errors(tmp_path) -> None:
    home = tmp_path / "empty-home"
    log_dir = home / "logs"
    home.mkdir()
    dest = tmp_path / "bundle.zip"

    collect_bundle(dest, home_dir=home, log_dir=log_dir)

    assert dest.exists()  # bundle always succeeds
    entries = _read_zip(dest)
    manifest = json.loads(entries["manifest.json"])
    assert isinstance(manifest["collection_errors"], list)


def test_tail_cap_truncates_large_files(tmp_path) -> None:
    home, log_dir = _make_home(tmp_path)
    (home / "logs" / "gateway.log").parent.mkdir(parents=True, exist_ok=True)
    (home / "logs" / "gateway.log").write_bytes(b"x" * 6_000_000)
    dest = tmp_path / "bundle.zip"

    collect_bundle(dest, home_dir=home, log_dir=log_dir)

    entries = _read_zip(dest)
    assert len(entries["logs/gateway.log"]) < 5_100_000
    manifest = json.loads(entries["manifest.json"])
    assert any("gateway.log" in str(item) for item in manifest["truncations"])
