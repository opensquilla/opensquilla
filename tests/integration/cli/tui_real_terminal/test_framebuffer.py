from __future__ import annotations

from dataclasses import replace

import pytest

from tui_real_terminal.framebuffer import (
    APP_BACKGROUND,
    DEFAULT_BACKGROUND,
    FOOTER_BACKGROUND,
    FOOTER_HEIGHT,
    PROMPT_BACKGROUND,
    SCROLLBAR_TRACK_BACKGROUND,
    FramebufferCell,
    FramebufferParseError,
    StyledFramebuffer,
    assert_opentui_framebuffer,
    context_rail_width,
    opentui_framebuffer_violations,
    parse_tmux_styled_framebuffer,
)


def test_styled_parser_preserves_background_state_but_not_unpainted_padding() -> None:
    frame = parse_tmux_styled_framebuffer(
        "\x1b[48;2;18;18;18mAB  \n\x1b[38;2;255;106;40mCD\n",
        checkpoint="styled",
        cols=4,
        rows=2,
        captured_at_ms=1,
    )

    assert [cell.background for cell in frame.cells[0]] == [APP_BACKGROUND] * 4
    # tmux carries SGR between serialized rows. Its omitted tail positions are
    # still empty/default cells, not painted spaces using that carried state.
    assert [cell.background for cell in frame.cells[1]] == [
        APP_BACKGROUND,
        APP_BACKGROUND,
        DEFAULT_BACKGROUND,
        DEFAULT_BACKGROUND,
    ]
    # RGB foreground components such as 106 or 40 must never be mistaken for
    # standalone ANSI background parameters.
    assert frame.cells[1][0].background == APP_BACKGROUND


def test_styled_parser_expands_wide_glyphs_to_display_cells() -> None:
    frame = parse_tmux_styled_framebuffer(
        "\x1b[48:2::18:18:18m中A \n",
        checkpoint="cjk",
        cols=4,
        rows=1,
        captured_at_ms=1,
    )

    assert frame.row_text(0) == "中A "
    assert frame.cells[0][0] == FramebufferCell("中", APP_BACKGROUND)
    assert frame.cells[0][1] == FramebufferCell("", APP_BACKGROUND, continuation=True)
    assert [cell.background for cell in frame.cells[0]] == [APP_BACKGROUND] * 4


@pytest.mark.parametrize(
    ("raw", "cols", "rows", "message"),
    [
        ("one row\n", 8, 2, "has 1 rows"),
        ("five!\n", 4, 1, "exceeds 4 display cells"),
        ("\x1b[2Jbad\n", 8, 1, "unsupported escape sequence"),
    ],
)
def test_styled_parser_rejects_non_exact_framebuffers(
    raw: str,
    cols: int,
    rows: int,
    message: str,
) -> None:
    with pytest.raises(FramebufferParseError, match=message):
        parse_tmux_styled_framebuffer(
            raw,
            checkpoint="invalid",
            cols=cols,
            rows=rows,
            captured_at_ms=1,
        )


@pytest.mark.parametrize("cols,rows", [(72, 24), (120, 34), (132, 34), (160, 40)])
def test_canonical_framebuffer_passes_background_and_fixed_chrome_gate(
    cols: int,
    rows: int,
) -> None:
    assert_opentui_framebuffer(_canonical_frame(cols, rows))


def test_default_background_hole_is_a_blocking_violation() -> None:
    frame = _replace_cell(
        _canonical_frame(120, 34),
        row=5,
        col=20,
        background=DEFAULT_BACKGROUND,
    )

    violations = opentui_framebuffer_violations(frame)

    assert any("background-mask" in violation for violation in violations)


def test_footer_background_staircase_in_transcript_is_a_blocking_violation() -> None:
    frame = _canonical_frame(120, 34)
    for row in range(4, 10):
        for col in range(12 + row, 22 + row):
            frame = _replace_cell(
                frame,
                row=row,
                col=col,
                background=FOOTER_BACKGROUND,
            )

    violations = opentui_framebuffer_violations(frame)

    assert any("background-mask: 60 mismatched cells" in violation for violation in violations)


def test_exact_semantic_prompt_surface_is_allowed_in_transcript() -> None:
    frame = _canonical_frame(120, 34)
    for row in (5, 6):
        for col in range(1, 119):
            frame = _replace_cell(
                frame,
                row=row,
                col=col,
                background=PROMPT_BACKGROUND,
            )
    frame = _write_text(frame, row=5, col=1, text="│ you  explain this")
    frame = _write_text(frame, row=6, col=1, text="│      second line")

    assert not opentui_framebuffer_violations(frame)


def test_exact_prompt_surface_accounts_for_active_scrollbar_gutter() -> None:
    frame = _canonical_frame(72, 24)
    for row in range(2, 24 - FOOTER_HEIGHT):
        frame = _replace_cell(
            frame,
            row=row,
            col=71,
            background=SCROLLBAR_TRACK_BACKGROUND,
        )
    for col in range(1, 70):
        frame = _replace_cell(
            frame,
            row=5,
            col=col,
            background=PROMPT_BACKGROUND,
        )
    frame = _write_text(frame, row=5, col=1, text="│ you  scrollable prompt")

    assert not opentui_framebuffer_violations(frame)


def test_surface_rectangle_without_prompt_role_is_a_blocking_violation() -> None:
    frame = _canonical_frame(120, 34)
    for col in range(1, 119):
        frame = _replace_cell(
            frame,
            row=5,
            col=col,
            background=PROMPT_BACKGROUND,
        )
    frame = _write_text(frame, row=5, col=1, text="│ stale surface")

    violations = opentui_framebuffer_violations(frame)

    assert any("background-mask: 118 mismatched cells" in violation for violation in violations)


