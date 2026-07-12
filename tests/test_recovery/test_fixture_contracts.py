from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).with_name("fixtures")
DESKTOP_MANIFEST = FIXTURE_ROOT / "desktop" / "released-profiles.json"
PORTABLE_MANIFEST = FIXTURE_ROOT / "portable" / "released-profiles.json"
DESKTOP_SNAPSHOTS = FIXTURE_ROOT / "desktop" / "frozen-profile-snapshots.json"


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return payload


def test_released_desktop_manifest_freezes_verified_path_contract() -> None:
    manifest = _load_manifest(DESKTOP_MANIFEST)
    cases = manifest["cases"]
    tags = {case["release_tag"] for case in cases}

    assert tags == {"v0.4.0", "v0.4.1", "v0.5.0rc1", "v0.5.0rc2", "v0.5.0rc3"}
    assert all(
        case["gateway_env_home"] == "H/state"
        for case in cases
        if case["release_tag"] != "v0.5.0rc3"
    )
    assert all(
        case["gateway_env_home"] == "H"
        for case in cases
        if case["release_tag"] == "v0.5.0rc3"
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


def test_released_desktop_cases_use_tag_proven_frozen_tree_snapshots() -> None:
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
