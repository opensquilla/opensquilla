import { THEME } from "../theme.mjs";
import { TOOL_INDENT, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

// Thinking renders incrementally as reasoning streams in. Each append re-lays
// the visible lines in place (purple ✱, no card) so the model's thinking
// scrolls live rather than appearing all at once when the block closes.
export function createThinkingBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let text = "";
  let railAdded = false;
  let lineCount = 0;

  function render() {
    const trimmed = stripTerminalControls(text).replace(/^\n+/, "");
    if (!trimmed) return;
    if (!railAdded) {
      const gt = new TextRenderable(renderer, { id: `${idPrefix}-gt`, content: `${TOOL_INDENT}│`, fg: THEME.detailText });
      box.add(gt);
      railAdded = true;
    }
    const lines = trimmed.split("\n");
    lines.forEach((line, i) => {
      const prefix = i === 0 ? `${TOOL_INDENT}✱ ` : `${TOOL_INDENT}│ `;
      const avail = timelineAvailCells(prefix, renderer.terminalWidth);
      const content = `${prefix}${clipToCells(line, avail)}`;
      const id = `${idPrefix}-l${i}`;
      // Reuse the existing node for a line we have already drawn (the streaming
      // last line grows in place); add a node for each newly revealed line.
      box.remove?.(id);
      const n = new TextRenderable(renderer, { id, content, fg: THEME.modelText });
      box.add(n);
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
  };
}
