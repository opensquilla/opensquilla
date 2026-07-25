from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).with_name("fixtures")
DESKTOP_MANIFEST = FIXTURE_ROOT / "desktop" / "released-profiles.json"
PORTABLE_MANIFEST = FIXTURE_ROOT / "portable" / "released-profiles.json"
DESKTOP_SNAPSHOTS = FIXTURE_ROOT / "desktop" / "frozen-profile-snapshots.json"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return payload


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        if os.environ.get("OPENSQUILLA_REQUIRE_RELEASE_TAG_PROVENANCE") == "1":
            pytest.fail("git is required for release-tag provenance verification")
        pytest.skip("git is unavailable; release-tag provenance is enforced by release CI")
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _require_release_tags(tags: set[str]) -> None:
    required = os.environ.get("OPENSQUILLA_REQUIRE_RELEASE_TAG_PROVENANCE") == "1"
    try:
        assert _git_output("rev-parse", "--is-inside-work-tree") == "true"
    except (AssertionError, pytest.skip.Exception):
        if required:
            pytest.fail("release-tag provenance requires a Git worktree")
        pytest.skip("Git metadata is unavailable; release-tag provenance is enforced by release CI")

    missing = []
    for tag in sorted(tags):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            missing.append(tag)
    if missing:
        detail = f"release tags are unavailable: {', '.join(missing)}"
        if required:
            pytest.fail(detail)
        pytest.skip(f"{detail}; expected in a shallow/offline checkout")


def test_released_desktop_manifest_freezes_verified_path_contract() -> None:
    manifest = _load_manifest(DESKTOP_MANIFEST)
    cases = manifest["cases"]
    tags = {case["release_tag"] for case in cases}

    assert tags == {
        "v0.4.0",
        "v0.4.1",
        "v0.5.0rc1",
        "v0.5.0rc2",
        "v0.5.0rc3",
        "v0.5.0rc4",
        "v0.5.0",
    }
    assert all(
        case["gateway_env_home"] == "H/state"
        for case in cases
        if case["release_tag"] in {"v0.4.0", "v0.4.1", "v0.5.0rc1", "v0.5.0rc2"}
    )
    assert all(
        case["gateway_env_home"] == "H"
        for case in cases
        if case["release_tag"] in {"v0.5.0rc3", "v0.5.0rc4", "v0.5.0"}
    )
    assert manifest["provenance"]["rc3_relocation_allowlist"] == [
        "skills",
        "skills-taps.json",
        "skills-lock.json",
        "workspace",
        "session-archive",
        "router",
        ".env",
        "state/*",
    ]


def test_released_desktop_cases_reference_frozen_tree_snapshots() -> None:
    manifest = _load_manifest(DESKTOP_MANIFEST)
    snapshots = _load_manifest(DESKTOP_SNAPSHOTS)
    by_id = {snapshot["id"]: snapshot for snapshot in snapshots["snapshots"]}

    assert set(by_id) == {case["id"] for case in manifest["cases"]}
    for case in manifest["cases"]:
        snapshot = by_id[case["id"]]
        source = snapshot["source"]
        assert snapshot["release_tag"] == case["release_tag"]
        assert re.fullmatch(r"[0-9a-f]{40}", source["release_commit"])
        assert re.fullmatch(r"[0-9a-f]{40}", source["desktop_main_blob"])
        assert re.fullmatch(r"[0-9a-f]{40}", source["python_paths_blob"])
        assert source["desktop_main_path"] == "desktop/electron/src/main.ts"
        assert source["python_paths_path"] == "src/opensquilla/paths.py"
        assert source["gateway_env_home"] == case["gateway_env_home"]

        seen: set[str] = set()
        for entry in snapshot["tree"]:
            relative = Path(entry["path"])
            assert not relative.is_absolute()
            assert ".." not in relative.parts
            assert entry["path"] not in seen
            seen.add(entry["path"])
            if entry["kind"] == "config":
                template = DESKTOP_SNAPSHOTS.parent / entry["template"]
                assert template.is_file()

        entries = {entry["path"]: entry for entry in snapshot["tree"]}
        assert entries["config.toml"]["kind"] == "config"
        assert entries["state/sessions.db"]["kind"] == "sqlite_sessions"
        assert entries["media/synthetic.txt"]["kind"] == "text"
        assert any(
            path.endswith("/USER.md") and entry["kind"] == "identity_markdown"
            for path, entry in entries.items()
        )


def test_released_desktop_snapshot_git_objects_match_release_tags() -> None:
    snapshots = _load_manifest(DESKTOP_SNAPSHOTS)["snapshots"]
    _require_release_tags({snapshot["release_tag"] for snapshot in snapshots})

    for snapshot in snapshots:
        tag = snapshot["release_tag"]
        source = snapshot["source"]
        assert _git_output("rev-parse", "--verify", f"{tag}^{{commit}}") == source[
            "release_commit"
        ]
        for path_field, blob_field in (
            ("desktop_main_path", "desktop_main_blob"),
            ("python_paths_path", "python_paths_blob"),
        ):
            actual_blob = _git_output("rev-parse", f"{tag}:{source[path_field]}")
            assert actual_blob == source[blob_field], (
                f"{tag}:{source[path_field]} is {actual_blob}, "
                f"fixture records {source[blob_field]}"
            )
            assert _git_output("cat-file", "-t", actual_blob) == "blob"


def test_published_portable_cases_pin_the_released_builder_blob() -> None:
    releases = _load_manifest(PORTABLE_MANIFEST)["published_releases"]
    for release in releases:
        source = release["source"]
        assert re.fullmatch(r"[0-9a-f]{40}", source["release_commit"])
        assert re.fullmatch(r"[0-9a-f]{40}", source["builder_blob"])
        assert re.fullmatch(r"[0-9a-f]{40}", source["config_blob"])
        assert re.fullmatch(r"[0-9a-f]{40}", source["latest_migration_blob"])
        assert source["builder_path"] == "scripts/build_wheelhouse_zip.py"
        assert source["config_path"] == "src/opensquilla/gateway/config.py"
        assert source["latest_migration_path"].startswith("migrations/V")
        assert source["latest_migration_path"].endswith(".py")
        assert source["latest_migration_id"] == Path(source["latest_migration_path"]).stem
        assert source["opensquilla_state_dir"] == "<portable-home>"
        assert source["gateway_state_dir"] == "<portable-home>/state"
        assert source["gateway_workspace_dir"] == "<portable-home>/workspace"
