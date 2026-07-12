"""Secret ``.env`` files written by migrators must be owner-only from birth.

Both the Hermes and OpenClaw migrators can land provider keys and channel
tokens in ``~/.opensquilla/.env`` when ``migrate_secrets=True``. These tests
pin the secure-write contract:

- the resulting file is mode 0600 (POSIX; mode bits are meaningless on
  Windows, matching the ``persist_config`` test idiom),
- the write is atomic (no leftover temp files),
- a failed write surfaces as an error instead of being silently swallowed.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from opensquilla.migration.hermes import HermesMigrationOptions, HermesMigrator
from opensquilla.migration.openclaw import MigrationOptions, OpenClawMigrator


@pytest.fixture()
def permissive_umask() -> Iterator[None]:
    """Force a typical 022 umask so a missing-chmod bug is deterministic."""
    if os.name == "nt":
        yield
        return
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def _assert_owner_only(path: Path) -> None:
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if os.name == "nt":
        assert mode & stat.S_IWRITE
    else:
        assert mode == 0o600


def _assert_no_leftover_tmp(directory: Path) -> None:
    leftovers = [p.name for p in directory.iterdir() if p.name.startswith(".env.")]
    assert leftovers == [], f"leftover temp files with secret content: {leftovers}"


def _make_hermes_source(root: Path) -> Path:
    source = root / ".hermes"
    source.mkdir(parents=True)
    (source / "config.yaml").write_text("", encoding="utf-8")
    (source / ".env").write_text("OPENAI_API_KEY=sk-dummy-hermes\n", encoding="utf-8")
    return source


def _make_openclaw_source(root: Path) -> Path:
    source = root / ".openclaw"
    source.mkdir(parents=True)
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {}}}), encoding="utf-8"
    )
    (source / ".env").write_text("OPENAI_API_KEY=sk-dummy-openclaw\n", encoding="utf-8")
    return source


def test_hermes_secret_env_written_with_owner_only_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permissive_umask: None
) -> None:
    source = _make_hermes_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)

    HermesMigrator(
        HermesMigrationOptions(
            source=source,
            config_path=tmp_path / "config.toml",
            apply=True,
            migrate_secrets=True,
        )
    ).migrate()

    env_path = home / ".env"
    assert "OPENAI_API_KEY=sk-dummy-hermes" in env_path.read_text(encoding="utf-8")
    _assert_owner_only(env_path)
    _assert_no_leftover_tmp(home)


def test_hermes_secret_merge_tightens_preexisting_env_perms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permissive_umask: None
) -> None:
    source = _make_hermes_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    home.mkdir()
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)
    env_path = home / ".env"
    env_path.write_text("EXISTING_KEY=keep-me\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(env_path, 0o644)

    HermesMigrator(
        HermesMigrationOptions(
            source=source,
            config_path=tmp_path / "config.toml",
            apply=True,
            migrate_secrets=True,
        )
    ).migrate()

    content = env_path.read_text(encoding="utf-8")
    assert "EXISTING_KEY=keep-me" in content
    assert "OPENAI_API_KEY=sk-dummy-hermes" in content
    _assert_owner_only(env_path)
    _assert_no_leftover_tmp(home)


def test_openclaw_secret_env_written_with_owner_only_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permissive_umask: None
) -> None:
    source = _make_openclaw_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)

    OpenClawMigrator(
        MigrationOptions(
            source=source,
            config_path=tmp_path / "config.toml",
            apply=True,
            migrate_secrets=True,
        )
    ).migrate()

    env_path = home / ".env"
    assert "OPENAI_API_KEY=sk-dummy-openclaw" in env_path.read_text(encoding="utf-8")
    _assert_owner_only(env_path)
    _assert_no_leftover_tmp(home)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are meaningless on Windows")
def test_openclaw_secret_env_secure_even_when_chmod_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permissive_umask: None
) -> None:
    # A post-hoc ``chmod`` used to be the only thing standing between the
    # secret file and umask-default permissions, and its failure was silently
    # swallowed. The file must now be owner-only from birth without relying
    # on chmod at all.
    source = _make_openclaw_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)

    real_chmod = os.chmod

    def chmod_denied_for_env(path: object, mode: int, *args: object, **kwargs: object) -> None:
        if str(path).endswith(".env"):
            raise OSError(1, "Operation not permitted")
        real_chmod(path, mode, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "chmod", chmod_denied_for_env)

    OpenClawMigrator(
        MigrationOptions(
            source=source,
            config_path=tmp_path / "config.toml",
            apply=True,
            migrate_secrets=True,
        )
    ).migrate()

    env_path = home / ".env"
    assert "OPENAI_API_KEY=sk-dummy-openclaw" in env_path.read_text(encoding="utf-8")
    _assert_owner_only(env_path)


def test_openclaw_secret_env_write_failure_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failure to land the secret file must propagate instead of being
    # silently swallowed, and no temp file holding the secret may remain.
    source = _make_openclaw_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)

    real_replace = os.replace

    def replace_denied_for_env(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if str(dst).endswith(".env"):
            raise OSError(13, "Permission denied")
        real_replace(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", replace_denied_for_env)

    with pytest.raises(OSError):
        OpenClawMigrator(
            MigrationOptions(
                source=source,
                config_path=tmp_path / "config.toml",
                apply=True,
                migrate_secrets=True,
            )
        ).migrate()

    assert not (home / ".env").exists()
    secret_holders = [
        path
        for path in home.rglob("*")
        if path.is_file() and "sk-dummy-openclaw" in path.read_text(errors="replace")
    ]
    assert secret_holders == [], f"secret leaked into: {secret_holders}"


def test_openclaw_secret_env_write_failure_rolls_back_other_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_openclaw_source(tmp_path)
    source_workspace = source / "workspace"
    source_workspace.mkdir()
    (source_workspace / "SOUL.md").write_text("openclaw soul\n", encoding="utf-8")
    source_skill = source_workspace / "skills" / "demo"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\n",
        encoding="utf-8",
    )
    source_tts = source_workspace / "tts"
    source_tts.mkdir()
    (source_tts / "voice.txt").write_text("voice\n", encoding="utf-8")
    (source / "openclaw.json").write_text(
        json.dumps({"agents": {"defaults": {"model": "deepseek-chat"}}}),
        encoding="utf-8",
    )

    home = tmp_path / "opensquilla-home"
    home.mkdir()
    workspace = tmp_path / "external-workspace"
    workspace.mkdir(parents=True)
    soul_path = workspace / "SOUL.md"
    soul_path.write_text("existing soul\n", encoding="utf-8")
    env_path = home / ".env"
    env_path.write_text("EXISTING_KEY=keep-me\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    original_config = (
        f"workspace_dir = {json.dumps(str(workspace))}\n"
        '\n[llm]\nprovider = "openai"\nmodel = "gpt-4o-mini"\n'
    )
    config_path.write_text(original_config, encoding="utf-8")

    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)
    real_replace = os.replace

    def replace_denied_for_env(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if str(dst).endswith(".env"):
            raise OSError(13, "Permission denied")
        real_replace(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", replace_denied_for_env)

    with pytest.raises(OSError):
        OpenClawMigrator(
            MigrationOptions(
                source=source,
                config_path=config_path,
                apply=True,
                migrate_secrets=True,
                overwrite=True,
            )
        ).migrate()

    assert soul_path.read_text(encoding="utf-8") == "existing soul\n"
    assert env_path.read_text(encoding="utf-8") == "EXISTING_KEY=keep-me\n"
    assert config_path.read_text(encoding="utf-8") == original_config
    assert list(workspace.glob("SOUL.md.backup.*")) == []
    assert list(tmp_path.glob("config.toml.backup.*")) == []
    assert not (home / "migration").exists()
    assert not (home / "skills").exists()
    assert not (home / "tts").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated Windows access")
def test_openclaw_late_failure_restores_secret_env_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_openclaw_source(tmp_path)
    source_workspace = source / "workspace"
    source_workspace.mkdir()
    (source_workspace / "SOUL.md").write_text("openclaw soul\n", encoding="utf-8")

    home = tmp_path / "opensquilla-home"
    home.mkdir()
    external_env = tmp_path / "shared.env"
    external_env.write_text("EXISTING_KEY=keep-me\n", encoding="utf-8")
    env_path = home / ".env"
    env_path.symlink_to(external_env)
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)

    def report_write_failed(_migrator: OpenClawMigrator) -> None:
        raise OSError(5, "report write failed")

    monkeypatch.setattr(OpenClawMigrator, "_write_report_files", report_write_failed)

    with pytest.raises(OSError, match="report write failed"):
        OpenClawMigrator(
            MigrationOptions(
                source=source,
                config_path=tmp_path / "config.toml",
                apply=True,
                migrate_secrets=True,
            )
        ).migrate()

    assert env_path.is_symlink()
    assert env_path.resolve() == external_env
    assert external_env.read_text(encoding="utf-8") == "EXISTING_KEY=keep-me\n"
    assert not (home / "workspace").exists()


def test_hermes_secret_env_write_failure_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_hermes_source(tmp_path)
    home = tmp_path / "opensquilla-home"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(home))
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", raising=False)

    real_replace = os.replace

    def replace_denied_for_env(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if str(dst).endswith(".env"):
            raise OSError(13, "Permission denied")
        real_replace(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", replace_denied_for_env)

    with pytest.raises(OSError):
        HermesMigrator(
            HermesMigrationOptions(
                source=source,
                config_path=tmp_path / "config.toml",
                apply=True,
                migrate_secrets=True,
            )
        ).migrate()

    assert not (home / ".env").exists()
    secret_holders = [
        path
        for path in home.rglob("*")
        if path.is_file() and "sk-dummy-hermes" in path.read_text(errors="replace")
    ]
    assert secret_holders == [], f"secret leaked into: {secret_holders}"
