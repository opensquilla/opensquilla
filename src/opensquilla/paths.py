"""OpenSquilla state-root resolution.

Single source of truth for the on-disk state root. Two env vars control
the root, and every subsystem derives its sub-path from the helpers here.

Resolution precedence for the home directory:

1. ``OPENSQUILLA_STATE_DIR`` environment variable (expanded for ``~``/``$HOME``)
   — full override; bypasses profile resolution for back-compat with
   single-instance deployments and CI scripts that pin a specific path.
2. ``$OPENSQUILLA_HOME/$OPENSQUILLA_PROFILE`` — multi-instance mode
   (the default on every host). Set ``OPENSQUILLA_HOME`` to the parent
   directory (default ``$HOME/.opensquilla/profiles``) and
   ``OPENSQUILLA_PROFILE`` (default ``"default"``) to select one. Profile
   names must match ``^[a-z0-9][a-z0-9_-]{0,63}$`` to prevent
   path-traversal escapes.

Multi-instance mode lets a single host run several OpenSquilla agents in
parallel, each with its own state/logs/config workspace, without sharing
locks, sockets, or state files. Multi-instance is the default so
``opensquilla --profile <name> init`` works without any environment
configuration; single-instance callers should set
``OPENSQUILLA_STATE_DIR`` to the legacy home path.
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
    "maybe_migrate_legacy_home",
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


def default_profiles_root() -> Path:
    """Return the directory that contains all OpenSquilla profile homes.

    Honors ``OPENSQUILLA_HOME`` (trimmed, ``~``/``$HOME`` expanded). When
    the env var is unset or empty, falls back to
    ``$HOME/.opensquilla/profiles`` so that
    ``opensquilla --profile <name> init`` works without any environment
    configuration. Each profile lives as a direct subdirectory of this
    root (``$HOME/.opensquilla/profiles/default/``,
    ``$HOME/.opensquilla/profiles/coder/``, …) — siblings, not nested,
    so an operator with ``OPENSQUILLA_HOME=D:\ai\opensquilla\profiles``
    gets the same flat layout as one who never set the env var.

    The legacy ``$HOME/.opensquilla`` home contents are auto-migrated
    into the ``default`` profile on first call — see
    :func:`maybe_migrate_legacy_home` for the safety contract.
    """
    override = os.environ.get(_PROFILES_DIR_ENV, "").strip()
    if override:
        return _expand_user(override)
    return _home_dir() / ".opensquilla" / "profiles"


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

    Resolves to ``default_profiles_root() / <profile_name>``. Validates the
    name and raises :class:`ValueError` on path-traversal attempts; ``None``
    means "use the current env-resolved profile name".

    The profiles root defaults to ``$HOME/.opensquilla/profiles`` when
    ``OPENSQUILLA_HOME`` is unset, so the default profile lands at
    ``$HOME/.opensquilla/profiles/default/`` and additional profiles
    (``--profile coder``) land at
    ``$HOME/.opensquilla/profiles/coder/`` — siblings, not nested.
    """
    name = (profile_name or default_profile_name()).strip()
    if not is_valid_profile_name(name):
        raise ValueError(
            f"Invalid OpenSquilla profile name: {name!r}. "
            f"Must match {_PROFILE_NAME_RE.pattern}."
        )
    return default_profiles_root() / name


def default_opensquilla_home() -> Path:
    """Return the OpenSquilla state root as an absolute :class:`~pathlib.Path`.

    See the module docstring for the full precedence rules. In short:

    * ``OPENSQUILLA_STATE_DIR`` wins when set (back-compat with
      single-instance deployments that pin a specific path).
    * Otherwise resolve to ``$OPENSQUILLA_HOME/$OPENSQUILLA_PROFILE``
      (multi-instance; defaults to ``$HOME/.opensquilla/profiles/default``
      when ``OPENSQUILLA_HOME`` is unset).

    Triggers a one-time automatic migration from the legacy
    ``$HOME/.opensquilla`` home when the resolver would otherwise land
    in ``$HOME/.opensquilla/profiles/default``; see
    :func:`maybe_migrate_legacy_home` for the safety contract.
    """
    override = os.environ.get(_STATE_DIR_ENV, "").strip()
    if override:
        return _expand_user(override)
    resolved = profile_home()
    maybe_migrate_legacy_home(resolved)
    return resolved


# --- Legacy migration -------------------------------------------------------

# Sentinel file written to the new home once migration has run. Prevents
# repeated migration on every CLI invocation; on hosts where the user
# later rolls back the migration manually, deleting the sentinel causes
# the next call to re-attempt it.
_MIGRATION_SENTINEL = ".migrated-to-profiles-root"

