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

import enum
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

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


class TokenType(enum.Enum):
    """Tokens emitted by :func:`_lex`."""

    FRONTMATTER_END = "frontmatter_end"
    PHASE_HEADING = "phase_heading"
    FENCED_YAML_FOR_EACH = "fenced_yaml_for_each"
    INVOCATION_LINE = "invocation_line"  # Run/Invoke/Call tool/Classify
    WITH_BULLET = "with_bullet"
    SAVE_AS_LINE = "save_as_line"
    BLANK = "blank"
    TEXT = "text"  # any other body line


@dataclass(frozen=True)
class Token:
    type: TokenType
    span: SourceSpan
    payload: dict[str, str] = field(default_factory=dict)


_PHASE_HEADING_RE = re.compile(
    r"^##\s+Phase\s+(?P<num>\d+)\s*:\s*(?P<title>[^\[]+?)\s*(?:\[(?P<annotations>[^\]]*)\])?\s*$",
)
_INVOCATION_RUN_RE = re.compile(r"^(?P<verb>Run|Invoke|Call tool|Classify)\s+")
_WITH_BULLET_RE = re.compile(r"^-\s+(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.+)$")
_SAVE_AS_RE = re.compile(r"^Save\s+as\s+`(?P<id>[^`]+)`\s*\.?\s*$")
_FENCE_START_RE = re.compile(r"^```(?P<lang>[A-Za-z_][A-Za-z0-9_ ]*)?\s*$")
_FOR_EACH_FENCE_HINT = "yaml for_each"


def _lex(body: str) -> Iterator[Token]:
    """Tokenize a SOP body line by line.

    Frontmatter is NOT handled here — the loader strips it before calling
    :func:`compile`. The body input is the markdown after the closing
    ``---``.

    Lexer skips the contents of generic fenced code blocks (\\`\\`\\` ...) so
    that markdown documentation code blocks don't confuse the parser.
    The single exception is fenced blocks tagged ``yaml for_each``: these
    are captured wholesale as a single ``FENCED_YAML_FOR_EACH`` token so
    the parser can ``yaml.safe_load`` the contents.
    """

    lines = body.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line_no = i + 1
        stripped = raw.strip()

        # Fenced code block detection
        fence_match = _FENCE_START_RE.match(raw)
        if fence_match:
            lang = (fence_match.group("lang") or "").strip()
            # Find the closing fence (a bare ```)
            j = i + 1
            while j < len(lines) and lines[j].strip() != "```":
                j += 1
            fence_lines = lines[i + 1 : j]
            if lang == _FOR_EACH_FENCE_HINT:
                yield Token(
                    type=TokenType.FENCED_YAML_FOR_EACH,
                    span=SourceSpan(
                        start_line=line_no + 1,  # first line inside fence
                        start_col=0,
                        end_line=j,
                        end_col=0,
                        excerpt="\n".join(fence_lines),
                    ),
                )
            # else: silently skip docs code blocks
            i = j + 1
            continue

        if not stripped:
            yield Token(
                type=TokenType.BLANK,
                span=SourceSpan(
                    start_line=line_no,
                    start_col=0,
                    end_line=line_no,
                    end_col=0,
                    excerpt="",
                ),
            )
            i += 1
            continue

        m = _PHASE_HEADING_RE.match(raw)
        if m:
            payload = {
                "num": m.group("num"),
                "title": m.group("title").strip(),
                "annotations": (m.group("annotations") or "").strip(),
            }
            yield Token(
                type=TokenType.PHASE_HEADING,
                span=SourceSpan(
                    start_line=line_no,
                    start_col=0,
                    end_line=line_no,
                    end_col=len(raw),
                    excerpt=raw[:120],
                ),
                payload=payload,
            )
            i += 1
            continue

        if _INVOCATION_RUN_RE.match(stripped):
            yield Token(
                type=TokenType.INVOCATION_LINE,
                span=SourceSpan(
                    start_line=line_no,
                    start_col=0,
                    end_line=line_no,
                    end_col=len(raw),
                    excerpt=raw[:120],
                ),
            )
            i += 1
            continue

        if _SAVE_AS_RE.match(stripped):
            m_save = _SAVE_AS_RE.match(stripped)
            assert m_save is not None
            yield Token(
                type=TokenType.SAVE_AS_LINE,
                span=SourceSpan(
                    start_line=line_no,
                    start_col=0,
                    end_line=line_no,
                    end_col=len(raw),
                    excerpt=raw[:120],
                ),
                payload={"id": m_save.group("id")},
            )
            i += 1
            continue

        wm = _WITH_BULLET_RE.match(stripped)
        if wm:
            yield Token(
                type=TokenType.WITH_BULLET,
                span=SourceSpan(
                    start_line=line_no,
                    start_col=0,
                    end_line=line_no,
                    end_col=len(raw),
                    excerpt=raw[:120],
                ),
                payload={"key": wm.group("key"), "value": wm.group("value").strip()},
            )
            i += 1
            continue

        yield Token(
            type=TokenType.TEXT,
            span=SourceSpan(
                start_line=line_no,
                start_col=0,
                end_line=line_no,
                end_col=len(raw),
                excerpt=raw[:120],
            ),
        )
        i += 1
