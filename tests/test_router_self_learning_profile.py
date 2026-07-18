"""The hand-edited profile file: reads, caching, and content versioning.

The profile no longer accumulates anything of its own — the *learned* half
(``history``) is projected from Dream-consolidated memory (see
``test_router_self_learning_preference_projection.py``). What remains here is the
hand-edit surface for ``permission``/``preference`` (``deny_models`` has no TOML
key), so these lock the read behaviour that surface depends on: absent/broken
files degrade to ``None``, a copy is handed out so the cache cannot be
corrupted, a hand-edit is picked up on mtime, and ``content_version`` moves
exactly when the body does.
"""

from __future__ import annotations

import json
from pathlib import Path

from opensquilla.squilla_router.self_learning.profile import (
    content_version,
    load_profile,
    profile_path,
)

_MODEL = "anthropic/claude-sonnet-4-5"
_OTHER = "openai/gpt-5"


def _write(home: Path, payload: dict) -> Path:
    path = profile_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_absent_profile_loads_as_none(tmp_path: Path) -> None:
    assert load_profile(tmp_path) is None


def test_malformed_profile_degrades_to_none(tmp_path: Path) -> None:
    path = profile_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_profile(tmp_path) is None


def test_a_non_object_top_level_is_not_a_profile(tmp_path: Path) -> None:
    path = profile_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_profile(tmp_path) is None


def test_load_returns_a_copy_callers_cannot_corrupt_the_cache(tmp_path: Path) -> None:
    _write(tmp_path, {"permission": {"deny_models": [_MODEL]}})
    first = load_profile(tmp_path)
    assert first is not None
    first["permission"]["deny_models"].append("injected")

    second = load_profile(tmp_path)
    assert second is not None
    assert second["permission"]["deny_models"] == [_MODEL]


def test_hand_edit_is_picked_up_without_a_restart(tmp_path: Path) -> None:
    """The cache keys on mtime, not on write.

    ``deny_models`` is hand-edited and has no TOML key, so the invalidation path
    must react to an edit made outside any write path — keying it on write alone
    would ignore the one change the file exists to make.
    """
    _write(tmp_path, {"permission": {"deny_models": [_MODEL]}})
    assert load_profile(tmp_path)["permission"]["deny_models"] == [_MODEL]

    _write(tmp_path, {"permission": {"deny_models": [_OTHER]}})
    reloaded = load_profile(tmp_path)
    assert reloaded is not None
    assert reloaded["permission"]["deny_models"] == [_OTHER]


def test_version_changes_when_the_body_changes(tmp_path: Path) -> None:
    a = {"permission": {"deny_models": [_MODEL]}}
    b = {"permission": {"deny_models": [_OTHER]}}
    assert content_version(a) != content_version(b)


def test_version_ignores_its_own_output_and_the_timestamp(tmp_path: Path) -> None:
    """``profile_version`` is the output, and ``last_updated_at`` is noise.

    Excluding both means the same effective profile hashes the same whether or
    not a stale version is stamped on it and whichever day it was last touched.
    """
    base = {"history": {"positive_model_ids": [_MODEL], "last_updated_at": "2026-01-01"}}
    stamped = {
        "history": {"positive_model_ids": [_MODEL], "last_updated_at": "2026-07-18"},
        "profile_version": "sha256:deadbeefdeadbeef",
    }
    assert content_version(base) == content_version(stamped)
