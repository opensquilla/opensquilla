import { STATUS, STATUS_PULSE_FRAMES } from "../theme.mjs";
import { TOOL_INDENT, RESULT_CORNER, DURATION_SEP, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

// A tool call renders like opencode/codex: ONE invocation line "<glyph> <name>
// <args>" (the running glyph pulses ◌◔◑◕, the line colored by run-state) and at
// most ONE dim "└ <result preview>" corner below it. On completion the glyph
// flips to ✓/✗ in place, the line recolors to ok/error, and a " · <duration>"
// suffix is appended. The turn card's own left border supplies the gutter, so no
// per-line "│" rail is redrawn.
export function createToolBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let node = null;        // the invocation line (glyph + name + args [+ duration])
  let resultNode = null;  // the single "└ …" result-preview corner, if any
  let resultRaw = "";     // the unclipped preview text, so a resize can re-clip
  let name = "";
  let tail = "";          // " <args>" inline after the name
  let durationTail = "";  // " · <duration>" appended on completion
  let resultAdded = false;
  let runState = "running"; // "running" | "ok" | "error" — so a live /theme recolors

  function lineContent(glyph) {
    return `${TOOL_INDENT}${glyph} ${name}${tail}${durationTail}`;
  }
  function setGlyph(glyph) {
    if (node) node.content = lineContent(glyph);
  }
  function resultContent() {
    const prefix = `${TOOL_INDENT}${RESULT_CORNER}`;
    const avail = timelineAvailCells(prefix, renderer.terminalWidth);
    // The Python side collapses results to one preview line, but a raw
    // multi-line delta must not smear unaligned rows under the corner: join
    // the lines into the single-row "line1 · line2" corner form.
    const flat = resultRaw.replace(/\s*\n+\s*/g, DURATION_SEP).trim();
    return `${prefix}${clipToCells(flat, avail)}`;
  }

  return {
    get node() { return node; },
    get isRunning() { return node !== null && !node._done; },
    setGlyph,
    begin(meta) {
      name = stripTerminalControls(String(meta?.name ?? ""));
      const summary = stripTerminalControls(String(meta?.args ?? ""));
      tail = summary ? ` ${summary}` : "";
      node = new TextRenderable(renderer, { id: `${idPrefix}-node`, content: lineContent(STATUS_PULSE_FRAMES.tool[0]), fg: STATUS.running });
      box.add(node);
      renderer.requestRender?.();
    },
    append(delta) {
      // One result corner per tool; later deltas are ignored (the Python side
      // already collapses the result to a single preview line).
      if (resultAdded) return;
      resultAdded = true;
      resultRaw = stripTerminalControls(String(delta));
      resultNode = new TextRenderable(renderer, { id: `${idPrefix}-result`, content: resultContent(), fg: STATUS.detail });
      box.add(resultNode);
      renderer.requestRender?.();
    },
    update(patch) {
      const status = patch?.status;
      if (patch?.duration) durationTail = `${DURATION_SEP}${stripTerminalControls(String(patch.duration))}`;
      if (status === "ok" || status === "error") {
        runState = status;
        const glyph = status === "error" ? "✗" : "✓";
        if (node) { node.content = lineContent(glyph); node.fg = status === "error" ? STATUS.error : STATUS.ok; node._done = true; }
        if (status === "error" && resultNode) resultNode.fg = STATUS.detailError;
      }
      renderer.requestRender?.();
    },
    end() { if (node) node._done = true; },
    // Re-clip the result preview to the current terminal width on resize; the
    // clip was baked at stream time and would otherwise stay sized to the old
    // width (a stranded "…" after growing, wrapped fragments after shrinking).
    relayout() {
      if (resultNode) resultNode.content = resultContent();
    },
    // Live /theme switch: re-derive the run-state colors from the (in-place
    // updated) STATUS palette for the current state.
    recolor() {
      if (node) node.fg = runState === "error" ? STATUS.error : runState === "ok" ? STATUS.ok : STATUS.running;
      if (resultNode) resultNode.fg = runState === "error" ? STATUS.detailError : STATUS.detail;
    },
  };
}
