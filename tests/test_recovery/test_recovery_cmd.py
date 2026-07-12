from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typer.main import get_command
from typer.testing import CliRunner

from opensquilla.cli.main import app as root_app
from opensquilla.cli.recovery_cmd import recovery_app


def _workspace(path: Path, marker: str) -> Path:
    path.mkdir(parents=True)
    (path / "SOUL.md").write_text(marker + "\n", encoding="utf-8")
    return path


def test_recovery_command_surface_is_registered_with_complete_offline_actions() -> None:
    root_command = get_command(root_app)
    recovery_command = get_command(recovery_app)

    assert "recovery" in root_command.commands
    assert set(recovery_command.commands) == {
        "inspect",
        "reconcile",
        "choose-workspace",
        "apply-settings",
        "recover-settings",
        "restore-profile",
        "recover-transaction",
    }


def test_recovery_subprocess_routes_before_cwd_or_profile_dotenv(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    home = tmp_path / "selected-home"
    workspace = _workspace(home / "workspace", "selected identity")
    (home / "state").mkdir(parents=True)
    (home / "config.toml").write_text(
        'state_dir = "state"\nworkspace_dir = "workspace"\n',
        encoding="utf-8",
    )
    (cwd / ".env").write_text(
        "OPENSQUILLA_RECOVERY_DOTENV_SENTINEL=loaded-from-cwd\n",
        encoding="utf-8",
    )
    (home / ".env").write_text(
        "OPENSQUILLA_RECOVERY_DOTENV_SENTINEL=loaded-from-profile\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("OPENSQUILLA_RECOVERY_OFFLINE", None)
    environment.pop("OPENSQUILLA_RECOVERY_DOTENV_SENTINEL", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys\n"
                "sys.argv = ['opensquilla', *sys.argv[1:]]\n"
                "from opensquilla.cli.main import app\n"
                "assert 'OPENSQUILLA_RECOVERY_DOTENV_SENTINEL' not in os.environ\n"
                "app()\n"
            ),
            "recovery",
            "inspect",
            "--home",
            str(home),
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["primary_home"] == str(home)
    assert payload["effective_workspace"] == str(workspace)


def test_inspect_command_emits_fixed_json_protocol(tmp_path: Path) -> None:
    home = tmp_path / "opensquilla"
    workspace = _workspace(home / "workspace", "current identity")
    (home / "state").mkdir(parents=True)
    (home / "config.toml").write_text(
        'state_dir = "state"\nworkspace_dir = "workspace"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        recovery_app,
        ["inspect", "--home", str(home), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "schema_version",
        "outcome",
        "stable_code",
        "primary_home",
        "effective_workspace",
        "candidates",
        "allowed_actions",
        "transaction_id",
        "revision",
    }
    assert payload["outcome"] == "ready"
    assert payload["effective_workspace"] == str(workspace)
