import { THEME } from "../theme.mjs";
import { TOOL_INDENT, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

// Thinking renders incrementally as reasoning streams in. Each append re-lays
// the visible lines in place (purple ✻, no card) so the model's thinking
// scrolls live rather than appearing all at once when the block closes.
export function createThinkingBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let text = "";
  let lineCount = 0;
  const nodes = new Map(); // id -> line node, for in-place recolor (no reordering)

  function render() {
    const trimmed = stripTerminalControls(text).replace(/^\n+/, "");
    if (!trimmed) return;
    const lines = trimmed.split("\n");
    lines.forEach((line, i) => {
      // The turn card's left border supplies the gutter; continuation lines just
      // indent to align under the ✻ marker rather than redrawing their own "│".
      const prefix = i === 0 ? `${TOOL_INDENT}✻ ` : `${TOOL_INDENT}  `;
      const avail = timelineAvailCells(prefix, renderer.terminalWidth);
      const content = `${prefix}${clipToCells(line, avail)}`;
      const id = `${idPrefix}-l${i}`;
      // Reuse the existing node for a line we have already drawn (the streaming
      // last line grows in place); add a node for each newly revealed line.
      box.remove?.(id);
      const n = new TextRenderable(renderer, { id, content, fg: THEME.thinkingAccent });
      box.add(n);
      nodes.set(id, n);
    });
    lineCount = lines.length;
    renderer.requestRender?.();
  }

  return {
    // seedText feeds pre-existing text (no longer used by retype, kept for any
    // caller that wants to prime the block before streaming).
    seedText(t) { text = String(t); render(); },
    begin() {},
    append(delta) { text += String(delta); render(); },
    update() {},
    end() {},
    // Live /theme switch: re-point the existing line nodes at the updated accent
    // IN PLACE. Re-running render() would box.remove()+box.add() each line, which
    // re-appends them after any later blocks in the shared card body — reordering
    // the transcript. Setting fg directly avoids that.
    recolor() { for (const n of nodes.values()) n.fg = THEME.thinkingAccent; },
  };
}
