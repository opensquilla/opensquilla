"""render_clarify_summary unit tests (PR3 helper, design §5.3 / §8.3)."""

from __future__ import annotations

from opensquilla.skills.meta.clarify_summary import render_clarify_summary
from opensquilla.skills.meta.types import ClarifyField, ClarifyStepConfig


def _cfg(*fields: ClarifyField, intro: str = "") -> ClarifyStepConfig:
    return ClarifyStepConfig(mode="form", fields=tuple(fields), intro=intro)


def test_renders_intro_then_bullets():
    cfg = _cfg(
        ClarifyField(name="destination", type="string", required=True),
        ClarifyField(
            name="budget", type="enum", choices=("budget", "mid"), default="mid"
        ),
        intro="Trip info needed.",
    )
    out = render_clarify_summary(schema=cfg, filled={"destination": "Tokyo"})
    assert "Trip info needed." in out
    assert "destination: Tokyo (from user)" in out
    assert "budget: mid (default)" in out


def test_renders_without_intro():
    cfg = _cfg(ClarifyField(name="x", type="string", required=True))
    out = render_clarify_summary(schema=cfg, filled={"x": "v"})
    assert out.startswith("- ") or out.startswith("• ")


def test_handles_missing_required_field_as_pending():
    """A required field that is missing from `filled` is rendered as
    `(pending)` rather than crashing."""
    cfg = _cfg(ClarifyField(name="x", type="string", required=True))
    out = render_clarify_summary(schema=cfg, filled={})
    assert "x: (pending)" in out


def test_output_stays_under_1kb():
    cfg = _cfg(
        *[
            ClarifyField(name=f"f{i}", type="string", required=True, prompt="p")
            for i in range(12)
        ]
    )
    filled = {f"f{i}": "x" * 50 for i in range(12)}
    out = render_clarify_summary(schema=cfg, filled=filled)
    assert len(out.encode("utf-8")) < 1024


def test_renders_with_intro_then_blank_then_bullets():
    cfg = _cfg(
        ClarifyField(name="x", type="string", required=True),
        intro="hello",
    )
    out = render_clarify_summary(schema=cfg, filled={"x": "y"})
    lines = out.splitlines()
    assert lines[0] == "hello"
    assert lines[1] == ""
    assert lines[2].startswith("- ") or lines[2].startswith("• ")
