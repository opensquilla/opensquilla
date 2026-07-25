#!/usr/bin/env python3
"""Validate and emit the released Desktop upgrade matrix."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_EXPECTED_DESKTOP_TAGS = (
    "v0.4.0",
    "v0.4.1",
    "v0.5.0rc1",
    "v0.5.0rc2",
    "v0.5.0rc3",
    "v0.5.0rc4",
    "v0.5.0",
)
_TAG_PATTERN = re.compile(r"v(\d+\.\d+\.\d+)(?:rc(\d+))?")
_LAYOUTS = {"pre-rc3", "modern"}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("upgrade matrix must be a schema_version=1 JSON object")
    return payload


def _version_for_tag(tag: str) -> str:
    match = _TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"invalid released Desktop tag: {tag!r}")
    version, rc = match.groups()
    return f"{version}-rc{rc}" if rc else version


def _release_order(tag: str) -> tuple[int, int, int, int, int]:
    match = _TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"invalid Desktop candidate tag: {tag!r}")
    version, rc = match.groups()
    major, minor, patch = (int(part) for part in version.split("."))
    return (major, minor, patch, 0 if rc else 1, int(rc or 0))


def compatible_sources(
    sources: list[dict[str, str]],
    candidate_tag: str,
) -> list[dict[str, str]]:
    if not candidate_tag:
        return sources
    candidate_order = _release_order(candidate_tag)
    return [
        source
        for source in sources
        if _release_order(source["tag"]) <= candidate_order
    ]


def validate(path: Path) -> list[dict[str, str]]:
    payload = _load(path)
    raw_sources = payload.get("desktop_sources")
    if not isinstance(raw_sources, list):
        raise ValueError("desktop_sources must be an array")
    sources: list[dict[str, str]] = []
    for index, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            raise ValueError(f"desktop_sources[{index}] must be an object")
        required = ("tag", "version", "layout", "mac_asset", "windows_asset")
        if any(not isinstance(raw.get(name), str) or not raw[name] for name in required):
            raise ValueError(f"desktop_sources[{index}] is missing a required string field")
        source = {name: str(raw[name]) for name in required}
        expected_version = _version_for_tag(source["tag"])
        if source["version"] != expected_version:
            raise ValueError(
                f"{source['tag']} version {source['version']!r} != {expected_version!r}"
            )
        if source["layout"] not in _LAYOUTS:
            raise ValueError(f"{source['tag']} has unsupported layout {source['layout']!r}")
        expected_mac = f"OpenSquilla-{expected_version}-mac-arm64.dmg"
        expected_windows = f"OpenSquilla-{expected_version}-win-x64.exe"
        if source["mac_asset"] != expected_mac:
            raise ValueError(f"{source['tag']} mac_asset != {expected_mac!r}")
        if source["windows_asset"] != expected_windows:
            raise ValueError(f"{source['tag']} windows_asset != {expected_windows!r}")
        sources.append(source)

    tags = tuple(source["tag"] for source in sources)
    if tags != _EXPECTED_DESKTOP_TAGS:
        raise ValueError(
            "desktop_sources must contain every released Desktop tag exactly once; "
            f"got {tags!r}"
        )

    cli_sources = payload.get("cli_sources")
    if not isinstance(cli_sources, list) or len(cli_sources) != 1:
        raise ValueError("cli_sources must contain exactly the released v0.3.1 CLI source")
    cli_source = cli_sources[0]
    if not isinstance(cli_source, dict):
        raise ValueError("cli_sources[0] must be an object")
    if cli_source.get("tag") != "v0.3.1" or cli_source.get("kind") != "cli-home":
        raise ValueError("cli_sources[0] must be the v0.3.1 cli-home source")
    for field in ("release_commit", "python_paths_blob", "session_storage_blob"):
        value = cli_source.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ValueError(f"cli_sources[0].{field} must be a 40-character Git object id")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--platform", choices=("mac", "windows"))
    parser.add_argument("--format", choices=("check", "tsv"), default="check")
    parser.add_argument(
        "--candidate-tag",
        default="",
        help="emit only sources that are not newer than an existing candidate tag",
    )
    args = parser.parse_args()
    try:
        sources = compatible_sources(validate(args.matrix), args.candidate_tag)
        if args.format == "tsv":
            if args.platform is None:
                raise ValueError("--platform is required with --format=tsv")
            if not sources:
                raise ValueError(
                    f"no released Desktop sources are compatible with {args.candidate_tag!r}"
                )
            asset_field = "mac_asset" if args.platform == "mac" else "windows_asset"
            for source in sources:
                print(
                    source["tag"],
                    source["version"],
                    source["layout"],
                    source[asset_field],
                    sep="\t",
                )
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid released Desktop upgrade matrix: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
