from __future__ import annotations

import json
import subprocess
from pathlib import Path

SRC = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "opensquilla"
    / "cli"
    / "tui"
    / "opentui"
    / "package"
    / "src"
)


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _node_json(script: str) -> object:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        cwd=Path(__file__).resolve().parents[4],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_host_split_into_block_modules() -> None:
    for f in [
        "theme.mjs",
        "primitives.mjs",
        "blockRegistry.mjs",
        "turnView.mjs",
        "composer.mjs",
        "ipc.mjs",
        "blocks/promptBlock.mjs",
        "blocks/thinkingBlock.mjs",
        "blocks/toolBlock.mjs",
        "blocks/answerBlock.mjs",
        "blocks/usageBlock.mjs",
        "blocks/errorBlock.mjs",
        "main.mjs",
    ]:
        assert (SRC / f).exists(), f"missing host module {f}"


def test_registry_covers_seven_kinds() -> None:
    reg = _read("blockRegistry.mjs")
    for kind in ["prompt", "thinking", "reasoning", "tool", "answer", "usage", "error"]:
        assert f"{kind}:" in reg, f"registry missing kind {kind}"
    assert "createBlock" in reg


def test_turn_card_owns_one_continuous_gutter() -> None:
    # The assistant turn renders as ONE card: a single left-border gutter runs
    # unbroken through narration + tool calls, so the timeline reads as one
    # assistant block (opencode/codex style). That gutter is the turn card's
    # border (answerFrame) owned by turnView — in-card blocks no longer redraw
    # their own "│" rail nodes. The chrome is width-independent: a short
    # "╭ squilla" label on top and a bare "╰ …" footer, never a full-width rule
    # (which wraps a stray dash when the scrollbar steals a viewport column).
    tv = _read("turnView.mjs")
    tool = _read("blocks/toolBlock.mjs")
    thinking = _read("blocks/thinkingBlock.mjs")
    assert 'border: ["left"]' in tv
    assert "borderColor: THEME.answerFrame" in tv
    assert '"╭ squilla"' in tv
    assert "╰" in tv
    assert "cardHeaderRule" not in tv
    # the card opens once and closes once per turn (header + footer drawn once)
    assert "openCard" in tv and "closeCard" in tv
    # in-card blocks defer the gutter to the turn card — no per-block rail node
    assert "-rail" not in tool
    assert "-gt" not in thinking


def test_answer_block_is_streaming_markdown_in_the_turn_card() -> None:
    answer = _read("blocks/answerBlock.mjs")
    assert "MarkdownRenderable" in answer
    assert "streaming: true" in answer
    # streaming stops on end()
    assert "md.streaming = false" in answer
    # the card chrome (left border, header label, footer) now belongs to the TURN,
    # not the answer block — the answer is purely the streamed markdown body.
    assert 'border: ["left"]' not in answer
    assert "╭" not in answer and "╰" not in answer
    # the retype mechanism is gone: no teardown contract with turnView
    assert "teardown" not in answer


def test_thinking_block_is_purple_glyph_timeline() -> None:
    thinking = _read("blocks/thinkingBlock.mjs")
    assert "✻" in thinking
    assert "THEME.thinkingAccent" in thinking
    # reasoning renders incrementally as it streams (render called from append)
    assert "append(delta)" in thinking
    assert "render()" in thinking
    # clips to viewport so continuation lines never wrap past the rail
    assert "clipToCells" in thinking
    assert "timelineAvailCells" in thinking


def test_tool_block_groups_detail_and_pulses() -> None:
    tool = _read("blocks/toolBlock.mjs")
    assert "✓" in tool and "✗" in tool
    assert "setGlyph" in tool
    # result preview clipped to viewport (no rail-breaking wrap)
    assert "clipToCells" in tool
    assert "timelineAvailCells" in tool
    # Run-state colors come from the shared STATUS vocabulary (opencode/codex
    # alignment): soft-orange while running, green/red on resolution, dim result.
    assert "STATUS.running" in tool
    assert "STATUS.ok" in tool and "STATUS.error" in tool
    assert "STATUS.detail" in tool
    # codex-style: ONE "└ " result corner (cap), a " · {duration}" suffix on
    # completion, and args inline after the name (no separate args node).
    assert "RESULT_CORNER" in tool and "DURATION_SEP" in tool
    assert "resultAdded" in tool  # the single-result-corner guard
    assert "duration" in tool


def test_prompt_and_usage_and_error_blocks() -> None:
    prompt = _read("blocks/promptBlock.mjs")
    usage = _read("blocks/usageBlock.mjs")
    error = _read("blocks/errorBlock.mjs")
    # the prompt is a compact chrome-free row set: a border-left rail box with
    # one muted text node per line — no header rule, no footer
    assert 'border: ["left"]' in prompt
    assert "THEME.promptAccent" in prompt
    assert "THEME.muted" in prompt
    assert "╭" not in prompt and "╰" not in prompt
    assert "·" in usage
    assert "THEME.muted" in usage
    assert "✗" in error
    assert "THEME.error" in error


