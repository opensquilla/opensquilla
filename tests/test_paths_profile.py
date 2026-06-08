"""Tests for OpenSquilla multi-instance profile resolution in ``opensquilla.paths``."""

from __future__ import annotations

import pytest

from opensquilla.paths import (
    default_opensquilla_home,
    default_profile_name,
    default_profiles_root,
    is_valid_profile_name,
    profile_home,
    state_dir,
)

# Profile name regex: starts with [a-z0-9], then [a-z0-9_-], max 64 chars.
_VALID_NAMES = [
    "default",
    "agent-a",
    "agent_a",
    "a1",
    "0",
    "a" * 64,  # max length
    "abc-123_xyz",
]
_INVALID_NAMES = [
    "",  # empty
    "-leading-dash",  # must start with alnum
    "_leading-underscore",
    "UPPER",  # only lowercase
    "MixedCase",
    "with spaces",
    "with/slash",
    "with\\backslash",
    "with..dot",
    "a" * 65,  # too long
    "../escape",  # path traversal
    "name?q=1",  # query string
    "中文",  # non-ASCII
    "name!",
    "name.with.dot",
    "name'quote",
    'name"quote',
]


@pytest.mark.parametrize("name", _VALID_NAMES)
def test_is_valid_profile_name_accepts(name: str) -> None:
    assert is_valid_profile_name(name)


@pytest.mark.parametrize("name", _INVALID_NAMES)
def test_is_valid_profile_name_rejects(name: str) -> None:
    assert not is_valid_profile_name(name)


def test_default_profile_name_defaults_to_default(monkeypatch) -> None:
    monkeypatch.delenv("OPENSQUILLA_PROFILE", raising=False)
    assert default_profile_name() == "default"


def test_default_profile_name_trims_whitespace(monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "  agent-a  ")
    assert default_profile_name() == "agent-a"


def test_default_profile_name_empty_string_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "   ")
    assert default_profile_name() == "default"


def test_default_profiles_root_uses_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path / "profiles"))
    assert default_profiles_root() == tmp_path / "profiles"


def test_default_profiles_root_returns_default_when_unset(
    monkeypatch, tmp_path
) -> None:
    """After the maintainer review, the default profiles root is always
    materialised: ``$HOME/.opensquilla/profiles``. ``None`` is no longer
    a valid return value, which means multi-instance mode is the default
    on every host — ``opensquilla --profile <name> init`` works without
    any environment configuration.
    """
    monkeypatch.delenv("OPENSQUILLA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_profiles_root() == tmp_path / ".opensquilla" / "profiles"


def test_default_profiles_root_expands_tilde(monkeypatch, tmp_path) -> None:
    # `~` should resolve against $HOME so the same env var is portable across
    # shells (the CLI / .env may pass either a literal path or a tilde).
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENSQUILLA_HOME", "~/my-profiles")
    assert default_profiles_root() == tmp_path / "my-profiles"


def test_profile_home_validates_name(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path / "profiles"))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "agent-a")
    assert profile_home() == tmp_path / "profiles" / "agent-a"


def test_profile_home_rejects_path_traversal(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENSQUILLA_HOME", str(tmp_path / "profiles"))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "../escape")
    # is_valid_profile_name returns False, so profile_home() must NOT
    # silently construct a path that escapes the profiles root.
    with pytest.raises(ValueError, match="Invalid OpenSquilla profile name"):
        profile_home()


def test_default_opensquilla_home_state_dir_overrides_profile(
    monkeypatch, tmp_path
) -> None:
    """OPENSQUILLA_STATE_DIR bypasses profile mode (back-compat)."""
    state_path = tmp_path / "pinned"
    profile_root = tmp_path / "profiles"
    monkeypatch.setenv("OPENSQUILLA_STATE_DIR", str(state_path))
    monkeypatch.setenv("OPENSQUILLA_HOME", str(profile_root))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "agent-a")

    assert default_opensquilla_home() == state_path


def test_default_opensquilla_home_resolves_via_profile(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    profile_root = tmp_path / "profiles"
    monkeypatch.setenv("OPENSQUILLA_HOME", str(profile_root))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "agent-b")

    assert default_opensquilla_home() == profile_root / "agent-b"


