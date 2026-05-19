"""Unit + integration tests for the SOP→DAG compiler.

The compiler lives at ``src/opensquilla/skills/meta/sop_compiler.py``.
This file mirrors its four stages (lexer / parser / resolver / emitter)
plus integration and acceptance tests.
"""

from __future__ import annotations

from typing import Any

import pytest

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


# ---------------------------------------------------------------------------
# Stage 2: Parser
# ---------------------------------------------------------------------------


def test_parse_single_sequential_phase() -> None:
    from opensquilla.skills.meta.sop_compiler import _lex, _parse

    body = (
        "## Phase 1: Search\n"
        "Run `multi-search-engine`. Save as `s`.\n"
    )
    doc = _parse(list(_lex(body)), skill_name="meta-x")
    assert len(doc.phases) == 1
    phase = doc.phases[0]
    assert phase.index == 1
    assert phase.title == "Search"
    assert phase.annotations == {}
    assert len(phase.invocations) == 1
    inv = phase.invocations[0]
    assert inv.skill_name == "multi-search-engine"
    assert inv.kind_hint is None
    assert inv.step_id_template == "s"
    assert inv.with_args == {}


def test_parse_invoke_with_kind_and_args() -> None:
    from opensquilla.skills.meta.sop_compiler import _lex, _parse

    body = (
        "## Phase 1: Outline\n"
        "Invoke `paper-outline-author` as agent with:\n"
        "- topic: `{{ inputs.user_message }}`\n"
        "- max_words: 200\n"
        "Save as `outline`.\n"
    )
    doc = _parse(list(_lex(body)), skill_name="meta-x")
    inv = doc.phases[0].invocations[0]
    assert inv.skill_name == "paper-outline-author"
    assert inv.kind_hint == "agent"
    assert inv.with_args["topic"] == "`{{ inputs.user_message }}`"
    assert inv.with_args["max_words"] == "200"


def test_parse_parallel_annotation() -> None:
    from opensquilla.skills.meta.sop_compiler import _lex, _parse

    body = (
        "## Phase 1: First\n"
        "Run `a`. Save as `s1`.\n"
        "## Phase 2: Foundation [parallel]\n"
        "Run `b`. Save as `s2`.\n"
        "Run `c`. Save as `s3`.\n"
    )
    doc = _parse(list(_lex(body)), skill_name="meta-x")
    p2 = doc.phases[1]
    assert "parallel" in p2.annotations
    assert len(p2.invocations) == 2


def test_parse_for_each_annotation_with_items() -> None:
    from opensquilla.skills.meta.sop_compiler import _lex, _parse

    body = (
        "## Phase 5: Drafting [parallel for_each: section]\n"
        "```yaml for_each\n"
        "section:\n"
        "  - {id: a, name: A}\n"
        "  - {id: b, name: B, extra: X}\n"
        "```\n"
        "Invoke `paper-section-author` with:\n"
        "- section: `{{ section.name }}`\n"
        "Save as `{{ section.id }}`.\n"
    )
    doc = _parse(list(_lex(body)), skill_name="meta-x")
    p = doc.phases[0]
    assert p.annotations.get("parallel for_each") == "section"
    assert p.for_each_var == "section"
    assert len(p.for_each_items) == 2
    assert p.for_each_items[0] == {"id": "a", "name": "A"}
    assert p.for_each_items[1] == {"id": "b", "name": "B", "extra": "X"}


def test_parse_depends_on_annotation_single() -> None:
    from opensquilla.skills.meta.sop_compiler import _lex, _parse

    body = (
        "## Phase 1: A\n"
        "Run `s`. Save as `a`.\n"
        "## Phase 2: B [depends_on: a]\n"
        "Run `s`. Save as `b`.\n"
    )
    doc = _parse(list(_lex(body)), skill_name="meta-x")
    p2 = doc.phases[1]
    assert p2.annotations.get("depends_on") == "a"


def test_parse_when_annotation_rejected() -> None:
    from opensquilla.skills.meta.sop_compiler import SOPCompileError, _lex, _parse

    body = (
        "## Phase 1: A [when: outputs.x == 'yes']\n"
        "Run `s`. Save as `a`.\n"
    )
    with pytest.raises(SOPCompileError, match="not in MVP scope"):
        _parse(list(_lex(body)), skill_name="meta-x")


