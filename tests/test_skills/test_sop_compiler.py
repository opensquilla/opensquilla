"""Unit + integration tests for the SOP→DAG compiler.

The compiler lives at ``src/opensquilla/skills/meta/sop_compiler.py``.
This file mirrors its four stages (lexer / parser / resolver / emitter)
plus integration and acceptance tests.
"""

from __future__ import annotations

from opensquilla.skills.meta.parser import MetaPlanError

# ---------------------------------------------------------------------------
# Stage 0: Foundation types
# ---------------------------------------------------------------------------


def test_source_span_carries_line_and_excerpt() -> None:
    from opensquilla.skills.meta.sop_compiler import SourceSpan

    span = SourceSpan(
        start_line=42,
        start_col=4,
        end_line=42,
        end_col=20,
        excerpt="Run `multi-search-engine`",
    )
    assert span.start_line == 42
    assert "multi-search-engine" in span.excerpt


def test_sop_compile_error_is_meta_plan_error() -> None:
    """SOPCompileError is a MetaPlanError so the loader's existing failure
    path catches it via its current except clause."""
    from opensquilla.skills.meta.sop_compiler import SOPCompileError

    exc = SOPCompileError(
        skill_name="meta-x",
        phase_index=2,
        span=None,
        reason="example",
    )
    assert isinstance(exc, MetaPlanError)
    msg = str(exc)
    assert "meta-x" in msg
    assert "Phase 2" in msg or "phase 2" in msg.lower()
    assert "example" in msg


def test_sop_compile_error_renders_excerpt() -> None:
    from opensquilla.skills.meta.sop_compiler import SOPCompileError, SourceSpan

    span = SourceSpan(
        start_line=10,
        start_col=0,
        end_line=10,
        end_col=30,
        excerpt="- name: introduction",
    )
    exc = SOPCompileError(
        skill_name="meta-y",
        phase_index=5,
        span=span,
        reason="duplicate id",
    )
    msg = str(exc)
    assert "line 10" in msg
    assert "- name: introduction" in msg
