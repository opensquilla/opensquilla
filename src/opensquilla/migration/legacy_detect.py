"""Read-only detection of importable legacy OpenSquilla homes.

The Phase 3 advisory surfaces (gateway boot warning, ``opensquilla doctor``,
``onboarding.status``) share this one detector so they all point at the same
candidate with the same suggested command. Detection only stats paths — the
import itself stays behind ``opensquilla migrate opensquilla`` at the CLI
layer, which requires a quiesced gateway.
"""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

#: Env vars that ever hosted a Windows-portable data dir; when neither is set
#: (and the platform is not Windows) portable enumeration is skipped entirely.
_PORTABLE_BASE_ENV_VARS = ("LOCALAPPDATA", "TEMP")


@dataclass(frozen=True)
class LegacyHomeCandidate:
    """One importable legacy home: where it lives and which source kind it is."""

    path: Path
    kind: str


def detect_legacy_home(target: Path | None = None) -> LegacyHomeCandidate | None:
    """Return the most likely legacy OpenSquilla home distinct from ``target``.

    ``target`` defaults to :func:`~opensquilla.paths.default_opensquilla_home`.
    A legacy CLI home (``~/.opensquilla``) wins over Windows-portable data
    dirs; portable enumeration only runs where such dirs can exist (Windows,
    or a ``LOCALAPPDATA``/``TEMP`` env base being present) and offers the
    newest candidate.

    Read-only and exception-free by contract: advisory callers must never
    fail because detection hit an unreadable disk, so any ``OSError``
    collapses to ``None``.
    """
    try:
        from opensquilla.migration.opensquilla_home import (
            _same_path,
            detect_legacy_cli_home,
            enumerate_portable_homes,
        )
        from opensquilla.paths import default_opensquilla_home

        resolved_target = target if target is not None else default_opensquilla_home()
        cli_home = detect_legacy_cli_home(resolved_target)
        if cli_home is not None:
            return LegacyHomeCandidate(path=cli_home, kind="cli-home")
        if sys.platform == "win32" or _portable_bases_present():
            for candidate in enumerate_portable_homes():
                # Never offer the live home as its own migration source
                # (mirrors the detect_legacy_cli_home guard).
                if _same_path(candidate.path, resolved_target):
                    continue
                return LegacyHomeCandidate(path=candidate.path, kind="windows-portable")
    except OSError:
        return None
    return None


def suggested_migrate_command(candidate: LegacyHomeCandidate) -> str:
    """Render the CLI invocation that previews importing ``candidate``.

    The command dry-runs by default; appending ``--apply`` performs the
    import.
    """
    return (
        "opensquilla migrate opensquilla "
        f"--kind {candidate.kind} --source {_command_path(candidate.path)}"
    )


def _portable_bases_present() -> bool:
    return any(os.environ.get(name, "").strip() for name in _PORTABLE_BASE_ENV_VARS)


def _command_path(path: Path) -> str:
    raw = str(path)
    if any(ch.isspace() for ch in raw):
        return shlex.quote(raw)
    return raw
