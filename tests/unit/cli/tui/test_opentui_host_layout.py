from __future__ import annotations

from pathlib import Path

HOST_SOURCE = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "opensquilla"
    / "cli"
    / "tui"
    / "opentui"
    / "package"
    / "src"
    / "main.mjs"
)


def test_opentui_host_uses_fullscreen_scrollbox_layout() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert 'screenMode: "alternate-screen"' in source
    assert "ScrollBoxRenderable" in source
    assert 'stickyStart: "bottom"' in source
    assert "viewportCulling" in source
    assert 'id: "composer-box"' in source
    assert 'id: "router-plugin"' in source
    assert 'screenMode: "split-footer"' not in source
    assert "writeToScrollback" not in source


def test_opentui_host_locks_recommended_daily_visual_preset() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "OPENTUI_DAILY_THEME" in source
    assert 'preset: "daily"' in source
    assert 'frameStyle: "card"' in source
    assert 'frame: "#5a6b7a"' in source
    assert "#77B7FF" in source
    assert "class TurnView" in source
    assert "conversationBox.add" in source
    assert "TextRenderable(renderer" in source
    assert "`sb-${scrollbackSeq++}`" in source
    assert "STATUS_PULSE_FRAMES" in source


def test_opentui_host_has_turnview_with_inplace_tool_nodes() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "class TurnView" in source
    assert "addTool" in source
    assert "finishTool" in source
    assert "appendAnswer" in source
    assert "setUsage" in source
    assert "STATUS_PULSE_FRAMES" in source
    assert "✓" in source and "✗" in source


def test_opentui_host_draws_continuous_tool_timeline_rail() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    set_prompt_body = source.split("  setPrompt(text) {", 1)[1].split(
        "  addTool(", 1
    )[0]
    add_tool_body = source.split("  addTool(toolId, name, summary) {", 1)[1].split(
        "  finishTool(", 1
    )[0]
    append_answer_body = source.split("  appendAnswer(delta) {", 1)[1].split(
        "  demoteAnswerToTimeline(", 1
    )[0]
    promote_answer_body = source.split("  promoteAnswerToCard() {", 1)[1].split(
        "  finishAnswer(", 1
    )[0]

    assert "rail-top" not in set_prompt_body
    assert 'const TOOL_INDENT = " ";' in source
    assert "`rail-tool-${toolId}`" in add_tool_body
    assert "`${TOOL_INDENT}│`, OPENTUI_DAILY_THEME.faint" in add_tool_body
    assert add_tool_body.index("rail-tool") < add_tool_body.index("tool-${toolId}")
    assert 'this._line("a-gap", "│", OPENTUI_DAILY_THEME.faint)' not in append_answer_body
    assert 'this._line("a-gap", "│", OPENTUI_DAILY_THEME.faint)' in promote_answer_body


def test_opentui_tool_timeline_is_indented_one_cell() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    add_tool_body = source.split("  addTool(toolId, name, summary) {", 1)[1].split(
        "  finishTool(", 1
    )[0]
    finish_tool_body = source.split("  finishTool(toolId, status, name, summary) {", 1)[
        1
    ].split("  addToolDetail(", 1)[0]
    detail_body = source.split("  addToolDetail(text, toolId = null) {", 1)[1].split(
        "  appendModelText(", 1
    )[0]
    demote_answer_body = source.split("  demoteAnswerToTimeline() {", 1)[1].split(
        "  promoteAnswerToCard(", 1
    )[0]
    refresh_body = source.split("  refreshToolPulse() {", 1)[1].split(
        "}\n\nfunction handlePythonMessage", 1
    )[0]

    assert "`${TOOL_INDENT}│`" in add_tool_body
    assert "`${TOOL_INDENT}${STATUS_PULSE_FRAMES.tool[0]}" in add_tool_body
    assert "`${TOOL_INDENT}${glyph} ${finalName}${tail}`" in finish_tool_body
    assert "`${TOOL_INDENT}│   ${line}`" in detail_body
    assert "`${TOOL_INDENT}│   … ${lines.length - max} more lines`" in detail_body
    assert "`${TOOL_INDENT}│`, OPENTUI_DAILY_THEME.faint" in demote_answer_body
    assert "`${TOOL_INDENT}✱ ${line}`" in demote_answer_body
    assert "`${TOOL_INDENT}  ${line}`" in demote_answer_body
    assert "`${TOOL_INDENT}${glyph} ${node._toolName}${node._toolTail}`" in refresh_body


def test_opentui_host_uses_lines_not_backgrounds_for_visual_separation() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "backgroundColor" not in source
    assert "routerBackground" not in source


