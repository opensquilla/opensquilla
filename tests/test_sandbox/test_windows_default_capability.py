from __future__ import annotations

from pathlib import Path


def test_capability_sid_is_stable_per_root(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_capability import (
        capability_sid_for_root,
        load_capability_store,
    )

    store_path = tmp_path / "cap_sids.json"
    generator = iter(
        [
            "S-1-5-21-100-101-102-103",
            "S-1-5-21-200-201-202-203",
        ]
    ).__next__

    first = capability_sid_for_root(store_path, tmp_path / "workspace", sid_factory=generator)
    second = capability_sid_for_root(store_path, tmp_path / "workspace", sid_factory=generator)
    loaded = load_capability_store(store_path)

    assert first == "S-1-5-21-100-101-102-103"
    assert second == first
    assert loaded.root_sids[str(tmp_path / "workspace")] == first


def test_command_capabilities_only_include_current_roots(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_capability import (
        capability_sid_for_root,
        capability_sids_for_command,
    )

    store_path = tmp_path / "cap_sids.json"
    generator = iter(
        [
            "S-1-5-21-100-101-102-103",
            "S-1-5-21-200-201-202-203",
        ]
    ).__next__
    workspace_sid = capability_sid_for_root(
        store_path,
        tmp_path / "workspace",
        sid_factory=generator,
    )
    other_sid = capability_sid_for_root(store_path, tmp_path / "other", sid_factory=generator)

    command_sids = capability_sids_for_command(store_path, (tmp_path / "workspace",))

    assert command_sids == (workspace_sid,)
    assert other_sid not in command_sids


def test_generated_restricting_sid_uses_create_restricted_token_compatible_form(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_default_capability import capability_sid_for_root

    sid = capability_sid_for_root(tmp_path / "cap_sids.json", tmp_path / "workspace")

    assert sid.startswith("S-1-5-21-")
    assert len(sid.split("-")) == 8


def test_legacy_app_capability_sids_are_not_reused(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_capability import (
        capability_sid_for_root,
        load_capability_store,
    )

    store_path = tmp_path / "cap_sids.json"
    root = tmp_path / "workspace"
    root_key = str(root).replace("\\", "\\\\")
    store_path.write_text(
        f'{{"rootSids": {{"{root_key}": "S-1-15-3-100-101-102-103-104-105-106-107"}}}}',
        encoding="utf-8",
    )

    loaded = load_capability_store(store_path)
    sid = capability_sid_for_root(
        store_path,
        root,
        sid_factory=lambda: "S-1-5-21-200-201-202-203",
    )

    assert loaded.root_sids == {}
    assert sid == "S-1-5-21-200-201-202-203"
