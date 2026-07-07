"""The committed models.dev snapshot must carry per-Mtok cost keys for major
providers, so the catalog layer of resolve_model_price works out of the box
without waiting on a live OpenRouter fetch or a packaged correction row.
"""

from __future__ import annotations

from opensquilla.provider.models_dev import lookup_model


def test_snapshot_carries_cost_keys_for_major_providers() -> None:
    entry = lookup_model("anthropic", "claude-opus-4-8")
    assert entry is not None and entry.get("in_mtok"), "snapshot missing cost keys — regenerate"


def test_snapshot_deepseek_cache_read_rate_present() -> None:
    entry = lookup_model("deepseek", "deepseek-v4-pro")
    assert entry is not None
    assert 0 < float(entry.get("cr_mtok", 0)) < float(entry.get("in_mtok", 0))
