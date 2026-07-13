from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from opensquilla.cli.main import _is_offline_import_verification
from opensquilla.cli.migrate_cmd import migrate_app

EXPECTED_FIELDS = {
    "schema_version",
    "outcome",
    "stable_code",
    "source",
    "source_kind",
    "target",
    "transaction_id",
    "matching_transaction_ids",
    "provider_connection",
    "report",
}


def test_offline_verifier_detection_only_matches_the_real_command_position() -> None:
    assert _is_offline_import_verification(
        ["opensquilla", "--profile", "desktop", "migrate", "verify-opensquilla-import"]
    )
    assert not _is_offline_import_verification(
        ["opensquilla", "doctor", "migrate", "verify-opensquilla-import"]
    )


def test_internal_import_verifier_emits_stable_redacted_json(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        migrate_app,
        [
            "verify-opensquilla-import",
            "--source",
            str(tmp_path / "source"),
            "--target",
            str(tmp_path / "target"),
            "--source-kind",
            "invalid-kind",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == EXPECTED_FIELDS
    assert payload["outcome"] == "invalid"
    assert payload["stable_code"] == "profile_import_source_kind_invalid"
    assert payload["matching_transaction_ids"] == []
    assert payload["provider_connection"] is None
    assert payload["report"] is None


def test_internal_import_verifier_routes_before_dotenv_bootstrap(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text(
        "OPENSQUILLA_IMPORT_VERIFY_DOTENV_SENTINEL=must-not-load\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("OPENSQUILLA_RECOVERY_OFFLINE", None)
    environment.pop("OPENSQUILLA_IMPORT_VERIFY_DOTENV_SENTINEL", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys\n"
                "sys.argv = ['opensquilla', *sys.argv[1:]]\n"
                "from opensquilla.cli.main import app\n"
                "assert 'OPENSQUILLA_IMPORT_VERIFY_DOTENV_SENTINEL' not in os.environ\n"
                "app()\n"
            ),
            "migrate",
            "verify-opensquilla-import",
            "--source",
            str(tmp_path / "source"),
            "--target",
            str(tmp_path / "target"),
            "--source-kind",
            "invalid-kind",
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert set(json.loads(completed.stdout)) == EXPECTED_FIELDS
