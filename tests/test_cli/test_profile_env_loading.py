"""Regression tests for CLI profile resolution before home .env loading."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import app
from opensquilla.paths import default_opensquilla_home

runner = CliRunner()


def _write_profile(home: Path, name: str, env_lines: list[str]) -> Path:
    profile_dir = home / name
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    return profile_dir


def test_cli_profile_loads_selected_profile_env(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "profiles"
    _write_profile(home, "default", ["PROFILE_MARK=loaded-default"])
    _write_profile(home, "coder", ["CODER_MARK=loaded-coder"])

    for key in (
        "OPENSQUILLA_HOME",
        "OPENSQUILLA_PROFILE",
        "OPENSQUILLA_STATE_DIR",
        "PROFILE_MARK",
        "CODER_MARK",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(home))

    result = runner.invoke(app, ["--profile", "coder", "providers", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert os.environ["OPENSQUILLA_PROFILE"] == "coder"
    assert os.environ["CODER_MARK"] == "loaded-coder"
    assert "PROFILE_MARK" not in os.environ
    assert default_opensquilla_home() == home / "coder"


def test_cli_without_profile_keeps_legacy_home(monkeypatch, tmp_path: Path) -> None:
    legacy_home = tmp_path / ".opensquilla"
    legacy_home.mkdir()
    (legacy_home / ".env").write_text("LEGACY_MARK=loaded\n", encoding="utf-8")

    for key in (
        "OPENSQUILLA_HOME",
        "OPENSQUILLA_PROFILE",
        "OPENSQUILLA_STATE_DIR",
        "LEGACY_MARK",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = runner.invoke(app, ["providers", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert os.environ["LEGACY_MARK"] == "loaded"
    assert default_opensquilla_home() == legacy_home


def test_cli_does_not_reload_same_home_env_after_key_removed(
    monkeypatch, tmp_path: Path
) -> None:
    legacy_home = tmp_path / ".opensquilla"
    legacy_home.mkdir()
    (legacy_home / ".env").write_text("RELOAD_MARK=loaded\n", encoding="utf-8")

    for key in (
        "OPENSQUILLA_HOME",
        "OPENSQUILLA_PROFILE",
        "OPENSQUILLA_STATE_DIR",
        "RELOAD_MARK",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = runner.invoke(app, ["providers", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert os.environ["RELOAD_MARK"] == "loaded"

    monkeypatch.delenv("RELOAD_MARK", raising=False)

    result = runner.invoke(app, ["providers", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert "RELOAD_MARK" not in os.environ


def test_cli_rejects_invalid_profile(monkeypatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)

    result = runner.invoke(app, ["--profile", "../escape", "providers", "list"])

    assert result.exit_code != 0
    assert "lowercase letters" in result.output


def test_env_load_uses_provided_home(monkeypatch, tmp_path: Path) -> None:
    from opensquilla.env import load_env

    home = tmp_path / "custom"
    home.mkdir(parents=True)
    (home / ".env").write_text("CUSTOM_MARK=ok\n", encoding="utf-8")

    for key in (
        "OPENSQUILLA_HOME",
        "OPENSQUILLA_PROFILE",
        "OPENSQUILLA_STATE_DIR",
        "CUSTOM_MARK",
    ):
        monkeypatch.delenv(key, raising=False)

    assert load_env(home=home) >= 1
    assert os.environ["CUSTOM_MARK"] == "ok"


def test_cli_profile_env_wins_over_legacy_home_for_same_key(
    monkeypatch, tmp_path: Path
) -> None:
    legacy_home = tmp_path / ".opensquilla"
    profiles_root = legacy_home / "profiles"
    legacy_home.mkdir()
    (legacy_home / ".env").write_text("PROFILE_SHARED_MARK=legacy\n", encoding="utf-8")
    _write_profile(profiles_root, "coder", ["PROFILE_SHARED_MARK=coder"])

    for key in (
        "OPENSQUILLA_HOME",
        "OPENSQUILLA_PROFILE",
        "OPENSQUILLA_STATE_DIR",
        "PROFILE_SHARED_MARK",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    result = runner.invoke(app, ["--profile", "coder", "providers", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert os.environ["PROFILE_SHARED_MARK"] == "coder"
    assert default_opensquilla_home() == profiles_root / "coder"


def test_cli_profile_env_wins_on_cold_start_import(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    legacy_home = tmp_path / ".opensquilla"
    profiles_root = legacy_home / "profiles"
    legacy_home.mkdir()
    (legacy_home / ".env").write_text("PROFILE_SHARED_MARK=legacy\n", encoding="utf-8")
    _write_profile(profiles_root, "coder", ["PROFILE_SHARED_MARK=coder"])

    env = os.environ.copy()
    env.update({"HOME": str(tmp_path)})
    env.pop("OPENSQUILLA_HOME", None)
    env.pop("OPENSQUILLA_PROFILE", None)
    env.pop("OPENSQUILLA_STATE_DIR", None)
    env.pop("PROFILE_SHARED_MARK", None)
    pythonpath = [
        str(repo_root / "src"),
        str(repo_root),
        env.get("PYTHONPATH", ""),
    ]
    env["PYTHONPATH"] = os.pathsep.join(path for path in pythonpath if path)

    script = """
import os
import sys
from typer.testing import CliRunner

sys.argv = ["opensquilla", "--profile", "coder", "providers", "list", "--json"]
from opensquilla.cli.main import app

cold_start_mark = os.environ.get("PROFILE_SHARED_MARK", "")
if cold_start_mark != "coder":
    print(cold_start_mark)
    raise SystemExit(2)

result = CliRunner().invoke(app, ["--profile", "coder", "providers", "list", "--json"])
if result.exit_code != 0:
    print(result.output)
    raise SystemExit(result.exit_code)

print(os.environ.get("PROFILE_SHARED_MARK", ""))
raise SystemExit(0 if os.environ.get("PROFILE_SHARED_MARK") == "coder" else 2)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_profile_from_cwd_env_wins_over_legacy_home_on_cold_start(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text("OPENSQUILLA_PROFILE=coder\n", encoding="utf-8")
    legacy_home = tmp_path / ".opensquilla"
    profiles_root = legacy_home / "profiles"
    legacy_home.mkdir()
    (legacy_home / ".env").write_text("PROFILE_SHARED_MARK=legacy\n", encoding="utf-8")
    _write_profile(profiles_root, "coder", ["PROFILE_SHARED_MARK=coder"])

    env = os.environ.copy()
    env.update({"HOME": str(tmp_path)})
    env.pop("OPENSQUILLA_HOME", None)
    env.pop("OPENSQUILLA_PROFILE", None)
    env.pop("OPENSQUILLA_STATE_DIR", None)
    env.pop("PROFILE_SHARED_MARK", None)
    pythonpath = [
        str(repo_root / "src"),
        str(repo_root),
        env.get("PYTHONPATH", ""),
    ]
    env["PYTHONPATH"] = os.pathsep.join(path for path in pythonpath if path)

    script = """
import os
from opensquilla.paths import default_opensquilla_home

from opensquilla.cli.main import app

if os.environ.get("PROFILE_SHARED_MARK") != "coder":
    print(os.environ.get("PROFILE_SHARED_MARK", ""))
    raise SystemExit(2)
if default_opensquilla_home().name != "coder":
    print(default_opensquilla_home())
    raise SystemExit(3)
raise SystemExit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
