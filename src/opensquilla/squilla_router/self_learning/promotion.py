"""Active-bundle pointer, atomic promotion, quarantine, and rollback.

The shipped baseline under ``site-packages`` is never mutated. A single pointer
file ``~/.opensquilla/router/active`` selects which bundle the router loads:

    baseline            -> the packaged/configured base bundle
    learned/<version>   -> a promoted candidate under router/learned/<version>

Promotion and rollback are just atomic rewrites of that one pointer, so a bad
candidate is reverted by pointing back to ``baseline``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from opensquilla.squilla_router.self_learning.store import router_data_root

_BASELINE = "baseline"


def active_pointer_path(home: Path | None = None) -> Path:
    return router_data_root(home) / "active"


def learned_root(home: Path | None = None) -> Path:
    return router_data_root(home) / "learned"


def learned_bundle_dir(version: str, home: Path | None = None) -> Path:
    return learned_root(home) / version


def read_active(home: Path | None = None) -> str:
    path = active_pointer_path(home)
    if not path.is_file():
        return _BASELINE
    value = path.read_text(encoding="utf-8").strip()
    return value or _BASELINE


def write_active_atomic(value: str, home: Path | None = None) -> None:
    """Atomically set the active pointer (write temp + os.replace)."""

    path = active_pointer_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, path)


def resolve_active_bundle_dir(home: Path | None = None) -> Path | None:
    """Return the learned bundle dir to load, or ``None`` to use the baseline.

    Falls back to baseline if the pointer references a missing/incomplete bundle.
    """

    active = read_active(home)
    if active == _BASELINE:
        return None
    if active.startswith("learned/"):
        version = active.split("/", 1)[1]
        bundle = learned_bundle_dir(version, home)
        if (bundle / "lgbm_main.bin").is_file():
            return bundle
    return None


def promote_candidate(version: str, home: Path | None = None) -> str:
    """Point active at ``learned/<version>``. Returns the previous pointer value."""

    previous = read_active(home)
    write_active_atomic(f"learned/{version}", home)
    return previous


def rollback_active(home: Path | None = None, *, to: str = _BASELINE) -> str:
    """Revert the active pointer (default: back to baseline). Returns previous."""

    previous = read_active(home)
    write_active_atomic(to, home)
    return previous


def quarantine_candidate(version: str, home: Path | None = None) -> Path | None:
    """Move a rejected/bad candidate out of ``learned/`` so it is never loaded."""

    src = learned_bundle_dir(version, home)
    if not src.exists():
        return None
    dest_root = learned_root(home) / ".quarantine"
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / version
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(src), str(dest))
    return dest


def should_rollback(
    *,
    pre_complaint_rate: float | None,
    post_complaint_rate: float,
    post_n: int,
    config: Any,
) -> bool:
    """Decide whether a live candidate has regressed enough to revert.

    Requires a minimum post-swap sample count before acting, then trips when the
    complaint rate rises beyond the configured delta over the pre-swap baseline.
    """

    if not bool(getattr(config, "auto_rollback", True)):
        return False
    if pre_complaint_rate is None:
        return False
    if post_n < int(getattr(config, "min_monitor_samples", 30)):
        return False
    delta = float(getattr(config, "complaint_regression_delta", 0.05))
    return post_complaint_rate > pre_complaint_rate + delta
