#!/usr/bin/env python3
"""Seed and verify synthetic Desktop profile data around installer operations."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

_LABEL_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,80}")


def _validated_label(value: str) -> str:
    if _LABEL_PATTERN.fullmatch(value) is None:
        raise ValueError("label must contain only ASCII letters, digits, dot, underscore, or dash")
    return value


def _workspace_files(label: str) -> dict[str, str]:
    return {
        "IDENTITY.md": f"# Synthetic {label} identity sentinel\n",
        "USER.md": f"# Synthetic {label} user\n",
        "SOUL.md": f"# Synthetic {label} soul\n",
        "MEMORY.md": f"# Synthetic {label} memory\n",
    }


def _config_text(home: Path, label: str) -> str:
    return (
        f"# Synthetic {label} release-preservation profile\n"
        f"state_dir = {json.dumps(str(home / 'state'))}\n"
        f"workspace_dir = {json.dumps(str(home / 'workspace'))}\n"
    )


def seed_profile(home: Path, label: str) -> None:
    """Create a minimal synthetic RC3-shaped profile without replacing any file."""

    home = home.resolve()
    workspace = home / "workspace"
    state = home / "state"
    protected = [home / "config.toml", state / "sessions.db"] + [
        workspace / name for name in _workspace_files(label)
    ]
    existing = [path for path in protected if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite preservation fixture: {existing[0]}")

    workspace.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    for name, expected in _workspace_files(label).items():
        (workspace / name).write_text(expected, encoding="utf-8", newline="")
    (home / "config.toml").write_text(_config_text(home, label), encoding="utf-8", newline="")

    with sqlite3.connect(state / "sessions.db") as connection:
        connection.execute(
            "CREATE TABLE release_preservation_chat (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO release_preservation_chat (id, body) VALUES (?, ?)",
            (f"{label}-session", f"synthetic retained chat ({label})"),
        )
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result != ("ok",):
            raise RuntimeError(f"seeded sessions.db failed PRAGMA quick_check: {result!r}")


def verify_profile(home: Path, label: str) -> None:
    """Verify exact fixture bytes and a read-only SQLite integrity probe."""

    home = home.resolve()
    workspace = home / "workspace"
    state = home / "state"
    for name, expected in _workspace_files(label).items():
        actual = (workspace / name).read_text(encoding="utf-8")
        if actual != expected:
            raise AssertionError(f"{name} changed while installing or uninstalling Desktop")

    actual_config = (home / "config.toml").read_text(encoding="utf-8")
    if actual_config != _config_text(home, label):
        raise AssertionError("config.toml changed while installing or uninstalling Desktop")

    database = state / "sessions.db"
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check != ("ok",):
            raise AssertionError(f"sessions.db failed PRAGMA quick_check: {quick_check!r}")
        row = connection.execute("SELECT id, body FROM release_preservation_chat").fetchone()
    expected_row = (f"{label}-session", f"synthetic retained chat ({label})")
    if row != expected_row:
        raise AssertionError(f"sessions.db retained-chat row changed: {row!r}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("seed", "verify"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--label", type=_validated_label, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.operation == "seed":
            seed_profile(args.home, args.label)
            print(f"profile preservation fixture seeded: {args.home}")
        else:
            verify_profile(args.home, args.label)
            print(f"profile preservation verified: {args.home}")
    except (
        AssertionError,
        FileExistsError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
