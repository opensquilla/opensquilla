"""pptx skill delivery contract."""

from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"


def test_pptx_skill_instructs_artifact_delivery() -> None:
    spec = SkillLoader(bundled_dir=BUNDLED).get_by_name("pptx")

    assert spec is not None
    assert "publish_artifact" in spec.content
    assert "Do not paste OOXML" in spec.content
    assert "final `.pptx`" in spec.content
