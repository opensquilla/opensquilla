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
    assert "file-authoring tools" in spec.content
    assert "If none of those file-authoring tools are available" in spec.content
    assert "Do not attempt to generate, save, or modify the `.pptx`" in spec.content
    assert "Ignore the Path B, Path C, and Visual QA sections below" in spec.content
    assert "Do not paste OOXML" in spec.content
    assert "final `.pptx`" in spec.content
