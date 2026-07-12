from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from typer.main import get_command
from typer.testing import CliRunner

from opensquilla.cli.main import app as root_app
from opensquilla.cli.recovery_cmd import recovery_app

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "opensquilla"


def _workspace(path: Path, marker: str) -> Path:
    path.mkdir(parents=True)
    (path / "SOUL.md").write_text(marker + "\n", encoding="utf-8")
    return path


def test_recovery_command_surface_is_deliberately_unregistered() -> None:
    root_command = get_command(root_app)
    recovery_command = get_command(recovery_app)

    assert "recovery" not in root_command.commands
    assert set(recovery_command.commands) == {
        "inspect",
        "reconcile",
        "choose-workspace",
    }


def test_importing_root_cli_does_not_import_recovery_runtime() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "import opensquilla.cli.main\n"
                "assert 'opensquilla.recovery' not in sys.modules\n"
                "assert 'opensquilla.cli.recovery_cmd' not in sys.modules\n"
            ),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_unregistered_inspect_command_emits_fixed_json_protocol(tmp_path: Path) -> None:
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


def test_only_unregistered_cli_adapter_imports_recovery() -> None:
    allowed = PACKAGE_ROOT / "cli" / "recovery_cmd.py"
    importers: list[Path] = []

    for source in PACKAGE_ROOT.rglob("*.py"):
        if source == allowed or source.is_relative_to(PACKAGE_ROOT / "recovery"):
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            else:
                continue
            if any(
                module == "opensquilla.recovery"
                or module.startswith("opensquilla.recovery.")
                for module in modules
            ):
                importers.append(source.relative_to(PACKAGE_ROOT))
                break

    assert importers == []
