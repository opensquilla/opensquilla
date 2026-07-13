#!/usr/bin/env python3
"""Route offline pytest files into stable Windows CI responsibility shards."""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Final

SHARD_NAMES: Final[tuple[str, ...]] = (
    "core",
    "gateway-sqlite",
    "recovery-migration",
    "desktop-installer-contracts",
)

_GATEWAY_SQLITE_PREFIXES: Final[tuple[str, ...]] = (
    "tests/test_gateway/",
    "tests/test_health/",
    "tests/test_observability/",
    "tests/test_persistence/",
    "tests/test_scheduler/",
    "tests/test_search/",
    "tests/test_session/",
)
_RECOVERY_MIGRATION_PREFIXES: Final[tuple[str, ...]] = (
    "tests/test_migration/",
    "tests/test_migrations/",
    "tests/test_recovery/",
)
_DESKTOP_INSTALLER_PREFIXES: Final[tuple[str, ...]] = (
    "tests/test_desktop/",
    "tests/test_dist/",
    "tests/test_packaging/",
    "tests/test_uninstall/",
)

_GATEWAY_SQLITE_NAME_TOKENS: Final[tuple[str, ...]] = (
    "database",
    "gateway",
    "memory",
    "scheduler",
    "session",
    "sqlite",
)
_RECOVERY_MIGRATION_NAME_TOKENS: Final[tuple[str, ...]] = (
    "legacy_config",
    "migrate",
    "migration",
    "recovery",
)
_DESKTOP_INSTALLER_NAME_TOKENS: Final[tuple[str, ...]] = (
    "artifact",
    "desktop",
    "install",
    "release",
    "uninstall",
    "wheelhouse",
)
_DESKTOP_INSTALLER_EXACT: Final[frozenset[str]] = frozenset(
    {
        "tests/test_compose_yaml_shape.py",
        "tests/test_root_start_scripts.py",
    }
)
_CORE_EXACT: Final[frozenset[str]] = frozenset(
    {
        "tests/test_ci/test_router_artifact_manifest.py",
        # This parity test executes Bun. Only the core job installs Bun and the
        # OpenTUI host dependencies, so it must not be moved by the balancer.
        "tests/unit/cli/tui/test_opentui_fuzzy_rank.py",
    }
)
_HARD_PINNED_SHARDS: Final[dict[str, str]] = {
    **{path: "core" for path in _CORE_EXACT},
    # This file consumes the two distinct roots provisioned only by the
    # recovery-migration Windows job. Other recovery tests use the same Python
    # environment as every shard and may safely participate in load balancing.
    "tests/test_recovery/test_atomic_and_locking.py": "recovery-migration",
}
_DURATION_FILE: Final[Path] = Path(__file__).with_name("windows_test_durations.json")


def discover_test_files(root: Path) -> tuple[str, ...]:
    """Return every pytest file below ``tests/`` as a repository-relative path."""

    tests_root = root / "tests"
    excluded = _pytest_excluded_prefixes(root)
    relative_paths = (
        path.relative_to(root).as_posix() for path in tests_root.rglob("test_*.py")
    )
    return tuple(
        sorted(
            relative
            for relative in relative_paths
            if not any(relative.startswith(prefix) for prefix in excluded)
        )
    )


def _pytest_excluded_prefixes(root: Path) -> tuple[str, ...]:
    pyproject = root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read pytest collection contract from {pyproject}") from exc
    configured = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    return tuple(
        f"{PurePosixPath(path).as_posix().rstrip('/')}/"
        for path in configured.get("norecursedirs", ())
        if PurePosixPath(path).as_posix().startswith("tests/")
    )


