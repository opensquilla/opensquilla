"""Bundled swe-bench skill: manifest parses and declares its requirements."""

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


def test_swebench_skill_loads(loader: SkillLoader) -> None:
    spec = loader.get_by_name("swe-bench")
    assert spec is not None, "bundled swe-bench skill must load"
    assert spec.layer.value == "bundled"
    assert "SWE-bench" in spec.description


def test_swebench_skill_declares_requirements(loader: SkillLoader) -> None:
    spec = loader.get_by_name("swe-bench")
    assert spec is not None
    meta = spec.metadata
    assert meta is not None
    assert meta.requires is not None
    assert "OPENROUTER_API_KEY" in meta.requires.env
    assert any("swebench" in i.package for i in meta.install)


def test_swebench_skill_does_not_hard_gate_on_docker(loader: SkillLoader) -> None:
    # Docker must NOT be a hard eligibility gate: the skill stays visible to
    # the agent so it can guide the user to install Docker instead of the
    # capability silently disappearing.
    spec = loader.get_by_name("swe-bench")
    assert spec is not None
    assert "docker" not in spec.metadata.requires.bins
    # ...but Docker is still documented as a prerequisite.
    assert "Docker" in spec.content


def test_swebench_skill_body_documents_the_cli(loader: SkillLoader) -> None:
    spec = loader.get_by_name("swe-bench")
    assert spec is not None
    assert "opensquilla swebench solve" in spec.content
    assert "--json" in spec.content
