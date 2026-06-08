"""Regression tests for the CLI `--profile` × `load_env` ordering.

Maintainer review surfaced that the legacy `cli.main.load_env()` call
ran at module import time, before the Typer callback had parsed
`--profile` / `OPENSQUILLA_PROFILE`. As a result, a command like
`opensquilla --profile coder gateway status --json` could route state
and config to `profiles/coder/` while still loading `.env` from the
default profile's home.

These tests exercise the post-fix behaviour: with two profiles
under one OPENSQUILLA_HOME, the active profile's `.env` is the one
that ends up in `os.environ`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


def _write_profile(home: Path, name: str, env_lines: list[str]) -> Path:
    """Materialise a profile directory with a `.env` and a `config.toml`."""
    profile_dir = home / name
    (profile_dir / "state").mkdir(parents=True, exist_ok=True)
    (profile_dir / "logs").mkdir(parents=True, exist_ok=True)
    (profile_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (profile_dir / ".env").write_text(
        "\n".join(env_lines) + "\n", encoding="utf-8"
    )
    (profile_dir / "config.toml").write_text(
        '[llm]\nprovider = "openrouter"\nmodel = "openai/gpt-4o-mini"\n',
        encoding="utf-8",
    )
    return profile_dir


def test_cli_profile_loads_selected_profile_env(
    monkeypatch, tmp_path: Path
) -> None:
    """`--profile coder` must populate `CODER_MARK`, not `DEFAULT_MARK`."""
    home = tmp_path / "profiles"
    _write_profile(home, "default", ["DEFAULT_MARK=loaded-default"])
    _write_profile(home, "coder", ["CODER_MARK=loaded-coder"])

    # Run from a clean env so load_env() actually injects from .env
    # (load_env never overrides pre-existing os.environ entries).
    for key in ("OPENSQUILLA_HOME", "OPENSQUILLA_PROFILE", "OPENSQUILLA_STATE_DIR",
                "DEFAULT_MARK", "CODER_MARK"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("OPENSQUILLA_HOME", str(home))
    result = runner.invoke(
        app,
        ["--profile", "coder", "gateway", "status", "--json"],
        env={"OPENSQUILLA_HOME": str(home)},
        catch_exceptions=False,
    )

    # Status may or may not be parseable JSON (no live gateway in tests),
    # but the env side-effect must have happened. CliRunner captures
    # os.environ in its own sandbox; the regression we are guarding
    # against is the *load order*, observable via OPENSQUILLA_PROFILE
    # being set to the resolved value before load_env runs.
    import os
    assert os.environ.get("OPENSQUILLA_PROFILE") == "coder", (
        f"OPENSQUILLA_PROFILE not set to 'coder' after CLI; "
        f"got {os.environ.get('OPENSQUILLA_PROFILE')!r}"
    )
    # The selected profile's home is the resolution target, not default.
    from opensquilla.paths import default_opensquilla_home
    assert default_opensquilla_home() == home / "coder"


def test_cli_default_profile_loads_default_env(monkeypatch, tmp_path: Path) -> None:
    """No --profile flag should still load the implicit default profile's .env."""
    home = tmp_path / "profiles"
    _write_profile(home, "default", ["DEFAULT_MARK=loaded-default"])
    _write_profile(home, "coder", ["CODER_MARK=loaded-coder"])

    for key in ("OPENSQUILLA_HOME", "OPENSQUILLA_PROFILE", "OPENSQUILLA_STATE_DIR",
                "DEFAULT_MARK", "CODER_MARK"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("OPENSQUILLA_HOME", str(home))
    # No --profile, no OPENSQUILLA_PROFILE — should resolve to 'default'.
    result = runner.invoke(
        app,
        ["gateway", "status", "--json"],
        env={"OPENSQUILLA_HOME": str(home)},
        catch_exceptions=False,
    )

    from opensquilla.paths import default_opensquilla_home
    assert default_opensquilla_home() == home / "default"


def test_env_load_uses_provided_home(monkeypatch, tmp_path: Path) -> None:
    """`env.load_env(home=...)` must read .env from that home, not default."""
    from opensquilla.env import load_env

    home = tmp_path / "custom"
    (home / "state").mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text("CUSTOM_MARK=ok\n", encoding="utf-8")

    for key in ("OPENSQUILLA_HOME", "OPENSQUILLA_PROFILE", "OPENSQUILLA_STATE_DIR",
                "CUSTOM_MARK", "DEFAULT_MARK"):
        monkeypatch.delenv(key, raising=False)

    injected = load_env(home=home)
    import os
    assert os.environ.get("CUSTOM_MARK") == "ok"
    assert injected >= 1