def test_parse_missing_save_as_rejected() -> None:
    from opensquilla.skills.meta.sop_compiler import SOPCompileError, _lex, _parse

    body = (
        "## Phase 1: A\n"
        "Run `s`.\n"
        "## Phase 2: B\n"
        "Run `t`. Save as `b`.\n"
    )
    with pytest.raises(SOPCompileError, match="Save as"):
        _parse(list(_lex(body)), skill_name="meta-x")


def test_parse_stdin_prose_rejected() -> None:
    from opensquilla.skills.meta.sop_compiler import SOPCompileError, _lex, _parse

    body = (
        "## Phase 1: Refbib\n"
        "Run `paper-refbib-stub`. Pipe outputs.search to stdin. Save as `r`.\n"
    )
    with pytest.raises(SOPCompileError, match="stdin"):
        _parse(list(_lex(body)), skill_name="meta-x")


# ---------------------------------------------------------------------------
# Stage 3: Resolver
# ---------------------------------------------------------------------------


class _StubSkillLoader:
    """Minimal SkillLoader stub for resolver tests.

    Real SkillLoader is heavy; resolver only needs ``get_by_name``.
    """

    def __init__(self, specs: dict[str, dict[str, Any]]) -> None:
        self._specs = specs

    def get_by_name(self, name: str) -> Any:
        spec = self._specs.get(name)
        if spec is None:
            return None
        from opensquilla.skills.types import SkillLayer, SkillSpec

        return SkillSpec(
            name=name,
            description=f"{name} description",
            layer=SkillLayer.BUNDLED,
            always=False,
            triggers=[],
            content="",
            kind="skill",
            entrypoint=spec.get("entrypoint"),
        )


def test_resolve_kind_skill_exec_when_skill_has_entrypoint() -> None:
    from opensquilla.skills.meta.sop_compiler import (
        SOPInvocation,
        SourceSpan,
        _resolve_kind,
    )

    inv = SOPInvocation(
        skill_name="multi-search-engine",
        kind_hint=None,
        with_args={},
        step_id_template="s",
        span=SourceSpan(1, 0, 1, 10, ""),
    )
    loader = _StubSkillLoader({"multi-search-engine": {"entrypoint": {"command": "x"}}})
    result = _resolve_kind(inv, skill_loader=loader, skill_name="meta-x", phase_index=1)
    assert result == "skill_exec"


def test_resolve_kind_agent_when_no_entrypoint() -> None:
    from opensquilla.skills.meta.sop_compiler import (
        SOPInvocation,
        SourceSpan,
        _resolve_kind,
    )

    inv = SOPInvocation(
        skill_name="paper-outline-author",
        kind_hint=None,
        with_args={},
        step_id_template="o",
        span=SourceSpan(1, 0, 1, 10, ""),
    )
    loader = _StubSkillLoader({"paper-outline-author": {}})
    assert _resolve_kind(inv, skill_loader=loader, skill_name="meta-x", phase_index=1) == "agent"


def test_resolve_kind_explicit_as_agent_overrides_entrypoint() -> None:
    from opensquilla.skills.meta.sop_compiler import (
        SOPInvocation,
        SourceSpan,
        _resolve_kind,
    )

    inv = SOPInvocation(
        skill_name="multi-search-engine",
        kind_hint="agent",  # explicit override
        with_args={},
        step_id_template="s",
        span=SourceSpan(1, 0, 1, 10, ""),
    )
    loader = _StubSkillLoader({"multi-search-engine": {"entrypoint": {"command": "x"}}})
    assert _resolve_kind(inv, skill_loader=loader, skill_name="meta-x", phase_index=1) == "agent"


def test_resolve_kind_unknown_skill_raises() -> None:
    from opensquilla.skills.meta.sop_compiler import (
        SOPCompileError,
        SOPInvocation,
        SourceSpan,
        _resolve_kind,
    )

    inv = SOPInvocation(
        skill_name="nonexistent-skill",
        kind_hint=None,
        with_args={},
        step_id_template="x",
        span=SourceSpan(5, 0, 5, 30, "Run `nonexistent-skill`. Save as `x`."),
    )
    loader = _StubSkillLoader({})
    with pytest.raises(SOPCompileError, match="not registered"):
        _resolve_kind(inv, skill_loader=loader, skill_name="meta-x", phase_index=1)
