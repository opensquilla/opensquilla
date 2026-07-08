"""Hygiene lint over migrations/*.py.

Guards three invariants of the migrations directory:

* Version prefixes are unique — except the grandfathered V010 pair
  (``V010__meta_skill_runs`` / ``V010__transcript_turn_usage``), which has
  distinct yoyo ids and is safe today but must never gain company.
* Every migration declares ``__depends__`` so yoyo orders it explicitly.
* Every migration is reachable from the head of the dependency graph, so
  dependency-aware partial-apply tooling cannot silently skip a leaf
  (the V010 transcript-usage migration was such a leaf until V018
  reconnected it).

Prefixes are NOT required to be strictly increasing or gap-free.

``__depends__`` is parsed with ``ast`` instead of importing the modules:
migration files call yoyo's ``step()`` at import time, which only works
inside yoyo's collector machinery.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

# The single allowed duplicate-prefix exception. Any NEW duplicate fails.
GRANDFATHERED_DUPLICATE_PREFIX = "V010"
GRANDFATHERED_V010_IDS = {
    "V010__meta_skill_runs",
    "V010__transcript_turn_usage",
}

_NAME_RE = re.compile(r"^(V(\d+))__.+\.py$")


def _migration_files() -> list[Path]:
    files = sorted(p for p in MIGRATIONS_DIR.glob("V*.py") if p.is_file())
    assert files, f"no migration files found under {MIGRATIONS_DIR}"
    return files


def _parse_depends(path: Path) -> set[str] | None:
    """Return the module-level ``__depends__`` value, or None when absent."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        target: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target, value = node.targets[0].id, node.value
        if target != "__depends__" or value is None:
            continue
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "set"
            and not value.args
        ):
            return set()
        deps = ast.literal_eval(value)
        return {str(dep) for dep in deps}
    return None


def test_migration_filenames_match_convention() -> None:
    bad = [p.name for p in _migration_files() if not _NAME_RE.match(p.name)]
    assert not bad, f"migration files must be named Vnnn__name.py: {bad}"


def test_version_prefixes_unique_except_grandfathered_v010() -> None:
    by_prefix: dict[str, list[str]] = {}
    for path in _migration_files():
        match = _NAME_RE.match(path.name)
        assert match is not None, path.name
        by_prefix.setdefault(match.group(1), []).append(path.stem)

    for prefix, ids in sorted(by_prefix.items()):
        if prefix == GRANDFATHERED_DUPLICATE_PREFIX:
            assert set(ids) == GRANDFATHERED_V010_IDS, (
                f"the {prefix} prefix is grandfathered ONLY for "
                f"{sorted(GRANDFATHERED_V010_IDS)}; found {sorted(ids)}"
            )
            continue
        assert len(ids) == 1, (
            f"duplicate migration version prefix {prefix}: {sorted(ids)}. "
            "Pick the next unused Vnnn prefix — duplicate prefixes are a "
            "hygiene hazard (only the historical V010 pair is allowed)."
        )


def test_every_migration_declares_depends() -> None:
    missing = [
        path.name for path in _migration_files() if _parse_depends(path) is None
    ]
    assert not missing, (
        f"migrations without a module-level __depends__: {missing}. "
        "Every migration must declare its dependencies explicitly."
    )


def test_all_migrations_reachable_from_dependency_head() -> None:
    """The max-prefix migration's __depends__ closure must cover every file.

    A migration outside the closure is a dangling leaf: dependency-aware
    partial-apply tooling targeting the head can skip it entirely. New
    migrations must name any current leaves in __depends__ (V018 did this
    for V010__transcript_turn_usage).
    """
    depends: dict[str, set[str]] = {}
    prefix_num: dict[str, int] = {}
    for path in _migration_files():
        match = _NAME_RE.match(path.name)
        assert match is not None, path.name
        deps = _parse_depends(path)
        assert deps is not None, path.name
        depends[path.stem] = deps
        prefix_num[path.stem] = int(match.group(2))

    unknown = {
        (mig, dep)
        for mig, deps in depends.items()
        for dep in deps
        if dep not in depends
    }
    assert not unknown, f"__depends__ references unknown migrations: {unknown}"

    head = max(depends, key=lambda mig: (prefix_num[mig], mig))
    reachable: set[str] = set()
    todo = [head]
    while todo:
        mig = todo.pop()
        if mig in reachable:
            continue
        reachable.add(mig)
        todo.extend(depends[mig])

    dangling = sorted(set(depends) - reachable)
    assert not dangling, (
        f"migrations unreachable from dependency head {head}: {dangling}. "
        "Add them to a newer migration's __depends__ so partial-apply "
        "tooling cannot skip them."
    )
