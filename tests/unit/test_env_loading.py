"""Loading resilience for .env files.

``load_env`` runs at CLI import time, so a broken ``~/.opensquilla/.env``
(one latin-1 byte is enough) used to kill every command — including the
onboarding wizard that could repair the file — with a raw
``UnicodeDecodeError`` before Typer even started. These tests pin the
recovery contract: a bad file is skipped with a single stderr warning while
every valid file keeps loading exactly as before, and **stdout stays byte
clean** — the warning used to also go through an unconfigured structlog
logger whose PrintLogger writes to stdout, corrupting machine-readable
output such as ``onboard status --json``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opensquilla import env as env_mod


def _isolate_global_env(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    home.mkdir()
    monkeypatch.setattr(env_mod, "default_opensquilla_home", lambda: home)


def test_load_env_survives_non_utf8_home_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    _isolate_global_env(monkeypatch, home)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_BAD_KEY", raising=False)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_GOOD_KEY", raising=False)

    # \xe9 is latin-1 "e-acute" — a single byte that is invalid UTF-8.
    (home / ".env").write_bytes(b"OPENSQUILLA_ENV_TEST_BAD_KEY=caf\xe9\n")
    (tmp_path / ".env").write_text(
        "OPENSQUILLA_ENV_TEST_GOOD_KEY=ok\n", encoding="utf-8"
    )

    injected = env_mod.load_env(tmp_path)

    assert injected == 1
    assert os.environ["OPENSQUILLA_ENV_TEST_GOOD_KEY"] == "ok"
    assert "OPENSQUILLA_ENV_TEST_BAD_KEY" not in os.environ

    captured = capsys.readouterr()
    err = captured.err
    assert str(home / ".env") in err
    assert "UTF-8" in err
    assert err.count("\n") == 1, f"expected a single concise stderr line, got: {err!r}"
    # Machine-readable stdout must stay byte clean: the warning must never be
    # emitted through an unconfigured structlog PrintLogger on stdout.
    assert captured.out == "", f"env warning leaked to stdout: {captured.out!r}"

    # The CLI loads env twice (import time and app callback); the warning
    # must not repeat for the same file within one process.
    env_mod.load_env(tmp_path)
    repeat = capsys.readouterr()
    assert repeat.err == ""
    assert repeat.out == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are meaningless on Windows")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root bypasses file modes"
)
def test_load_env_survives_unreadable_home_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    _isolate_global_env(monkeypatch, home)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_BAD_KEY", raising=False)

    env_file = home / ".env"
    env_file.write_text("OPENSQUILLA_ENV_TEST_BAD_KEY=nope\n", encoding="utf-8")
    os.chmod(env_file, 0)
    try:
        injected = env_mod.load_env(tmp_path)
    finally:
        os.chmod(env_file, 0o600)

    assert injected == 0
    assert "OPENSQUILLA_ENV_TEST_BAD_KEY" not in os.environ
    captured = capsys.readouterr()
    assert str(env_file) in captured.err
    assert captured.out == "", f"env warning leaked to stdout: {captured.out!r}"


def test_load_env_valid_files_still_load_the_same_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    _isolate_global_env(monkeypatch, home)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_KEY", raising=False)
    monkeypatch.delenv("OPENSQUILLA_ENV_TEST_QUOTED", raising=False)

    (home / ".env").write_text(
        "# comment\n"
        "\n"
        "OPENSQUILLA_ENV_TEST_KEY=plain-value\n"
        "OPENSQUILLA_ENV_TEST_QUOTED='quoted value'\n"
        "not-an-assignment\n",
        encoding="utf-8",
    )

    assert env_mod.load_env(tmp_path) == 2
    assert os.environ["OPENSQUILLA_ENV_TEST_KEY"] == "plain-value"
    assert os.environ["OPENSQUILLA_ENV_TEST_QUOTED"] == "quoted value"
    assert capsys.readouterr().err == ""
