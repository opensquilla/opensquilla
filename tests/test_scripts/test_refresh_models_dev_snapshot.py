"""Offline tests for scripts/refresh_models_dev_snapshot.py.

The transform (``build_snapshot_providers``) and the integrity guards
(``check_snapshot_integrity``) are pure, so everything here runs against
synthetic payloads — no network, no models.dev fetch.
"""

from __future__ import annotations

import json

from scripts.refresh_models_dev_snapshot import (
    MAX_SHRINK_RATIO,
    SNAPSHOT_PATH,
    _trim_model,
    build_snapshot_providers,
    check_snapshot_integrity,
)

# Synthetic models.dev api.json payload: two providers, three models —
# one with flat costs, one with tiered-only costs (flat keys omitted),
# one self-contradictory (context < output → dropped).
_FAKE_API: dict = {
    "acme": {
        "models": {
            "Acme-Priced": {
                "limit": {"context": 200_000, "output": 32_000},
                "reasoning": True,
                "tool_call": True,
                "modalities": {"input": ["text", "image"]},
                "cost": {
                    "input": 2.5,
                    "output": 10.0,
                    "cache_read": 0.25,
                    "cache_write": 3.125,
                },
            },
            "acme-contradictory": {
                "limit": {"context": 4_096, "output": 8_192},
                "tool_call": True,
                "cost": {"input": 1.0, "output": 2.0},
            },
        }
    },
    "budget": {
        "models": {
            "budget-tiered": {
                "limit": {"context": 100_000, "output": 8_000},
                "cost": {
                    "input": [{"up_to": 128_000, "cost": 1.0}],
                    "output": {"tiers": [{"up_to": 128_000, "cost": 4.0}]},
                },
            }
        }
    },
}

_FAKE_SOURCES = {"acme_cloud": ("acme",), "budget_cloud": ("budget",)}


def _snapshot(tables: dict) -> dict:
    return {"providers": tables}


# ---------------------------------------------------------------------------
# Transform (build_snapshot_providers / _trim_model)
# ---------------------------------------------------------------------------


def test_transform_emits_flat_costs_and_keeps_drop_rules() -> None:
    providers = build_snapshot_providers(_FAKE_API, _FAKE_SOURCES)

    assert set(providers) == {"acme_cloud", "budget_cloud"}
    # Model ids are lowercased; the contradictory entry is dropped.
    assert set(providers["acme_cloud"]) == {"acme-priced"}
    assert providers["acme_cloud"]["acme-priced"] == {
        "ctx": 200_000,
        "out": 32_000,
        "reasoning": True,
        "tools": True,
        "vision": True,
        "in_mtok": 2.5,
        "out_mtok": 10.0,
        "cr_mtok": 0.25,
        "cw_mtok": 3.125,
    }
    # Tiered-only pricing: capability shape is emitted, flat cost keys are not.
    assert providers["budget_cloud"]["budget-tiered"] == {
        "ctx": 100_000,
        "out": 8_000,
        "reasoning": False,
        "tools": False,
        "vision": False,
    }


def test_trim_model_vendors_only_flat_nonnegative_leaf_costs() -> None:
    trimmed = _trim_model(
        {
            "limit": {"context": 50_000, "output": 5_000},
            "cost": {
                "input": 0.5,  # flat leaf → vendored
                "output": {"tiered": True},  # nested → ignored
                "cache_read": -1.0,  # negative garbage → ignored
                "cache_write": True,  # boolean → not a price, ignored
            },
        }
    )

    assert trimmed == {
        "ctx": 50_000,
        "out": 5_000,
        "reasoning": False,
        "tools": False,
        "vision": False,
        "in_mtok": 0.5,
    }


def test_trim_model_without_cost_block_emits_no_cost_keys() -> None:
    trimmed = _trim_model({"limit": {"context": 8_192, "output": 4_096}, "tool_call": True})

    assert trimmed is not None
    assert set(trimmed) == {"ctx", "out", "reasoning", "tools", "vision"}


# ---------------------------------------------------------------------------
# Integrity guards (check_snapshot_integrity)
# ---------------------------------------------------------------------------


def test_shrink_guard_fails_below_the_floor() -> None:
    old = _snapshot({"a": {f"m{i}": {} for i in range(10)}})
    new = _snapshot({"a": {f"m{i}": {} for i in range(7)}})

    errors = check_snapshot_integrity(new, old, required_provider_ids=[])

    assert len(errors) == 1
    assert "7" in errors[0] and "10" in errors[0]


def test_shrink_guard_allows_exactly_the_floor() -> None:
    assert MAX_SHRINK_RATIO == 0.8
    old = _snapshot({"a": {f"m{i}": {} for i in range(10)}})
    new = _snapshot({"a": {f"m{i}": {} for i in range(8)}})

    assert check_snapshot_integrity(new, old, required_provider_ids=[]) == []


def test_regression_guard_flags_a_lost_required_table() -> None:
    old = _snapshot({"a": {"m": {}}, "b": {"m": {}}})
    new = _snapshot({"a": {"m": {}, "m2": {}}})  # same total, but "b" vanished

    errors = check_snapshot_integrity(new, old, required_provider_ids=["a", "b"])

    assert len(errors) == 1
    assert "'b'" in errors[0]


def test_regression_guard_ignores_providers_the_committed_snapshot_lacks() -> None:
    old = _snapshot({"a": {"m": {}}})
    new = _snapshot({"a": {"m": {}}})

    assert check_snapshot_integrity(new, old, required_provider_ids=["a", "brand-new"]) == []


def test_empty_committed_snapshot_never_blocks_a_first_write() -> None:
    new = _snapshot({"a": {"m": {}}})

    assert check_snapshot_integrity(new, {}, required_provider_ids=["a"]) == []


def test_committed_snapshot_passes_its_own_integrity_check() -> None:
    # Identity comparison over the real committed snapshot, exercising the
    # registry-derived default for required provider ids — still offline.
    committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert check_snapshot_integrity(committed, committed) == []
