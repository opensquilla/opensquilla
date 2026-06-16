from __future__ import annotations

from pathlib import Path


def test_cache_dirs_cover_common_language_tools(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_cache import planned_cache_dirs

    dirs = planned_cache_dirs(tmp_path)

    names = {path.relative_to(tmp_path / ".opensquilla-cache").parts[0] for path in dirs}
    assert {
        "temp",
        "home",
        "git",
        "pip",
        "uv",
        "npm",
        "pnpm",
        "yarn",
        "cargo",
        "rustup",
        "go",
        "maven",
        "gradle",
        "nuget",
        "dotnet",
        "composer",
        "ruby",
    } <= names


def test_cache_env_points_to_workspace_cache(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_cache import build_cache_env

    env = build_cache_env(tmp_path, base_env={})

    root = tmp_path / ".opensquilla-cache"
    assert env["TEMP"] == str(root / "temp")
    assert env["TMP"] == str(root / "temp")
    assert env["HOME"] == str(root / "home")
    assert env["USERPROFILE"] == str(root / "home")
    assert env["XDG_CONFIG_HOME"] == str(root / "home" / ".config")
    assert env["GIT_CONFIG_GLOBAL"] == str(root / "git" / "config")
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["PIP_CACHE_DIR"] == str(root / "pip")
    assert env["UV_CACHE_DIR"] == str(root / "uv")
    assert env["npm_config_cache"] == str(root / "npm")
    assert env["PNPM_HOME"] == str(root / "pnpm" / "home")
    assert env["PNPM_STORE_DIR"] == str(root / "pnpm" / "store")
    assert env["YARN_CACHE_FOLDER"] == str(root / "yarn")
    assert env["CARGO_HOME"] == str(root / "cargo")
    assert env["RUSTUP_HOME"] == str(root / "rustup")
    assert env["GOMODCACHE"] == str(root / "go" / "pkg" / "mod")
    assert env["GOCACHE"] == str(root / "go" / "build")
    assert env["MAVEN_USER_HOME"] == str(root / "maven")
    assert env["GRADLE_USER_HOME"] == str(root / "gradle")
    assert env["NUGET_PACKAGES"] == str(root / "nuget")
    assert env["DOTNET_CLI_HOME"] == str(root / "dotnet")
    assert env["COMPOSER_CACHE_DIR"] == str(root / "composer")
    assert env["GEM_HOME"] == str(root / "ruby" / "gems")
    assert env["GEM_SPEC_CACHE"] == str(root / "ruby" / "specs")


def test_existing_user_cache_env_can_be_preserved(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_cache import build_cache_env

    external = r"C:\Users\me\.cache\pip"
    env = build_cache_env(
        tmp_path,
        base_env={"PIP_CACHE_DIR": external},
        override_user=False,
    )

    assert env["PIP_CACHE_DIR"] == external
    assert env["UV_CACHE_DIR"] == str(tmp_path / ".opensquilla-cache" / "uv")
