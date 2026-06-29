"""V4 Phase 3 router must degrade loudly, not silently.

Regression for the ML300 incident where missing ML dependencies routed
every turn to the default tier with only per-turn debug metadata as
evidence.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from opensquilla.squilla_router.v4_phase3 import V4Phase3Strategy


def _make_unavailable_classifier(tmp_path):
    # Empty bundle dir → _validate_bundle fails → unavailable (no raise
    # because require_router_runtime defaults to False).
    return V4Phase3Strategy(bundle_dir=tmp_path / "missing-bundle")


def test_unavailable_classifier_reports_source(tmp_path):
    clf = _make_unavailable_classifier(tmp_path)
    tier, confidence, source, meta = asyncio.run(
        clf.classify("hello", valid_tiers=["c1", "c2"])
    )
    assert source == "v4_unavailable"
    assert confidence == 0.0


def test_degradation_warns_once(tmp_path):
    clf = _make_unavailable_classifier(tmp_path)
    assert clf._degraded_warned is False
    asyncio.run(clf.classify("first", valid_tiers=["c1"]))
    assert clf._degraded_warned is True
    # Second call must not reset or re-warn; flag stays set.
    asyncio.run(clf.classify("second", valid_tiers=["c1"]))
    assert clf._degraded_warned is True


def test_require_router_runtime_fails_fast(tmp_path):
    with pytest.raises(RuntimeError):
        V4Phase3Strategy(
            bundle_dir=tmp_path / "missing-bundle",
            require_router_runtime=True,
        )


def test_require_router_runtime_reports_lfs_pointer_assets(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "runtime_src").mkdir(parents=True)
    (bundle / "router.runtime.yaml").write_text("v4: {}\n", encoding="utf-8")

    pointer = b"version https://git-lfs.github.com/spec/v1\n"
    asset = bundle / "features" / "tfidf.pkl"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(pointer)
    (bundle / "artifact_manifest.json").write_text(
        json.dumps({"files": [{"path": "features/tfidf.pkl", "size_bytes": len(pointer)}]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Git LFS pointer"):
        V4Phase3Strategy(bundle_dir=bundle, require_router_runtime=True)