# Subpaths of a legacy $HOME/.opensquilla home that we know how to move
# into a profile subdirectory. Anything outside this list (e.g. a
# user-added `custom-stuff/`) is left in place under the legacy home so
# the migration is strictly additive.
_LEGACY_SUBDIRS = ("state", "logs", "workspace", "media")
_LEGACY_FILES = ("config.toml", ".env")


def _is_legacy_home_nonempty(legacy: Path) -> bool:
    """Return True if ``legacy`` looks like a real pre-profiles install."""
    if not legacy.is_dir():
        return False
    for name in _LEGACY_SUBDIRS:
        if (legacy / name).is_dir() and any((legacy / name).iterdir()):
            return True
    for name in _LEGACY_FILES:
        if (legacy / name).is_file():
            return True
    return False


def maybe_migrate_legacy_home(new_home: Path) -> bool:
    """One-time, best-effort migration of the legacy ``$HOME/.opensquilla``
    home into ``new_home`` (a profile directory).

    Returns ``True`` if a migration actually ran; ``False`` if no
    migration was needed or attempted. The migration is intentionally
    conservative:

    * Only runs when ``OPENSQUILLA_HOME`` is unset — explicit
      ``OPENSQUILLA_HOME`` callers own their layout and do not want
      silent moves of unrelated state.
    * Only moves the canonical subpaths listed in
      :data:`_LEGACY_SUBDIRS` / :data:`_LEGACY_FILES`; anything else
      under the legacy home stays put. This keeps the migration
      strictly additive.
    * Uses :func:`os.rename` (atomic on the same filesystem on POSIX
      and Windows when the source and target are on the same volume).
      Falls back to :func:`shutil.move` if rename fails across
      filesystems, and finally to copy+delete if even that fails — never
      loses the source, may leave the source in place on hard failure.
    * Writes :data:`_MIGRATION_SENTINEL` on success and skips the
      migration thereafter. Deleting the sentinel forces a re-run.

    The function is a no-op when:

    * the legacy home is missing or empty,
    * the new home already exists (operator-managed; do not touch),
    * a sentinel from a prior successful migration is present,
    * the current profile name is not ``"default"`` (only the default
      profile ever inherits the legacy layout — non-default profiles
      live strictly under the profiles root from day one).
    """
    # Only auto-migrate for the default profile, only when OPENSQUILLA_HOME
    # is unset, and only when the migration has not been disabled by an
    # explicit operator choice.
    if default_profile_name() != _DEFAULT_PROFILE_NAME:
        return False
    if os.environ.get(_PROFILES_DIR_ENV, "").strip():
        return False

    new_home = new_home.resolve()
    sentinel = new_home / _MIGRATION_SENTINEL
    if sentinel.exists():
        return False
    if new_home.exists():
        # The new home already has content. Either the operator
        # created it manually, or migration already ran and the
        # sentinel was deleted. Either way: do not touch — they
        # own the layout now.
        return False

    # The legacy home is the parent directory's sibling. For
    # `$HOME/.opensquilla/profiles/default`, the legacy home is
    # `$HOME/.opensquilla`.
    profiles_root = new_home.parent
    legacy = profiles_root.parent
    if not _is_legacy_home_nonempty(legacy):
        return False

    # Move the canonical subpaths into the new home. Rename is atomic
    # on the same volume; on cross-volume renames (rare for a fresh
    # install) we fall back to a copy that never deletes the source on
    # failure.
    import shutil

    new_home.mkdir(parents=True, exist_ok=True)
    moved_any = False
    for name in _LEGACY_SUBDIRS:
        src = legacy / name
        if not src.is_dir():
            continue
        dst = new_home / name
        if dst.exists():
            # The new home already has this subdir; leave both in
            # place rather than overwriting. Operator can reconcile.
            continue
        try:
            os.rename(src, dst)
        except OSError:
            try:
                shutil.move(str(src), str(dst))
            except Exception:
                # Last-resort: copy, never delete. The legacy
                # subdir remains in place so the operator can retry.
                shutil.copytree(src, dst)
        moved_any = True

    for name in _LEGACY_FILES:
        src = legacy / name
        if not src.is_file():
            continue
        dst = new_home / name
        if dst.exists():
            continue
        try:
            os.rename(src, dst)
        except OSError:
            try:
                shutil.move(str(src), str(dst))
            except Exception:
                shutil.copy2(src, dst)
        moved_any = True

    if moved_any:
        sentinel.touch()
        return True
    return False


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
