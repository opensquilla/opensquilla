from __future__ import annotations

from pathlib import Path


def test_capability_sid_is_stable_per_root(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_capability import (
        capability_sid_for_root,
        load_capability_store,
    )

    store_path = tmp_path / "cap_sids.json"
    generator = iter(["S-1-15-3-100", "S-1-15-3-200"]).__next__

    first = capability_sid_for_root(store_path, tmp_path / "workspace", sid_factory=generator)
    second = capability_sid_for_root(store_path, tmp_path / "workspace", sid_factory=generator)
    loaded = load_capability_store(store_path)

    assert first == "S-1-15-3-100"
    assert second == first
    assert loaded.root_sids[str(tmp_path / "workspace")] == first


def test_command_capabilities_only_include_current_roots(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_capability import (
        capability_sid_for_root,
        capability_sids_for_command,
    )

    store_path = tmp_path / "cap_sids.json"
    generator = iter(["S-1-15-3-100", "S-1-15-3-200"]).__next__
    workspace_sid = capability_sid_for_root(
        store_path,
        tmp_path / "workspace",
        sid_factory=generator,
    )
    other_sid = capability_sid_for_root(store_path, tmp_path / "other", sid_factory=generator)

    command_sids = capability_sids_for_command(store_path, (tmp_path / "workspace",))

    assert command_sids == (workspace_sid,)
    assert other_sid not in command_sids
