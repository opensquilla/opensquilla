from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

SHARD_SCRIPT = Path(".github/scripts/windows_test_shards.py")
SHARD_MODULE: dict[str, Any] = runpy.run_path(
    SHARD_SCRIPT.as_posix(), run_name="windows_test_shards"
)
SHARD_NAMES: tuple[str, ...] = SHARD_MODULE["SHARD_NAMES"]
discover_test_files = SHARD_MODULE["discover_test_files"]
files_for_shard = SHARD_MODULE["files_for_shard"]
matching_specialized_shards = SHARD_MODULE["matching_specialized_shards"]
shard_for_test = SHARD_MODULE["shard_for_test"]


def test_every_pytest_file_belongs_to_exactly_one_windows_shard() -> None:
    discovered = set(discover_test_files(Path.cwd()))
    by_shard = {
        shard: set(files_for_shard(Path.cwd(), shard)) for shard in SHARD_NAMES
    }

    assert set(SHARD_NAMES) == {
        "core",
        "gateway-sqlite",
        "recovery-migration",
        "desktop-installer-contracts",
    }
    assert all(by_shard.values())
    assert set().union(*by_shard.values()) == discovered
    assert sum(len(paths) for paths in by_shard.values()) == len(discovered)
    assert all(len(matching_specialized_shards(path)) <= 1 for path in discovered)
    assert "tests/fixtures/meta_skill_inputs/code_review_dirty_repo/tests/test_app.py" not in (
        discovered
    )


def test_windows_shard_responsibilities_cover_high_risk_surfaces() -> None:
    expected = {
        "tests/test_engine/test_agent_max_iterations.py": "core",
        "tests/test_ci/test_router_artifact_manifest.py": "core",
        "tests/test_gateway/test_task_runtime_terminal_cleanup.py": "gateway-sqlite",
        "tests/test_persistence/test_migrator.py": "gateway-sqlite",
        "tests/test_session/test_manager.py": "gateway-sqlite",
        "tests/test_migration/test_opensquilla_home_migration.py": "recovery-migration",
        "tests/test_recovery/test_fixture_contracts.py": "recovery-migration",
        "tests/test_cli/test_migrate_cmd.py": "recovery-migration",
        "tests/test_desktop/test_electron_startup_contract.py": (
            "desktop-installer-contracts"
        ),
        "tests/test_uninstall/test_safety.py": "desktop-installer-contracts",
        "tests/test_install_scripts.py": "desktop-installer-contracts",
    }

    assert {path: shard_for_test(path) for path in expected} == expected


def test_windows_shard_runner_preserves_failure_exit_and_summary(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nnorecursedirs = ["tests/fixtures"]\n',
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_failure.py").write_text(
        "def test_failure():\n    assert False, 'synthetic shard failure'\n",
        encoding="utf-8",
    )
    junit = tmp_path / "reports" / "junit.xml"
    summary = tmp_path / "reports" / "first-failure.txt"

    result = subprocess.run(
        [
            sys.executable,
            SHARD_SCRIPT.resolve().as_posix(),
            "run",
            "core",
            "--root",
            tmp_path.as_posix(),
            "--junit",
            junit.as_posix(),
            "--summary",
            summary.as_posix(),
            "--",
            "-q",
            "--maxfail=3",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert junit.is_file()
    text = summary.read_text(encoding="utf-8")
    assert "pytest_exit_code=1" in text
    assert "junit_status=failed" in text
    assert "synthetic shard failure" in text
