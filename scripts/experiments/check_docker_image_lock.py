#!/usr/bin/env python3
"""Verify eval Docker image tags against a digest lock."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"lock file must contain a JSON object: {path}")
    return data


def _read_instance_ids(paths: list[Path]) -> list[str]:
    instance_ids: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            instance_id = raw_line.strip()
            if not instance_id or instance_id.startswith("#") or instance_id in seen:
                continue
            seen.add(instance_id)
            instance_ids.append(instance_id)
    return instance_ids


def _records_by_instance(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = lock.get("records")
    if not isinstance(records, list):
        raise ValueError("lock file is missing records[]")
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("lock records must be JSON objects")
        instance_id = record.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("lock record missing instance_id")
        indexed[instance_id] = record
    return indexed


def _inspect_image_id(image_ref: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["docker", "inspect", image_ref, "--format", "{{.Id}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _expected_instances(
    records: dict[str, dict[str, Any]],
    instance_files: list[Path],
) -> list[str]:
    if instance_files:
        return _read_instance_ids(instance_files)
    return sorted(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        required=True,
        type=Path,
        help="Path to the image lock JSON.",
    )
    parser.add_argument(
        "--instance-file",
        action="append",
        default=[],
        type=Path,
        help="Instance id file to verify. May be repeated. Defaults to all lock records.",
    )
    args = parser.parse_args(argv)

    try:
        lock = _read_json(args.lock)
        records = _records_by_instance(lock)
        instance_ids = _expected_instances(records, args.instance_file)
    except Exception as exc:
        print(f"invalid_lock: {exc}", file=sys.stderr)
        return 1

    errors = 0
    for instance_id in instance_ids:
        record = records.get(instance_id)
        if record is None:
            print(f"missing_lock_record: {instance_id}", file=sys.stderr)
            errors += 1
            continue
        image_ref = record.get("image_ref")
        expected_id = record.get("image_id")
        if not isinstance(image_ref, str) or not isinstance(expected_id, str):
            print(f"invalid_lock_record: {instance_id}", file=sys.stderr)
            errors += 1
            continue
        returncode, actual_id, stderr = _inspect_image_id(image_ref)
        if returncode != 0:
            print(f"missing_image: {instance_id} {image_ref} {stderr}", file=sys.stderr)
            errors += 1
            continue
        if actual_id != expected_id:
            print(
                f"digest_mismatch: {instance_id} {image_ref} "
                f"expected={expected_id} actual={actual_id}",
                file=sys.stderr,
            )
            errors += 1

    if errors:
        print(f"checked={len(instance_ids)} errors={errors}", file=sys.stderr)
        return 1

    print(f"checked={len(instance_ids)} errors=0 tag={lock.get('tag', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
