#!/usr/bin/env python3
"""Capture and verify the exact Python/dependency runtime for a DRACO run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

SCHEMA = "opensquilla.draco-runtime-environment/v1"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def environment_payload(repo: Path) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    pyproject = repo / "pyproject.toml"
    lockfile = repo / "uv.lock"
    if not pyproject.is_file() or not lockfile.is_file():
        raise ValueError("formal runtime capture requires pyproject.toml and uv.lock")
    packages = sorted(
        {
            (
                str(distribution.metadata.get("Name") or "").strip().casefold(),
                str(distribution.version or "").strip(),
            )
            for distribution in metadata.distributions()
            if str(distribution.metadata.get("Name") or "").strip()
        }
    )
    return {
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "version": sys.version,
            "implementation": sys.implementation.name,
            "cache_tag": sys.implementation.cache_tag,
        },
        "platform": platform.platform(),
        "pyproject_sha256": file_sha256(pyproject),
        "uv_lock_sha256": file_sha256(lockfile),
        "installed_distributions": [
            {"name": name, "version": version} for name, version in packages
        ],
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("capture", "verify"))
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()

    current = environment_payload(args.repo)
    fingerprint = canonical_sha256(current)
    if args.command == "capture":
        if args.evidence.exists():
            parser.error(f"refusing to overwrite runtime evidence: {args.evidence}")
        atomic_write(
            args.evidence,
            {
                "schema": SCHEMA,
                "captured_at": datetime.now(UTC).isoformat(),
                "environment_sha256": fingerprint,
                "environment": current,
            },
        )
        return 0

    value = json.loads(args.evidence.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != SCHEMA
        or value.get("environment") != current
        or value.get("environment_sha256") != fingerprint
    ):
        raise ValueError("Python/dependency runtime changed after capture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
