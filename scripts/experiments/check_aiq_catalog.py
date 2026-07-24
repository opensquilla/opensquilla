"""Check the OpenSquilla AIQ tool catalog against a live AIQ checkout.

This is an offline developer guard: it imports AIQ ``FunctionTool`` objects and
compares their parameter names, structural types, array item types, and
semantic required fields with the build-time ``catalog.json`` snapshot.
Curated OpenSquilla descriptions, defaults, and narrower enums may
intentionally differ, so they are not rewritten here.

Usage:
    uv run python scripts/experiments/check_aiq_catalog.py \
        --aiq-repo /path/to/aiq
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "src" / "opensquilla" / "contrib" / "aiq" / "catalog.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aiq-repo",
        type=Path,
        required=True,
        help="AIQ repository whose FunctionTool schemas are authoritative",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="OpenSquilla catalog snapshot to check",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable drift details",
    )
    parser.add_argument("--_in-aiq-env", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def _types(schema: dict[str, Any]) -> tuple[str, ...]:
    raw_type = schema.get("type")
    values = raw_type if isinstance(raw_type, list) else [raw_type]
    if isinstance(schema.get("anyOf"), list):
        values = [
            arm.get("type") for arm in schema["anyOf"] if isinstance(arm, dict) and arm.get("type")
        ]
    return tuple(sorted(str(value) for value in values if value))


def _item_types(schema: dict[str, Any]) -> tuple[str, ...]:
    candidates = [schema]
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        candidates.extend(arm for arm in any_of if isinstance(arm, dict))
    values = {
        item_type
        for candidate in candidates
        if isinstance(candidate.get("items"), dict)
        for item_type in _types(candidate["items"])
    }
    return tuple(sorted(values))


def compare_catalog(catalog_path: Path, aiq_repo: Path) -> list[dict[str, Any]]:
    """Return one drift record per mismatched or unimportable tool."""

    if not (aiq_repo / "lib" / "tools").is_dir():
        raise ValueError(f"{aiq_repo} is not an AIQ checkout (missing lib/tools)")
    entries = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError(f"{catalog_path} must contain a JSON array")

    sys.path.insert(0, str(aiq_repo.resolve()))
    drift: list[dict[str, Any]] = []
    names = [str(entry.get("name") or "") for entry in entries if isinstance(entry, dict)]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        drift.append(
            {
                "tool": "<catalog>",
                "duplicate_tool_names": duplicate_names,
            }
        )

    for entry in entries:
        name = str(entry.get("name") or "")
        try:
            tool = getattr(
                importlib.import_module(str(entry["module"])),
                str(entry["attr"]),
            )
            live_schema = tool.params_json_schema
            live = live_schema.get("properties", {})
        except Exception as exc:  # noqa: BLE001 - report every catalog import failure
            drift.append(
                {
                    "tool": name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        snapshot = entry.get("params")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        missing = sorted(set(live) - set(snapshot))
        extra = sorted(set(snapshot) - set(live))
        # OpenAI strict schemas list every property under ``required`` even
        # when the Python parameter has a default or accepts null. Recover the
        # semantic required set so this check does not force optional/defaulted
        # fields into every OpenSquilla call.
        strict_required = {
            str(value) for value in live_schema.get("required", []) if isinstance(value, str)
        }
        live_required = {
            name
            for name in strict_required
            if name in live and "default" not in live[name] and "null" not in _types(live[name])
        }
        snapshot_required = {
            str(value) for value in entry.get("required", []) if isinstance(value, str)
        }
        missing_required = sorted(live_required - snapshot_required)
        extra_required = sorted(snapshot_required - live_required)
        structural = []
        for parameter in sorted(set(live) & set(snapshot)):
            live_schema = live[parameter]
            snapshot_schema = snapshot[parameter]
            if not isinstance(live_schema, dict) or not isinstance(snapshot_schema, dict):
                structural.append(
                    {
                        "parameter": parameter,
                        "live": live_schema,
                        "catalog": snapshot_schema,
                    }
                )
                continue
            live_shape = {
                "types": _types(live_schema),
                "item_types": _item_types(live_schema),
            }
            catalog_shape = {
                "types": _types(snapshot_schema),
                "item_types": _item_types(snapshot_schema),
            }
            if live_shape != catalog_shape:
                structural.append(
                    {
                        "parameter": parameter,
                        "live": live_shape,
                        "catalog": catalog_shape,
                    }
                )
        if missing or extra or missing_required or extra_required or structural:
            drift.append(
                {
                    "tool": name,
                    "missing_in_catalog": missing,
                    "extra_in_catalog": extra,
                    "missing_required_in_catalog": missing_required,
                    "extra_required_in_catalog": extra_required,
                    "structural_drift": structural,
                }
            )
    return drift


def main() -> int:
    args = _parse_args()
    if not args._in_aiq_env and importlib.util.find_spec("agents") is None:
        uv = shutil.which("uv")
        if uv is None:
            print(
                "The current Python environment lacks AIQ dependencies and `uv` "
                "was not found. Run this script from the AIQ virtual environment.",
                file=sys.stderr,
            )
            return 2
        command = [
            uv,
            "run",
            "--no-sync",
            "--project",
            str(args.aiq_repo.resolve()),
            "python",
            str(Path(__file__).resolve()),
            "--aiq-repo",
            str(args.aiq_repo.resolve()),
            "--catalog",
            str(args.catalog.resolve()),
            "--_in-aiq-env",
        ]
        if args.json:
            command.append("--json")
        return subprocess.run(command, check=False).returncode

    drift = compare_catalog(args.catalog.resolve(), args.aiq_repo.resolve())
    if args.json:
        print(json.dumps(drift, indent=2, default=str))
    elif drift:
        print(f"AIQ catalog drift detected in {len(drift)} tool(s):")
        for item in drift:
            print(f"- {item['tool']}: {json.dumps(item, default=str)}")
    else:
        print("AIQ catalog matches the live tool parameter/type contract.")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
