"""Boundary tests for channel in-flight ownership."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


def _make_config(*, channel_inflight_cap: int = 8, max_concurrency: int = 4) -> Any:
    cfg = MagicMock()
    cfg.task_runtime.channel_inflight_cap = channel_inflight_cap
    cfg.task_runtime.max_concurrency = max_concurrency
    return cfg


def test_channel_inflight_module_exposes_public_api() -> None:
    """The new owning module exposes public in-flight helpers."""
    spec = importlib.util.find_spec("opensquilla.gateway.channel_inflight")
    assert spec is not None

    module = importlib.import_module("opensquilla.gateway.channel_inflight")

    assert hasattr(module, "ChannelInFlightSet")
    assert hasattr(module, "compute_channel_cap")


def test_channel_inflight_behavior_and_cap_semantics_match_dispatch_aliases() -> None:
    """Public helpers preserve the legacy tracker behavior and cap formula."""
    inflight = importlib.import_module("opensquilla.gateway.channel_inflight")
    dispatch = importlib.import_module("opensquilla.gateway.channel_dispatch")

    assert inflight.ChannelInFlightSet.__doc__ == dispatch._ChannelInFlightSet.__doc__
    doc = inflight.ChannelInFlightSet.__doc__ or ""
    assert "second-layer semaphore" in doc
    assert "global_sem" in doc
    assert "min(channel_inflight_cap, max(2" in doc

    tracker = inflight.ChannelInFlightSet(cap=2)
    first = object()
    second = object()
    third = object()

    assert tracker.cap == 2
    assert tracker.try_acquire(first) is True
    assert tracker.try_acquire(second) is True
    assert tracker.full()
    assert tracker.try_acquire(third) is False
    tracker.release(first)
    assert not tracker.full()
    assert tracker.try_acquire(third) is True

    cases = [
        (_make_config(channel_inflight_cap=8, max_concurrency=1), 2),
        (_make_config(channel_inflight_cap=8, max_concurrency=4), 8),
        (_make_config(channel_inflight_cap=3, max_concurrency=16), 3),
        (_make_config(channel_inflight_cap=8, max_concurrency=0), 1),
        (None, 8),
        (object(), 8),
    ]
    for config, expected in cases:
        assert inflight.compute_channel_cap(config) == expected
        assert dispatch._compute_channel_cap(config) == expected


def test_channel_dispatch_preserves_private_compatibility_aliases() -> None:
    """Legacy private imports remain aliases to the new owning module."""
    inflight = importlib.import_module("opensquilla.gateway.channel_inflight")
    dispatch = importlib.import_module("opensquilla.gateway.channel_dispatch")

    assert dispatch._ChannelInFlightSet is inflight.ChannelInFlightSet
    assert dispatch._compute_channel_cap is inflight.compute_channel_cap


def test_source_ownership_moves_implementation_out_of_channel_dispatch() -> None:
    """The class/function definitions live in channel_inflight.py."""
    repo_root = Path(__file__).resolve().parents[2]
    dispatch_source = (
        repo_root / "src" / "opensquilla" / "gateway" / "channel_dispatch.py"
    ).read_text()
    inflight_source = (
        repo_root / "src" / "opensquilla" / "gateway" / "channel_inflight.py"
    ).read_text()

    assert "class _ChannelInFlightSet" not in dispatch_source
    assert "def _compute_channel_cap" not in dispatch_source
    assert "class ChannelInFlightSet" in inflight_source
    assert "def compute_channel_cap" in inflight_source
