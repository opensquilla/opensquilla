from __future__ import annotations

from pathlib import Path

from opensquilla.paths import media_root_from_config


class _Config:
    attachments = None
    state_dir = None
    config_path = None


def test_default_media_root_uses_opensquilla_home_not_cwd(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home" / ".opensquilla"
    long_cwd = tmp_path / ("nested-" + "x" * 24) / ("worktree-" + "y" * 24)
    long_cwd.mkdir(parents=True)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.chdir(long_cwd)

    assert media_root_from_config(_Config()) == home / "media"


def test_default_media_root_prefers_config_state_root(tmp_path: Path) -> None:
    class Config:
        attachments = None
        state_dir = str(tmp_path / "runtime-home" / "state")
        config_path = None

    assert media_root_from_config(Config()) == tmp_path / "runtime-home" / "media"


def test_explicit_media_root_is_preserved(tmp_path: Path) -> None:
    class Attachments:
        media_root = str(tmp_path / "custom-media")

    class Config:
        attachments = Attachments()
        state_dir = str(tmp_path / "runtime-home" / "state")
        config_path = None

    assert media_root_from_config(Config()) == tmp_path / "custom-media"