def matching_specialized_shards(path: str) -> tuple[str, ...]:
    """Return specialized shards whose responsibility rules match ``path``."""

    normalized = PurePosixPath(path).as_posix()
    if normalized in _CORE_EXACT:
        return ()
    name = PurePosixPath(normalized).name.casefold()
    prefix_matches: list[str] = []
    if normalized.startswith(_GATEWAY_SQLITE_PREFIXES):
        prefix_matches.append("gateway-sqlite")
    if normalized.startswith(_RECOVERY_MIGRATION_PREFIXES):
        prefix_matches.append("recovery-migration")
    if normalized.startswith(_DESKTOP_INSTALLER_PREFIXES):
        prefix_matches.append("desktop-installer-contracts")
    if prefix_matches:
        return tuple(prefix_matches)

    matches: list[str] = []
    if any(token in name for token in _GATEWAY_SQLITE_NAME_TOKENS):
        matches.append("gateway-sqlite")
    if any(token in name for token in _RECOVERY_MIGRATION_NAME_TOKENS):
        matches.append("recovery-migration")
    if normalized in _DESKTOP_INSTALLER_EXACT or any(
        token in name for token in _DESKTOP_INSTALLER_NAME_TOKENS
    ):
        matches.append("desktop-installer-contracts")

    return tuple(matches)


@cache
def historical_test_weights() -> dict[str, float]:
    """Load validated per-file Windows durations used by the stable balancer."""

    try:
        payload = json.loads(_DURATION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read Windows test durations from {_DURATION_FILE}") from exc

    if payload.get("schema_version") != 1:
        raise ValueError(f"unsupported Windows test duration schema in {_DURATION_FILE}")
    raw_weights = payload.get("weights_seconds")
    if not isinstance(raw_weights, dict):
        raise ValueError(f"missing weights_seconds mapping in {_DURATION_FILE}")

    weights: dict[str, float] = {}
    for raw_path, raw_weight in raw_weights.items():
        if not isinstance(raw_path, str):
            raise ValueError(f"non-string Windows test path in {_DURATION_FILE}")
        path = PurePosixPath(raw_path).as_posix()
        if (
            path != raw_path
            or not path.startswith("tests/")
            or not PurePosixPath(path).name.startswith("test_")
            or not path.endswith(".py")
        ):
            raise ValueError(f"invalid Windows test path in duration data: {raw_path!r}")
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
            raise ValueError(f"invalid Windows test weight for {path}: {raw_weight!r}")
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"invalid Windows test weight for {path}: {raw_weight!r}")
        weights[path] = weight
    if not weights:
        raise ValueError(f"empty Windows test duration data in {_DURATION_FILE}")
    return weights


@cache
def _balanced_assignments() -> dict[str, str]:
    """Assign known tests with affinity-aware longest-processing-time binning.

    Tests with job-specific runtime requirements are always pinned. Domain prefixes
    are affinities: the balancer keeps the maximum number of those files on their
    named shard without exceeding its fair-share duration budget, then balances the
    small overflow with generic tests. New unmatched tests are intentionally absent
    and therefore fail safe to ``core``.
    """

    weights = historical_test_weights()
    totals = dict.fromkeys(SHARD_NAMES, 0.0)
    assignments: dict[str, str] = {}
    candidates: list[tuple[str, float]] = []
    affinity_candidates: dict[str, list[tuple[str, float]]] = {
        shard: [] for shard in SHARD_NAMES
    }
    target = sum(weights.values()) / len(SHARD_NAMES)

    for path, shard in _HARD_PINNED_SHARDS.items():
        if path not in weights:
            continue
        assignments[path] = shard
        totals[shard] += weights[path]

    for path, weight in weights.items():
        if path in assignments:
            continue
        matches = matching_specialized_shards(path)
        if len(matches) > 1:
            joined = ", ".join(matches)
            raise ValueError(f"test file matches multiple Windows shards: {path} ({joined})")
        if matches:
            affinity_candidates[matches[0]].append((path, weight))
        else:
            candidates.append((path, weight))

    # Smallest-first retains the greatest number of domain-affinity files. Only
    # duration overflow is released to the common LPT queue.
    for shard in SHARD_NAMES:
        for path, weight in sorted(
            affinity_candidates[shard], key=lambda item: (item[1], item[0])
        ):
            if totals[shard] + weight <= target:
                assignments[path] = shard
                totals[shard] += weight
            else:
                candidates.append((path, weight))

    shard_order = {shard: index for index, shard in enumerate(SHARD_NAMES)}
    for path, weight in sorted(candidates, key=lambda item: (-item[1], item[0])):
        shard = min(SHARD_NAMES, key=lambda item: (totals[item], shard_order[item]))
        assignments[path] = shard
        totals[shard] += weight

    return assignments


