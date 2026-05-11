"""html-to-pdf skill — load + eligibility + render smoke (skipped without weasyprint)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.skills.eligibility import EligibilityContext, check_eligibility
from opensquilla.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
SCRIPTS = BUNDLED / "html-to-pdf" / "scripts"


def _spec() -> object:
    return SkillLoader(bundled_dir=BUNDLED).get_by_name("html-to-pdf")


def test_skill_loads() -> None:
    spec = _spec()
    assert spec is not None
    assert spec.name == "html-to-pdf"


def test_skill_instructs_artifact_delivery() -> None:
    spec = _spec()
    assert spec is not None
    assert "publish_artifact" in spec.content
    assert "Do not paste the full HTML/CSS source" in spec.content


def test_eligibility_with_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "opensquilla.skills.eligibility.shutil.which",
        lambda name: "/usr/bin/python3" if name in {"python", "python3"} else None,
    )
    spec = _spec()
    assert spec is not None
    assert check_eligibility(spec, EligibilityContext.auto())


def test_render_html_to_pdf(tmp_path: Path) -> None:
    pytest.importorskip(
        "weasyprint",
        reason="weasyprint is opt-in via opensquilla[document-extras]; skip when absent",
    )
    sys.path.insert(0, str(SCRIPTS))
    try:
        import render  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    html_path = tmp_path / "doc.html"
    html_path.write_text(
        """<!doctype html><html><head><title>x</title>
        <style>@page { size: Letter; margin: 0.5in; } body { font-family: serif; }</style>
        </head><body><h1>Hello</h1><p>World.</p></body></html>""",
        encoding="utf-8",
    )
    out_path = tmp_path / "out.pdf"
    render.render(str(html_path), out_path, "Letter")
    assert out_path.is_file()
    # Sanity: a non-trivial PDF is at least a few hundred bytes and starts with %PDF.
    blob = out_path.read_bytes()
    assert blob.startswith(b"%PDF")
    assert len(blob) > 500
