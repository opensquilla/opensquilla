from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.backend.linux_paths import canonical_linux_mount
from opensquilla.sandbox.types import MountSpec


def test_canonical_linux_mount_rewrites_workspace_alias_to_host_path(
    tmp_path: Path,
) -> None:
    mount = MountSpec(
        host_path=tmp_path,
        sandbox_path=Path("/workspace"),
        mode="rw",
        required=True,
    )

    canonical = canonical_linux_mount(mount)

    assert canonical.host_path == tmp_path
    assert canonical.sandbox_path == tmp_path
    assert canonical.mode == "rw"
    assert canonical.required is True


def test_canonical_linux_mount_keeps_non_workspace_mount(tmp_path: Path) -> None:
    mount = MountSpec(
        host_path=tmp_path / "src",
        sandbox_path=tmp_path / "src",
        mode="ro",
        required=False,
    )

    assert canonical_linux_mount(mount) is mount