def shard_for_test(path: str) -> str:
    """Return the one responsibility/balance shard for ``path`` or fail safely."""

    normalized = PurePosixPath(path).as_posix()
    assignment = _balanced_assignments().get(normalized)
    if assignment is not None:
        return assignment
    hard_pinned = _HARD_PINNED_SHARDS.get(normalized)
    if hard_pinned is not None:
        return hard_pinned
    matches = matching_specialized_shards(normalized)
    if len(matches) > 1:
        joined = ", ".join(matches)
        raise ValueError(f"test file matches multiple Windows shards: {normalized} ({joined})")
    if matches:
        return matches[0]
    return "core"


def files_for_shard(root: Path, shard: str) -> tuple[str, ...]:
    if shard not in SHARD_NAMES:
        raise ValueError(f"unknown Windows shard: {shard}")
    return tuple(path for path in discover_test_files(root) if shard_for_test(path) == shard)


def shard_weight_summary(root: Path) -> dict[str, tuple[int, float, int]]:
    """Return file count, historical seconds, and unweighted count per shard."""

    weights = historical_test_weights()
    summary: dict[str, tuple[int, float, int]] = {}
    for shard in SHARD_NAMES:
        files = files_for_shard(root, shard)
        summary[shard] = (
            len(files),
            sum(weights.get(path, 0.0) for path in files),
            sum(path not in weights for path in files),
        )
    return summary


def _write_failure_summary(junit_path: Path, summary_path: Path, exit_code: int) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"pytest_exit_code={exit_code}"]
    if not junit_path.is_file():
        lines.append("junit_status=unavailable")
        summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    try:
        root = ET.parse(junit_path).getroot()
    except (ET.ParseError, OSError) as exc:
        lines.extend(("junit_status=unreadable", f"detail={type(exc).__name__}"))
        summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    for testcase in root.iter("testcase"):
        failure = testcase.find("failure")
        if failure is None:
            failure = testcase.find("error")
        if failure is None:
            continue
        class_name = testcase.get("classname", "")
        test_name = testcase.get("name", "unknown")
        node = f"{class_name}::{test_name}" if class_name else test_name
        detail = (failure.text or failure.get("message") or "failure details unavailable").strip()
        lines.extend(
            (
                "junit_status=failed",
                f"first_failure={node}",
                "detail:",
                detail[:12_000],
            )
        )
        break
    else:
        lines.append("junit_status=passed" if exit_code == 0 else "junit_status=no-test-failure")

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    import pytest

    root = args.root.resolve()
    files = files_for_shard(root, args.shard)
    if not files:
        print(f"Windows shard {args.shard!r} has no tests", file=sys.stderr)
        return 2

    args.junit.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text("pytest_status=started\n", encoding="utf-8")

    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    pytest_args.extend(str(root / path) for path in files)
    pytest_args.append(f"--junitxml={args.junit}")

    _, weight, unweighted = shard_weight_summary(root)[args.shard]
    print(
        f"Running {len(files)} test files in CI shard {args.shard} "
        f"(historical weight: {weight:.1f}s; unweighted: {unweighted})"
    )
    exit_code = int(pytest.main(pytest_args))
    _write_failure_summary(args.junit, args.summary, exit_code)
    return exit_code


def _list(args: argparse.Namespace) -> int:
    for path in files_for_shard(args.root.resolve(), args.shard):
        print(path)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list files assigned to one shard")
    list_parser.add_argument("shard", choices=SHARD_NAMES)
    list_parser.add_argument("--root", type=Path, default=Path.cwd())
    list_parser.set_defaults(handler=_list)

    run_parser = subparsers.add_parser("run", help="run one shard through pytest")
    run_parser.add_argument("shard", choices=SHARD_NAMES)
    run_parser.add_argument("--root", type=Path, default=Path.cwd())
    run_parser.add_argument("--junit", type=Path, required=True)
    run_parser.add_argument("--summary", type=Path, required=True)
    run_parser.set_defaults(handler=_run)
    return parser


def main() -> int:
    parser = _parser()
    args, pytest_args = parser.parse_known_args()
    if args.command != "run" and pytest_args:
        parser.error(f"unrecognized arguments: {' '.join(pytest_args)}")
    args.pytest_args = pytest_args
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
