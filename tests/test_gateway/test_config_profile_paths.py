from __future__ import annotations

from pathlib import Path

from opensquilla.gateway.config import GatewayConfig
from opensquilla.recovery import inspect_profile


def test_relative_profile_roots_are_config_relative_not_cwd_relative(
    monkeypatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    elsewhere = tmp_path / "runtime-cwd"
    profile.mkdir()
    elsewhere.mkdir()
    config = profile / "config.toml"
    config.write_text(
        'state_dir = "state"\nworkspace_dir = "workspace"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(elsewhere)

    loaded = GatewayConfig.load(config)

    assert loaded.state_dir == str(profile / "state")
    assert loaded.workspace_dir == str(profile / "workspace")


def test_relative_environment_profile_roots_use_the_same_config_base(
    monkeypatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    elsewhere = tmp_path / "runtime-cwd"
    profile.mkdir()
    elsewhere.mkdir()
    config = profile / "config.toml"
    config.write_text(
        'config_version = 1\nstate_dir = "toml-state"\nworkspace_dir = "toml-workspace"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_STATE_DIR", "external-state")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_WORKSPACE_DIR", "external-workspace")

    loaded = GatewayConfig.load(config)

    assert loaded.state_dir == str(profile / "external-state")
    assert loaded.workspace_dir == str(profile / "external-workspace")


def test_recovery_and_runtime_share_path_override_precedence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    toml_state = profile / "toml-state"
    toml_workspace = profile / "toml-workspace"
    env_state = profile / "env-state"
    env_workspace = profile / "env-workspace"
    for directory in (toml_state, toml_workspace, env_state, env_workspace):
        directory.mkdir()
    (env_workspace / "SOUL.md").write_text("synthetic\n", encoding="utf-8")
    config = profile / "config.toml"
    config.write_text(
        'state_dir = "toml-state"\nworkspace_dir = "toml-workspace"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_STATE_DIR", "env-state")
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_WORKSPACE_DIR", "env-workspace")

    loaded = GatewayConfig.load(config)
    inspected = inspect_profile(profile, profile_kind="desktop-primary")

    assert loaded.state_dir == str(env_state)
    assert loaded.workspace_dir == str(env_workspace)
    assert inspected.effective_workspace == env_workspace
    state = next(candidate for candidate in inspected.candidates if candidate.kind == "state")
    assert state.path == env_state


def test_legacy_workspace_environment_alias_matches_recovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    workspace = profile / "alias-workspace"
    state = profile / "state"
    workspace.mkdir(parents=True)
    state.mkdir()
    (workspace / "SOUL.md").write_text("synthetic\n", encoding="utf-8")
    config = profile / "config.toml"
    config.write_text('workspace_dir = "toml-workspace"\n', encoding="utf-8")
    monkeypatch.delenv("OPENSQUILLA_GATEWAY_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_WORKSPACE_DIR", "alias-workspace")

    loaded = GatewayConfig.load(config)
    inspected = inspect_profile(profile, profile_kind="desktop-primary")

    assert loaded.workspace_dir == str(workspace)
    assert inspected.effective_workspace == workspace