def test_turnview_routes_block_messages() -> None:
    tv = _read("turnView.mjs")
    assert "createTurnView" in tv
    for method in ["begin(", "append(", "update(", "end(", "refreshPulse("]:
        assert method in tv, f"turnView missing {method}"
    # the retype mechanism is gone: blocks keep their kind for life
    assert "retype" not in tv
    assert "teardown" not in tv
    assert "seedText" not in tv
    # running-tool pulse set is maintained (no dangling animated nodes)
    assert "runningTools" in tv


def test_dispatcher_routes_block_and_legacy_messages() -> None:
    ipc = _read("ipc.mjs")
    assert "createDispatcher" in ipc
    for t in [
        "turn.begin",
        "turn.end",
        "turn.status",
        "composer.set",
        "completion.context",
        "completion.response",
        "router.update",
        "block.begin",
        "block.append",
        "block.update",
        "block.end",
        "prompt.echo",
        "model.text",
        "scrollback.write",
        "notice.write",
        "theme.set",
        "theme.pick",
        "shutdown",
    ]:
        assert f'"{t}"' in ipc, f"dispatcher missing case {t}"


def test_composer_input_region_behaviors() -> None:
    composer = _read("composer.mjs")
    assert "createComposer" in composer
    assert "inputHistory" in composer
    assert "syncTerminalCursorToCaret" in composer
    assert "scrollBy" in composer
    # esc cancels the turn; ctrl+C clears-or-eofs; option/meta+return inserts newline
    assert '"escape"' in composer
    assert "input.cancel" in composer
    assert "input.eof" in composer
    assert 'insertAtCursor("\\n")' in composer
    assert ("pageup" in composer) or ("pagedown" in composer)


def test_composer_router_state_carries_structured_fields() -> None:
    composer = _read("composer.mjs")
    # routerState seeds the new structured fields.
    assert "baselineModel" in composer
    assert "rolloutPhase" in composer
    # setRouterState reads the snake_case keys Python sends via asdict.
    assert "baseline_model" in composer
    assert "routing_applied" in composer
    assert "rollout_phase" in composer
    # the model row can render a downgrade marker and source markers exist.
    assert "shortModel" in composer
    assert "↓" in composer
    assert "setCompletionContext" in composer


def test_composer_router_model_downgrade_keeps_target_model_visible() -> None:
    module_path = (
        "./src/opensquilla/cli/tui/opentui/package/src/"
        "composer.mjs"
    )
    prim_path = (
        "./src/opensquilla/cli/tui/opentui/package/src/"
        "primitives.mjs"
    )
    data = _node_json(
        f"""
        const {{ routerStripValue, formatRouterModelValue }} = await import("{module_path}");
        const {{ textWidth }} = await import("{prim_path}");
        const target = "vendor/small-fast";
        const baseline = "vendor/big-heavy";
        const downgrade = formatRouterModelValue(target, baseline);
        const unchanged = formatRouterModelValue(target, target);
        const row = routerStripValue(downgrade);
        const clippedLong = routerStripValue("x".repeat(30));
        console.log(JSON.stringify({{
          downgrade, unchanged, row,
          clippedLong, clippedWidth: textWidth(clippedLong),
        }}));
        """
    )
    assert data["downgrade"] == "↓ small-fast"
    assert data["unchanged"] == "small-fast"
    assert "small-fast" in data["row"]
    assert "big-heavy" not in data["row"]
    # The live strip clips every value cell to 18 display cells.
    assert data["clippedLong"].endswith("…")
    assert data["clippedWidth"] <= 18


def test_main_is_thin_entry_with_mouse_and_alt_screen() -> None:
    main = _read("main.mjs")
    assert 'screenMode: "alternate-screen"' in main
    assert "useMouse: true" in main
    assert "ScrollBoxRenderable" in main
    assert 'stickyStart: "bottom"' in main
    assert "viewportCulling" in main
    assert "createTurnView" in main
    assert "createComposer" in main
    assert "createDispatcher" in main
    # old monolith artifacts must be gone
    assert "class TurnView" not in main
    assert "OPENTUI_DAILY_THEME" not in main
    assert "answer.demote" not in main


def test_resize_reflows_width_clipped_block_content() -> None:
    # The card chrome is width-independent, so a resize only re-clips block
    # content (tool result corners, narration wraps): main tracks every turn
    # and calls relayout(), which skips entirely on a height-only resize and
    # otherwise defers to each block. No module bakes a width-dependent header
    # rule anymore.
    main = _read("main.mjs")
    turn = _read("turnView.mjs")
    tool = _read("blocks/toolBlock.mjs")
    prompt = _read("blocks/promptBlock.mjs")
    assert "turns" in main and "relayout" in main
    assert "relayout()" in turn and "lastRelayoutWidth" in turn
    assert "relayout()" in tool
    # the compact prompt has nothing width-dependent left to reflow
    assert "relayout()" not in prompt
    # A resize must force a FULL repaint, else OpenTUI's diff-render leaves the old
    # (wider) layout's cells uncleared — the router box bleeds through as stale
    # glyphs when the window shrinks.
    assert "forceFullRepaintRequested" in main


def test_no_legacy_optimistic_demote_in_host() -> None:
    # The optimistic-render + demote/retype model is gone entirely: reasoning
    # and answer arrive as distinct streams, so no block ever changes kind.
    for f in ["main.mjs", "turnView.mjs"]:
        src = _read(f)
        assert "demoteAnswerToTimeline" not in src
        assert "promoteAnswerToCard" not in src
        assert "retype" not in src
