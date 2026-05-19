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


# ---------------------------------------------------------------------------
# Stage 1: Lexer
# ---------------------------------------------------------------------------


def test_lex_recognizes_phase_heading() -> None:
    from opensquilla.skills.meta.sop_compiler import TokenType, _lex

    body = "## Phase 1: Search\n\nRun `multi-search-engine`. Save as `s`.\n"
    tokens = list(_lex(body))
    types = [t.type for t in tokens]
    assert TokenType.PHASE_HEADING in types
    heading = next(t for t in tokens if t.type == TokenType.PHASE_HEADING)
    assert heading.span.start_line == 1
    assert "Search" in heading.span.excerpt


def test_lex_recognizes_phase_heading_with_annotations() -> None:
    from opensquilla.skills.meta.sop_compiler import TokenType, _lex

    body = "## Phase 3: Drafting [parallel for_each: section]\n"
    tokens = list(_lex(body))
    heading = next(t for t in tokens if t.type == TokenType.PHASE_HEADING)
    # The lexer captures the full heading text; the parser splits title/annotations.
    assert "parallel for_each" in heading.span.excerpt


def test_lex_recognizes_invocation_and_with_bullets() -> None:
    from opensquilla.skills.meta.sop_compiler import TokenType, _lex

    body = (
        "## Phase 1: Search\n"
        "Invoke `paper-outline-author` with:\n"
        "- topic: `hello`\n"
        "- outline_format: markdown\n"
        "Save as `outline`.\n"
    )
    tokens = list(_lex(body))
    types = [t.type for t in tokens]
    assert TokenType.INVOCATION_LINE in types
    assert types.count(TokenType.WITH_BULLET) == 2
    assert TokenType.SAVE_AS_LINE in types


def test_lex_skips_fenced_code_blocks_except_for_each() -> None:
    from opensquilla.skills.meta.sop_compiler import TokenType, _lex

    body = (
        "## Phase 1: Search\n"
        "```python\n"
        "# This is just docs, ignore me\n"
        "## Phase 99: Not a heading\n"
        "```\n"
        "Run `s`. Save as `x`.\n"
    )
    tokens = list(_lex(body))
    # The fake "Phase 99" inside the python fence must NOT be a token
    phase_count = sum(1 for t in tokens if t.type == TokenType.PHASE_HEADING)
    assert phase_count == 1


def test_lex_captures_fenced_for_each_yaml() -> None:
    from opensquilla.skills.meta.sop_compiler import TokenType, _lex

    body = (
        "## Phase 5: Drafting [parallel for_each: section]\n"
        "```yaml for_each\n"
        "section:\n"
        "  - {id: a, name: A}\n"
        "  - {id: b, name: B}\n"
        "```\n"
        "Invoke `x` with:\n"
        "- y: z\n"
        "Save as `{{ section.id }}`.\n"
    )
    tokens = list(_lex(body))
    types = [t.type for t in tokens]
    assert TokenType.FENCED_YAML_FOR_EACH in types
    fey = next(t for t in tokens if t.type == TokenType.FENCED_YAML_FOR_EACH)
    # The whole inner YAML is preserved in the excerpt for the parser to load
    assert "section:" in fey.span.excerpt
    assert "id: a" in fey.span.excerpt


def test_lex_returns_source_spans_with_correct_line_numbers() -> None:
    from opensquilla.skills.meta.sop_compiler import TokenType, _lex

    body = (
        "Hello\n"               # line 1
        "\n"                     # line 2 (blank)
        "## Phase 1: Search\n"   # line 3
        "Run `s`. Save as `x`.\n"  # line 4
    )
    tokens = list(_lex(body))
    heading = next(t for t in tokens if t.type == TokenType.PHASE_HEADING)
    assert heading.span.start_line == 3
    invocation = next(t for t in tokens if t.type == TokenType.INVOCATION_LINE)
    assert invocation.span.start_line == 4
