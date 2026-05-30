"""Tests for SkillLoader.list_meta_specs() helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.skills.loader import SkillLoader

BUNDLED = Path(__file__).resolve().parents[1].parent / "src" / "opensquilla" / "skills" / "bundled"


@pytest.fixture
def loader(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=snapshot)
    loader.invalidate_cache()
    loader.load_all()
    return loader


def test_list_meta_specs_returns_only_kind_meta(loader: SkillLoader) -> None:
    metas = loader.list_meta_specs()
    assert len(metas) > 0
    assert all(spec.kind == "meta" for spec in metas)


def test_list_meta_specs_includes_compiled_meta_sop(loader: SkillLoader) -> None:
    """meta-paper-write is authored as kind: meta_sop but loader Pass 2 compiles it to kind: meta.
    Post-compile it MUST appear in list_meta_specs — both shapes are valid pattern citations."""
    metas = loader.list_meta_specs()
    names = {s.name for s in metas}
    assert "meta-paper-write" in names


def test_list_meta_specs_includes_known_meta_bundles(loader: SkillLoader) -> None:
    names = {s.name for s in loader.list_meta_specs()}
    assert names == {
        "meta-account-watch",
        "meta-daily-operator-brief",
        "meta-document-to-decision",
        "meta-family-day-coordinator",
        "meta-job-search-pipeline",
        "meta-kid-project-planner",
        "meta-paper-write",
        "meta-safe-skill-installer",
        "meta-skill-creator",
        "meta-web-research-to-report",
    }
