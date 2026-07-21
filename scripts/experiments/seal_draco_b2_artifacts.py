#!/usr/bin/env python3
"""Snapshot and finalize authoritative DRACO B2 experiment artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA = "opensquilla.draco-b2-artifact-snapshot/v1"
SUCCESS_SCHEMA = "opensquilla.draco-b2-formal-success/v1"
ROUTE_PREFLIGHT_SCHEMA = "opensquilla.openrouter-route-preflight/v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
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


def relative_file_record(root: Path, path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"artifact is not a regular non-symlink file: {path}")
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact escapes snapshot root: {path}") from exc
    stat = resolved.stat()
    permissions = stat.st_mode & 0o777
    if permissions & 0o077:
        raise ValueError(
            f"artifact permissions expose benchmark data outside the owner: {path}"
        )
    return {
        "path": relative.as_posix(),
        "sha256": file_sha256(resolved),
        "size_bytes": stat.st_size,
        "mode": oct(permissions),
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"invalid artifact snapshot: {path}")
    return value


def safe_relative_path(value: Any, *, label: str) -> Path:
    relative = Path(str(value or ""))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} is not a safe relative path: {value!r}")
    return relative


def recursive_artifact_paths(
    root: Path, *, excluded: set[Path]
) -> list[Path]:
    artifacts: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(f"artifact tree contains a symlink: {candidate}")
        if candidate.is_file() and candidate.resolve(strict=True) not in excluded:
            artifacts.append(candidate.resolve(strict=True))
    return artifacts


def verify_snapshot(path: Path) -> dict[str, Any]:
    snapshot = load_snapshot(path)
    root_reference = safe_relative_path(snapshot.get("root"), label="snapshot root")
    root = (path.resolve(strict=True).parent / root_reference).resolve(strict=True)
    if root != path.resolve(strict=True).parent:
        raise ValueError(f"snapshot root must be its containing directory: {path}")
    records = snapshot.get("artifacts")
    if not isinstance(records, list) or not records:
        raise ValueError(f"artifact snapshot has no files: {path}")
    recorded_paths: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"artifact snapshot contains a non-object record: {path}")
        relative = safe_relative_path(record.get("path"), label="artifact path")
        relative_key = relative.as_posix()
        if relative_key in recorded_paths:
            raise ValueError(f"artifact snapshot contains duplicate paths: {path}")
        recorded_paths.add(relative_key)
        artifact = root / relative
        actual = relative_file_record(root, artifact)
        if actual != record:
            raise ValueError(f"artifact changed after audit: {artifact}")
    if snapshot.get("closed_world") is True:
        allowed_values = snapshot.get("allowed_after_snapshot") or []
        if not isinstance(allowed_values, list):
            raise ValueError(f"snapshot allowed-after list is invalid: {path}")
        allowed = {
            safe_relative_path(value, label="allowed-after path").as_posix()
            for value in allowed_values
        }
        snapshot_relative = path.resolve(strict=True).relative_to(root).as_posix()
        excluded = {
            path.resolve(strict=True),
            *{
                (root / relative).resolve(strict=False)
                for relative in allowed
            },
        }
        actual_paths = {
            artifact.relative_to(root).as_posix()
            for artifact in recursive_artifact_paths(root, excluded=excluded)
        }
        if actual_paths != recorded_paths:
            missing = sorted(recorded_paths - actual_paths)
            extra = sorted(actual_paths - recorded_paths)
            raise ValueError(
                f"artifact set changed after audit: missing={missing}, extra={extra}, "
                f"snapshot={snapshot_relative}"
            )
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("output", type=Path)
    snapshot_parser.add_argument("--root", type=Path, required=True)
    snapshot_parser.add_argument("--file", type=Path, action="append", default=[])
    snapshot_parser.add_argument("--recursive", action="store_true")
    snapshot_parser.add_argument("--allow-after", action="append", default=[])

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("snapshot", type=Path)

    success_parser = subparsers.add_parser("success")
    success_parser.add_argument("output", type=Path)
    success_parser.add_argument("--source-git-head", required=True)
    success_parser.add_argument("--input-sha256", required=True)
    success_parser.add_argument("--gateway-config-sha256", required=True)
    success_parser.add_argument("--experiment-config-sha256", required=True)
    success_parser.add_argument("--snapshot", type=Path, action="append", default=[])
    success_parser.add_argument("--evidence", type=Path, action="append", default=[])
    args = parser.parse_args()

    if args.command == "snapshot":
        if args.output.exists():
            parser.error(f"refusing to overwrite artifact snapshot: {args.output}")
        root = args.root.resolve(strict=True)
        output_resolved = args.output.resolve(strict=False)
        if output_resolved.parent != root:
            parser.error("artifact snapshot must be created directly inside --root")
        if args.recursive and args.file:
            parser.error("--recursive cannot be combined with --file")
        try:
            allowed_after = sorted(
                {
                    safe_relative_path(value, label="allowed-after path").as_posix()
                    for value in args.allow_after
                }
            )
        except ValueError as exc:
            parser.error(str(exc))
        excluded = {
            output_resolved,
            *{(root / relative).resolve(strict=False) for relative in allowed_after},
        }
        files = (
            recursive_artifact_paths(root, excluded=excluded)
            if args.recursive
            else sorted({path.resolve(strict=True) for path in args.file})
        )
        if not files:
            parser.error("artifact snapshot requires at least one --file")
        if output_resolved in files:
            parser.error("artifact snapshot cannot include itself")
        payload = {
            "schema": SNAPSHOT_SCHEMA,
            "created_at": datetime.now(UTC).isoformat(),
            "root": ".",
            "closed_world": bool(args.recursive),
            "allowed_after_snapshot": allowed_after,
            "artifacts": [relative_file_record(root, path) for path in files],
        }
        atomic_write_json(args.output, payload)
        return 0

    if args.command == "verify":
        verify_snapshot(args.snapshot)
        return 0

    if args.output.exists():
        parser.error(f"refusing to overwrite success sentinel: {args.output}")
    if not HEX40.fullmatch(args.source_git_head):
        parser.error("--source-git-head must be a 40-character lowercase hex commit")
    for field, value in (
        ("--input-sha256", args.input_sha256),
        ("--gateway-config-sha256", args.gateway_config_sha256),
        ("--experiment-config-sha256", args.experiment_config_sha256),
    ):
        if not HEX64.fullmatch(value):
            parser.error(f"{field} must be a 64-character lowercase hex digest")
    for path in args.snapshot:
        if path.is_symlink() or not path.is_file():
            parser.error(f"snapshot is not a regular non-symlink file: {path}")
        if path.stat().st_mode & 0o077:
            parser.error(f"snapshot permissions are not owner-only: {path}")
    resolved_snapshot_paths = [path.resolve(strict=True) for path in args.snapshot]
    if len(resolved_snapshot_paths) != 3 or len(set(resolved_snapshot_paths)) != 3:
        parser.error(
            "formal success requires exactly three distinct static/canary/full snapshots"
        )
    for path in args.evidence:
        if path.is_symlink() or not path.is_file():
            parser.error(f"evidence is not a regular non-symlink file: {path}")
        if path.stat().st_mode & 0o077:
            parser.error(f"evidence permissions are not owner-only: {path}")
    resolved_evidence_paths = [path.resolve(strict=True) for path in args.evidence]
    if len(resolved_evidence_paths) != 2 or len(set(resolved_evidence_paths)) != 2:
        parser.error(
            "formal success requires exactly two distinct route preflight artifacts"
        )
    success_root = args.output.resolve(strict=False).parent
    snapshots = []
    for snapshot_path in resolved_snapshot_paths:
        snapshot = verify_snapshot(snapshot_path)
        try:
            relative_snapshot = snapshot_path.relative_to(success_root).as_posix()
        except ValueError:
            parser.error(f"snapshot escapes success directory: {snapshot_path}")
        snapshots.append(
            {
                "path": relative_snapshot,
                "sha256": file_sha256(snapshot_path),
                "snapshot_schema": snapshot["schema"],
            }
        )
    evidence = []
    for resolved in resolved_evidence_paths:
        if resolved.is_symlink() or not resolved.is_file():
            parser.error(f"evidence is not a regular non-symlink file: {resolved}")
        try:
            route_payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid route preflight evidence {resolved}: {exc}")
        if (
            not isinstance(route_payload, dict)
            or route_payload.get("schema") != ROUTE_PREFLIGHT_SCHEMA
            or route_payload.get("pass") is not True
        ):
            parser.error(f"route preflight evidence did not pass: {resolved}")
        try:
            relative_evidence = resolved.relative_to(success_root).as_posix()
        except ValueError:
            parser.error(f"evidence escapes success directory: {resolved}")
        evidence.append(
            {
                "path": relative_evidence,
                "sha256": file_sha256(resolved),
                "size_bytes": resolved.stat().st_size,
            }
        )
    payload = {
        "schema": SUCCESS_SCHEMA,
        "status": "complete",
        "created_at": datetime.now(UTC).isoformat(),
        "source_git_head": args.source_git_head,
        "input_sha256": args.input_sha256,
        "gateway_config_sha256": args.gateway_config_sha256,
        "experiment_config_sha256": args.experiment_config_sha256,
        "artifact_snapshots": snapshots,
        "route_preflight_evidence": evidence,
    }
    atomic_write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
