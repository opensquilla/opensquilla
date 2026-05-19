"""SOP→DAG compiler — translates ``kind: meta_sop`` SKILL.md into the
standard ``composition.steps`` YAML before the parser sees it.

Four stages:

1. :func:`_lex` — line-based scanner producing tokens with ``SourceSpan``.
2. :func:`_parse` — token stream → ``SOPDocument`` AST.
3. :func:`_resolve` — skill lookup + kind inference per invocation.
4. :func:`_emit` — AST → ``composition_raw`` dict.

Public surface:

* :func:`compile` — driver that runs all four stages and returns a fresh
  ``SkillSpec(kind="meta", composition_raw=..., sop_source=...)``.
* :class:`SOPCompileError` — parse-time error, subclass of
  :class:`MetaPlanError` so the loader's existing error path catches it.
* :class:`SourceSpan` — line/column/excerpt for error reporting; carried
  on every AST node.
"""

from __future__ import annotations

from dataclasses import dataclass

from opensquilla.skills.meta.parser import MetaPlanError


@dataclass(frozen=True)
class SourceSpan:
    """Source location for an AST node or error pointer.

    Lines and columns are 1-indexed (matches editor display conventions).
    ``excerpt`` is the literal source text the span covers; truncated to
    ~80 chars when stored. Carried on every node so errors render as
    ``Phase N (line K): <reason>\\n> <excerpt>``.
    """

    start_line: int
    start_col: int
    end_line: int
    end_col: int
    excerpt: str


class SOPCompileError(MetaPlanError):
    """Compile-time SOP parse/resolve/emit failure.

    Subclasses :class:`MetaPlanError` so the loader's existing
    ``except MetaPlanError`` path catches us. Carries structured fields
    (skill_name, phase_index, span, reason) so callers can render rich
    diagnostics; ``str(exc)`` produces a human-readable one-block format.
    """

    def __init__(
        self,
        *,
        skill_name: str,
        phase_index: int | None,
        span: SourceSpan | None,
        reason: str,
    ) -> None:
        self.skill_name = skill_name
        self.phase_index = phase_index
        self.span = span
        self.reason = reason
        super().__init__(self._render())

    def _render(self) -> str:
        parts: list[str] = [self.skill_name]
        if self.phase_index is not None:
            parts.append(f"Phase {self.phase_index}")
        if self.span is not None:
            parts.append(f"line {self.span.start_line}")
        head = ":".join(parts) + ": " + self.reason
        if self.span is not None and self.span.excerpt:
            return head + "\n> " + self.span.excerpt
        return head