def test_opentui_host_removes_regex_timeline_classifier() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "decorateDailyTimelineScrollback" not in source
    assert "classifyDailyTimelineLine" not in source
    assert "colorForDailyScrollback" not in source
    assert "conversationBox" in source


def test_opentui_footer_revives_status_and_composer_and_router_color() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "syncPulseTimer" in source
    assert "setInterval" in source
    assert "composerDisabledBorder" in source
    assert "colorForStyle(routerState.style)" in source
    assert "backgroundColor" not in source


def test_opentui_answer_uses_markdown_renderable() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    assert "MarkdownRenderable" in source
    assert "SyntaxStyle" in source
    assert "streaming" in source
    assert "this.answerBody = new BoxRenderable" in source
    assert 'border: ["left"]' in source
    assert "borderColor: OPENTUI_DAILY_THEME.toolAccent" in source
    assert "this.answerBody.add(this.answerMd)" in source


def test_opentui_promotes_only_final_answer_run_to_card() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")

    add_tool_body = source.split("  addTool(toolId, name, summary) {", 1)[1].split(
        "  finishTool(", 1
    )[0]
    append_answer_body = source.split("  appendAnswer(delta) {", 1)[1].split(
        "  demoteAnswerToTimeline(", 1
    )[0]
    promote_answer_body = source.split("  promoteAnswerToCard() {", 1)[1].split(
        "  finishAnswer(", 1
    )[0]
    finish_answer_body = source.split("  finishAnswer(cancelled) {", 1)[1].split(
        "  setUsage(", 1
    )[0]
    demote_answer_body = source.split("  demoteAnswerToTimeline() {", 1)[1].split(
        "  promoteAnswerToCard(", 1
    )[0]

    assert "this.answerDraft = null;" in source
    assert "new MarkdownRenderable" not in append_answer_body
    assert "OPENTUI_DAILY_THEME.toolAccent" not in append_answer_body
    assert "OPENTUI_DAILY_THEME.modelText" in append_answer_body
    assert "this.box.remove(this.answerDraft.id)" in promote_answer_body
    assert "this.answerBody = new BoxRenderable" in promote_answer_body
    assert 'id: `turn-${this.id}-answer-body`' in promote_answer_body
    assert 'border: ["left"]' in promote_answer_body
    assert "borderColor: OPENTUI_DAILY_THEME.toolAccent" in promote_answer_body
    assert "paddingLeft: 1" in promote_answer_body
    assert "this.answerBody.add(this.answerMd)" in promote_answer_body
    assert "this.box.add(this.answerBody)" in promote_answer_body
    assert "this.box.add(this.answerMd)" not in promote_answer_body
    assert "demoteAnswerToTimeline" in source
    assert "this.demoteAnswerToTimeline();" in add_tool_body
    # Intermediate output is demoted into a ✱-glyphed timeline block (purple),
    # framed by rail gaps, rather than a bare text node.
    assert "✱ " in demote_answer_body
    assert "OPENTUI_DAILY_THEME.modelText" in demote_answer_body
    assert "OPENTUI_DAILY_THEME.faint" in demote_answer_body
    assert "promoteAnswerToCard" in source
    assert "this.promoteAnswerToCard()" in finish_answer_body
    assert finish_answer_body.index("if (cancelled)") < finish_answer_body.index(
        "this.promoteAnswerToCard()"
    )
    assert "this.demoteAnswerToTimeline();" in finish_answer_body
    assert "new MarkdownRenderable" in promote_answer_body
    # The answer card header runs a long rule; the footer stays short (top > bottom).
    assert "╭─ answer ─ squilla ${CARD_RULE_LONG}" in source
    assert "╰${CARD_RULE_SHORT}" in source


def test_opentui_input_region_and_scroll_routing() -> None:
    source = HOST_SOURCE.read_text(encoding="utf-8")
    keypress_body = source.split('renderer.keyInput.on("keypress", (key) => {', 1)[
        1
    ].split('renderer.keyInput.on("paste"', 1)[0]

    assert "inputHistory" in source
    assert "cursorVisible" in source
    assert "scrollBy" in source
    assert 'justifyContent: "flex-start"' in source
    assert 'justifyContent: "center"' not in source
    assert "useMouse: true" in source
    assert "key.option" in keypress_body
    assert 'insertAtCursor("\\n")' in keypress_body
    assert keypress_body.index('insertAtCursor("\\n")') < keypress_body.index("submitInput()")
    assert 'name === "pageup"' in source or 'name === "pagedown"' in source