def test_incomplete_prompt_surface_is_a_blocking_violation() -> None:
    frame = _canonical_frame(120, 34)
    for col in range(1, 118):
        frame = _replace_cell(
            frame,
            row=5,
            col=col,
            background=PROMPT_BACKGROUND,
        )
    frame = _write_text(frame, row=5, col=1, text="│ you  clipped surface")

    violations = opentui_framebuffer_violations(frame)

    assert any("background-mask: 117 mismatched cells" in violation for violation in violations)


def test_scrollbar_track_color_is_allowed_only_on_transcript_edge() -> None:
    edge = _replace_cell(
        _canonical_frame(72, 24),
        row=5,
        col=71,
        background=SCROLLBAR_TRACK_BACKGROUND,
    )
    residue = _replace_cell(
        edge,
        row=5,
        col=70,
        background=SCROLLBAR_TRACK_BACKGROUND,
    )

    assert not opentui_framebuffer_violations(edge)
    assert any(
        "background-mask" in violation for violation in opentui_framebuffer_violations(residue)
    )


def test_duplicate_composer_residue_is_a_blocking_violation() -> None:
    frame = _write_text(_canonical_frame(120, 34), row=10, col=6, text="send a message")

    violations = opentui_framebuffer_violations(frame)

    assert any("composer-placeholder" in violation for violation in violations)


def test_border_only_duplicate_composer_residue_is_a_blocking_violation() -> None:
    frame = _write_text(
        _canonical_frame(120, 34),
        row=34 - FOOTER_HEIGHT,
        col=20,
        text="╭────────────╮",
    )

    violations = opentui_framebuffer_violations(frame)

    assert any(
        "composer-border" in violation and "duplicate/residual" in violation
        for violation in violations
    )


def test_duplicate_context_rail_is_a_blocking_violation() -> None:
    frame = _canonical_frame(132, 34)
    for row in range(frame.rows):
        frame = _replace_cell(frame, row=row, col=80, glyph="│")

    violations = opentui_framebuffer_violations(frame)

    assert any("context-rail" in violation and "80" in violation for violation in violations)


def test_block_logo_overflow_into_context_rail_is_a_blocking_violation() -> None:
    frame = _canonical_frame(132, 34)
    content = frame.cols - context_rail_width(frame.cols)
    frame = _replace_cell(frame, row=4, col=content + 5, glyph="█")

    violations = opentui_framebuffer_violations(frame)

    assert any("block logo overflowed" in violation for violation in violations)


def test_wrapped_partial_context_headings_are_a_blocking_violation() -> None:
    frame = _canonical_frame(72, 24)
    frame = _write_text(frame, row=1, col=0, text="GENT")
    frame = _write_text(frame, row=5, col=0, text="AFETY")
    frame = _write_text(frame, row=8, col=0, text="OUTING")

    violations = opentui_framebuffer_violations(frame)

    assert any("wrapped heading fragments" in violation for violation in violations)


def _canonical_frame(cols: int, rows: int) -> StyledFramebuffer:
    rail = context_rail_width(cols)
    content = cols - rail
    footer_top = rows - FOOTER_HEIGHT
    cells: list[list[FramebufferCell]] = []
    for row in range(rows):
        cells.append(
            [
                FramebufferCell(
                    " ",
                    FOOTER_BACKGROUND if row >= footer_top and col < content else APP_BACKGROUND,
                )
                for col in range(cols)
            ]
        )

    if rail:
        for row in range(rows):
            cells[row][content] = replace(cells[row][content], glyph="│")
        _write_mutable(cells, row=0, col=content + 2, text="AGENT")
        _write_mutable(cells, row=6, col=content + 2, text="RUNTIME")

    footer_strip = "direct · model fake-terminal"
    _write_mutable(cells, row=footer_top, col=3, text=footer_strip)
    for col in range(1, content - 1):
        cells[footer_top + 1][col] = replace(
            cells[footer_top + 1][col],
            glyph="╭" if col == 1 else "╮" if col == content - 2 else "─",
        )
        cells[rows - 1][col] = replace(
            cells[rows - 1][col],
            glyph="╰" if col == 1 else "╯" if col == content - 2 else "─",
        )
    for row in range(footer_top + 2, rows - 1):
        cells[row][1] = replace(cells[row][1], glyph="│")
        cells[row][content - 2] = replace(cells[row][content - 2], glyph="│")
    _write_mutable(cells, row=footer_top + 2, col=4, text="send a message")

    return StyledFramebuffer(
        checkpoint=f"canonical-{cols}x{rows}",
        raw="",
        captured_at_ms=1,
        cols=cols,
        rows=rows,
        cells=tuple(tuple(row) for row in cells),
    )


def _replace_cell(
    frame: StyledFramebuffer,
    *,
    row: int,
    col: int,
    glyph: str | None = None,
    background: str | None = None,
) -> StyledFramebuffer:
    cells = [list(line) for line in frame.cells]
    original = cells[row][col]
    cells[row][col] = FramebufferCell(
        original.glyph if glyph is None else glyph,
        original.background if background is None else background,
        original.continuation,
    )
    return replace(frame, cells=tuple(tuple(line) for line in cells))


def _write_text(
    frame: StyledFramebuffer,
    *,
    row: int,
    col: int,
    text: str,
) -> StyledFramebuffer:
    cells = [list(line) for line in frame.cells]
    _write_mutable(cells, row=row, col=col, text=text)
    return replace(frame, cells=tuple(tuple(line) for line in cells))


def _write_mutable(
    cells: list[list[FramebufferCell]],
    *,
    row: int,
    col: int,
    text: str,
) -> None:
    for offset, glyph in enumerate(text):
        cells[row][col + offset] = replace(cells[row][col + offset], glyph=glyph)
