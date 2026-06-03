"""Durable user-level sandbox grant storage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from opensquilla.paths import state_dir

_STATE_FILE = "sandbox_user_grants.json"
_COLLECTIONS = frozenset({"mounts", "domains", "bundles"})


def load_user_grants_payload() -> dict[str, list[dict[str, Any]]]:
    raw = _read_state()
    return {
        "mounts": _items(raw.get("mounts")),
        "domains": _items(raw.get("domains")),
        "bundles": _items(raw.get("bundles")),
    }


def upsert_domain_grant(payload: dict[str, Any]) -> None:
    _upsert("domains", "domain", payload)


def remove_domain_grant(domain: str) -> None:
    _remove("domains", "domain", domain)


def upsert_mount_grant(payload: dict[str, Any]) -> None:
    _upsert("mounts", "path", payload)


def remove_mount_grant(path: str) -> None:
    _remove("mounts", "path", path)


def upsert_bundle_grant(payload: dict[str, Any]) -> None:
    _upsert("bundles", "bundle_id", payload)


def remove_bundle_grant(bundle_id: str) -> None:
    _remove("bundles", "bundle_id", bundle_id)


def _state_path() -> Path:
    return state_dir(_STATE_FILE)


def _read_state() -> dict[str, Any]:
    path = _state_path()
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_state(payload: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _state_with_collections(raw: dict[str, Any]) -> dict[str, Any]:
    state = {"version": 1}
    for collection in _COLLECTIONS:
        state[collection] = _items(raw.get(collection))
    return state


def _upsert(collection: str, key: str, payload: dict[str, Any]) -> None:
    value = str(payload.get(key) or "").strip()
    if not value:
        return
    state = _state_with_collections(_read_state())
    items = [item for item in state[collection] if str(item.get(key) or "").strip() != value]
    items.append(dict(payload))
    state[collection] = items
    _write_state(state)


def _remove(collection: str, key: str, value: str) -> None:
    normalized = str(value or "").strip()
    if not normalized:
        return
    state = _state_with_collections(_read_state())
    items = [item for item in state[collection] if str(item.get(key) or "").strip() != normalized]
    if items == state[collection]:
        return
    state[collection] = items
    _write_state(state)


__all__ = [
    "load_user_grants_payload",
    "remove_bundle_grant",
    "remove_domain_grant",
    "remove_mount_grant",
    "upsert_bundle_grant",
    "upsert_domain_grant",
    "upsert_mount_grant",
]