def test_default_opensquilla_home_uses_profiles_default_when_unset(
    monkeypatch, tmp_path
) -> None:
    """No STATE_DIR, no HOME, no PROFILE → multi-instance default
    ``$HOME/.opensquilla/profiles/default``. The legacy
    ``$HOME/.opensquilla`` home is auto-migrated on first call, so
    an existing install transparently lands in the same place after
    the migration runs once.
    """
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.delenv("OPENSQUILLA_HOME", raising=False)
    monkeypatch.delenv("OPENSQUILLA_PROFILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    # On a fresh tmp_path with no legacy artifacts, the resolver
    # lands at the multi-instance default — no migration needed.
    assert default_opensquilla_home() == tmp_path / ".opensquilla" / "profiles" / "default"


def test_state_dir_under_profile_isolated_between_profiles(
    monkeypatch, tmp_path
) -> None:
    """Two profiles must not share state/logs even when run from the same cwd."""
    profile_root = tmp_path / "profiles"
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(profile_root))

    monkeypatch.setenv("OPENSQUILLA_PROFILE", "agent-a")
    state_a = state_dir("agents", "main", "memory.db")
    assert state_a == profile_root / "agent-a" / "state" / "agents" / "main" / "memory.db"

    monkeypatch.setenv("OPENSQUILLA_PROFILE", "agent-b")
    state_b = state_dir("agents", "main", "memory.db")
    assert state_b == profile_root / "agent-b" / "state" / "agents" / "main" / "memory.db"

    assert state_a != state_b


def test_profile_siblings_share_profiles_root(
    monkeypatch, tmp_path
) -> None:
    """`default` and any new profile (e.g. `coder`) must live side-by-side
    under the same profiles root — `.../profiles/coder/` is a sibling of
    `.../profiles/default/`, not a child of it. pathlib `/` does the join
    portably on Windows, macOS, and Linux.
    """
    profile_root = tmp_path / "profiles"
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(profile_root))

    monkeypatch.setenv("OPENSQUILLA_PROFILE", "default")
    default_home = default_opensquilla_home()
    assert default_home == profile_root / "default"

    monkeypatch.setenv("OPENSQUILLA_PROFILE", "coder")
    coder_home = default_opensquilla_home()
    assert coder_home == profile_root / "coder"

    # Siblings: same parent, different leaf. Confirms coder is NOT nested
    # under default (which would be the bug if anyone tried to be cute with
    # the path resolution).
    assert default_home.parent == coder_home.parent == profile_root
    assert default_home != coder_home


def test_profile_home_uses_forward_slashes_in_posix_paths(
    monkeypatch, tmp_path
) -> None:
    """On POSIX hosts, the resolved path must use forward slashes so shell
    tools and JSON paths stay portable. (Windows is allowed to use backslashes
    — pathlib emits whatever the host expects.)
    """
    import sys

    profile_root = tmp_path / "profiles"
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.setenv("OPENSQUILLA_HOME", str(profile_root))
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "coder")

    home = default_opensquilla_home()
    if sys.platform != "win32":
        assert "\\" not in str(home), f"POSIX path leaked backslashes: {home!s}"
    # Independent of platform, pathlib's join must produce *some* path
    # ending with the profile name.
    assert home.name == "coder"
    assert home.parent == profile_root


def test_default_profile_name_explicit_default_lands_under_profiles_root(
    monkeypatch, tmp_path
) -> None:
    """With multi-instance mode the default, ``OPENSQUILLA_PROFILE=default``
    and no ``OPENSQUILLA_HOME`` resolves to
    ``$HOME/.opensquilla/profiles/default``, not the legacy
    ``$HOME/.opensquilla``.
    """
    monkeypatch.delenv("OPENSQUILLA_STATE_DIR", raising=False)
    monkeypatch.delenv("OPENSQUILLA_HOME", raising=False)
    monkeypatch.setenv("OPENSQUILLA_PROFILE", "default")
    monkeypatch.setenv("HOME", str(tmp_path))

    home = default_opensquilla_home()
    assert home == tmp_path / ".opensquilla" / "profiles" / "default"
