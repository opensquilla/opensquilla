"""Capability SID storage for Windows sandbox roots."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CapabilityStore:
    root_sids: dict[str, str]


def load_capability_store(path: Path) -> CapabilityStore:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return CapabilityStore(root_sids={})
    if not isinstance(raw, dict):
        return CapabilityStore(root_sids={})
    roots = raw.get("rootSids")
    if not isinstance(roots, dict):
        return CapabilityStore(root_sids={})
    clean = {
        str(key): str(value)
        for key, value in roots.items()
        if str(value).startswith("S-1-15-3-")
    }
    return CapabilityStore(root_sids=clean)


def save_capability_store(path: Path, store: CapabilityStore) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"rootSids": store.root_sids}, sort_keys=True),
        encoding="utf-8",
    )


def capability_sid_for_root(
    store_path: Path,
    root: Path,
    *,
    sid_factory: Callable[[], str] | None = None,
) -> str:
    store = load_capability_store(store_path)
    key = str(root)
    existing = store.root_sids.get(key)
    if existing:
        return existing
    sid = sid_factory() if sid_factory is not None else _new_capability_sid()
    updated = dict(store.root_sids)
    updated[key] = sid
    save_capability_store(store_path, CapabilityStore(root_sids=updated))
    return sid


def capability_sids_for_command(store_path: Path, roots: tuple[Path, ...]) -> tuple[str, ...]:
    return tuple(capability_sid_for_root(store_path, root) for root in roots)


def _new_capability_sid() -> str:
    parts = [str(secrets.randbits(31)) for _ in range(8)]
    return "S-1-15-3-" + "-".join(parts)


__all__ = [
    "CapabilityStore",
    "capability_sid_for_root",
    "capability_sids_for_command",
    "load_capability_store",
    "save_capability_store",
]
