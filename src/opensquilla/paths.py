"""OpenSquilla state-root resolution.

Single source of truth for the on-disk state root. One env var controls
the root, and every subsystem derives its sub-path from the helper here.

Precedence:
1. ``OPENSQUILLA_STATE_DIR`` environment variable (expanded for ``~``/``$HOME``)
2. ``$HOME/.opensquilla``
"""

from __future__ import annotations

import os
from pathlib import Path


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


def default_opensquilla_home() -> Path:
    """Return the OpenSquilla state root as an absolute :class:`~pathlib.Path`.

    Honors ``OPENSQUILLA_STATE_DIR`` (trimmed, ``~`` expanded). Falls back to
    ``$HOME/.opensquilla`` when unset or empty.
    """
    override = os.environ.get("OPENSQUILLA_STATE_DIR", "").strip()
    if override:
        return _expand_user(override)
    return _home_dir() / ".opensquilla"


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
