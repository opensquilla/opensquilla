"""OpenSquilla state-root resolution.

Single source of truth for the on-disk state root. One env var controls
the root, and every subsystem derives its sub-path from the helper here.

Resolution precedence for the home directory:

1. ``OPENSQUILLA_STATE_DIR`` environment variable (expanded for ``~``/``$HOME``)
   — full override; bypasses profile resolution for back-compat with
   single-instance deployments and CI scripts that pin a specific path.
2. ``$OPENSQUILLA_HOME/$OPENSQUILLA_PROFILE`` — multi-instance mode.
   Set ``OPENSQUILLA_HOME`` to the parent directory (default
   ``$HOME/.opensquilla/profiles``) and ``OPENSQUILLA_PROFILE`` (default
   ``"default"``) to select one. Profile names must match
   ``^[a-z0-9][a-z0-9_-]{0,63}$`` to prevent path-traversal escapes.
3. ``$HOME/.opensquilla`` — single-instance default (no profile mode).

Multi-instance mode lets a single host run several OpenSquilla agents in
parallel, each with its own state/logs/config workspace, without sharing
locks, sockets, or state files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = [
    "default_opensquilla_home",
    "default_profile_name",
    "default_profiles_root",
    "is_valid_profile_name",
    "media_root_from_config",
    "profile_home",
    "state_dir",
]

_PROFILES_DIR_ENV = "OPENSQUILLA_HOME"
_PROFILE_ENV = "OPENSQUILLA_PROFILE"
_STATE_DIR_ENV = "OPENSQUILLA_STATE_DIR"
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DEFAULT_PROFILE_NAME = "default"


def _home_dir() -> Path:
    home = os.environ.get("HOME", "").strip()
    if home:
        return Path(home).expanduser()
    return Path.home()


def _expand_user(path: str) -> Path:
    if path == "~":
        return _home_dir()
    if path.startswith("~/") or path.startswith("~\\"):
        return _home_dir() / path[2:]
    return Path(path).expanduser()


def is_valid_profile_name(name: str) -> bool:
    """Return True iff ``name`` is safe to use as a profile directory name.

    The regex is intentionally restrictive (lowercase alnum + ``_``/``-``)
    so a hostile or buggy caller cannot escape the profiles root via
    ``..`` segments, separators, or path separators.
    """
    return bool(_PROFILE_NAME_RE.fullmatch(name))


def default_profiles_root() -> Path | None:
    """Return the directory that contains all OpenSquilla profile homes.

    Honors ``OPENSQUILLA_HOME`` (trimmed, ``~``/``$HOME`` expanded).
    Returns ``None`` when unset or empty — that signals "profile mode is
    not active" and :func:`default_opensquilla_home` falls back to the
    legacy single-instance home (``$HOME/.opensquilla``).

    Returning ``None`` instead of a synthesized default keeps
    :func:`default_opensquilla_home` byte-compatible with deployments that
    never set the env var: the on-disk location is unchanged.
    """
    override = os.environ.get(_PROFILES_DIR_ENV, "").strip()
    if not override:
        return None
    return _expand_user(override)


def default_profile_name() -> str:
    """Return the active profile name (default ``"default"``).

    Trims whitespace; returns ``"default"`` when unset or empty.
    Callers that need to use the name as a path segment should still call
    :func:`is_valid_profile_name` to guard against operator-controlled
    values that bypass the env layer (config files, CLI args, RPC).
    """
    raw = os.environ.get(_PROFILE_ENV, "").strip()
    return raw or _DEFAULT_PROFILE_NAME


def profile_home(profile_name: str | None = None) -> Path:
    """Return the home directory for ``profile_name`` under the profiles root.

    Validates the name and raises :class:`ValueError` on path-traversal
    attempts. ``None`` means "use the current env-resolved profile name".

    Raises :class:`RuntimeError` when profile mode is not active (i.e.
    :func:`default_profiles_root` returns ``None``) but a non-default name
    was requested. Callers that want the legacy ``$HOME/.opensquilla``
    behavior should call :func:`default_opensquilla_home` directly.
    """
    name = (profile_name or default_profile_name()).strip()
    if not is_valid_profile_name(name):
        raise ValueError(
            f"Invalid OpenSquilla profile name: {name!r}. "
            f"Must match {_PROFILE_NAME_RE.pattern}."
        )
    root = default_profiles_root()
    if root is None:
        if name == _DEFAULT_PROFILE_NAME:
            return _home_dir() / ".opensquilla"
        raise RuntimeError(
            f"OpenSquilla profile mode is not active: "
            f"{_PROFILES_DIR_ENV} is not set, so profile {name!r} has no "
            f"profiles root to live in. Set {_PROFILES_DIR_ENV} to a directory "
            f"or unset {_PROFILE_ENV} to fall back to the legacy home."
        )
    return root / name


def default_opensquilla_home() -> Path:
    """Return the OpenSquilla state root as an absolute :class:`~pathlib.Path`.

    See the module docstring for the full precedence rules. In short:

    * ``OPENSQUILLA_STATE_DIR`` wins when set (back-compat with
      single-instance deployments that pin a specific path).
    * ``OPENSQUILLA_HOME`` set + ``OPENSQUILLA_PROFILE`` set →
      ``$OPENSQUILLA_HOME/$OPENSQUILLA_PROFILE`` (multi-instance).
    * Otherwise the legacy ``$HOME/.opensquilla`` home (unchanged).
    """
    override = os.environ.get(_STATE_DIR_ENV, "").strip()
    if override:
        return _expand_user(override)
    return profile_home()


def state_dir(*parts: str) -> Path:
    """Return a path under OpenSquilla's state directory.

    ``default_opensquilla_home()`` is the user-visible OpenSquilla home. Runtime state
    lives in the ``state`` subdirectory below it, matching the gateway config
    default and keeping prompt history out of the config/env root.
    """
    return default_opensquilla_home() / "state" / Path(*parts)


def media_root_from_config(config: object | None = None) -> Path:
    """Return the stable attachment/artifact media root.

    Explicit ``attachments.media_root`` wins. Otherwise derive from the configured
    OpenSquilla home instead of process cwd so artifact links keep working when the
    gateway is launched from a long or transient source/worktree path.
    """
    attachments_cfg = getattr(config, "attachments", None)
    media_root = getattr(attachments_cfg, "media_root", None)
    if isinstance(media_root, str) and media_root.strip():
        return _expand_user(media_root.strip())

    state_root = getattr(config, "state_dir", None)
    if isinstance(state_root, str) and state_root.strip():
        state_path = _expand_user(state_root.strip())
        return state_path.parent / "media"

    config_path = getattr(config, "config_path", None)
    if isinstance(config_path, str) and config_path.strip():
        return _expand_user(config_path.strip()).parent / "media"

    return default_opensquilla_home() / "media"
