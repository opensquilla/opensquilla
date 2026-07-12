#!/usr/bin/env python3
"""Route offline pytest files into stable Windows CI responsibility shards."""

from __future__ import annotations

import argparse
import sys
import tomllib
import xml.etree.ElementTree as ET
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
    }
)


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


def shard_for_test(path: str) -> str:
    """Return the one responsibility shard for ``path`` or fail on ambiguity."""

    matches = matching_specialized_shards(path)
    if len(matches) > 1:
        joined = ", ".join(matches)
        raise ValueError(f"test file matches multiple Windows shards: {path} ({joined})")
    return matches[0] if matches else "core"


def files_for_shard(root: Path, shard: str) -> tuple[str, ...]:
    if shard not in SHARD_NAMES:
        raise ValueError(f"unknown Windows shard: {shard}")
    return tuple(path for path in discover_test_files(root) if shard_for_test(path) == shard)


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

    print(f"Running {len(files)} test files in Windows shard {args.shard}")
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
