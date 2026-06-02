import { THEME, STATUS_PULSE_FRAMES } from "../theme.mjs";
import { TOOL_INDENT, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

export function createToolBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let node = null;
  let railNode = null;
  let name = "";
  let tail = "";
  let detailCount = 0;
  const detailPrefix = `${TOOL_INDENT}│   `;

  function setGlyph(glyph) {
    if (node) node.content = `${TOOL_INDENT}${glyph} ${name}${tail}`;
  }

  return {
    get node() { return node; },
    get isRunning() { return node !== null && railNode !== null && !node._done; },
    setGlyph,
    begin(meta) {
      name = stripTerminalControls(String(meta?.name ?? ""));
      const summary = stripTerminalControls(String(meta?.args ?? ""));
      tail = summary ? ` ${summary}` : "";
      railNode = new TextRenderable(renderer, { id: `${idPrefix}-rail`, content: `${TOOL_INDENT}│`, fg: THEME.detailText });
      box.add(railNode);
      node = new TextRenderable(renderer, { id: `${idPrefix}-node`, content: `${TOOL_INDENT}${STATUS_PULSE_FRAMES.tool[0]} ${name}${tail}`, fg: THEME.toolAccent });
      box.add(node);
      renderer.requestRender?.();
    },
    append(delta) {
      if (detailCount >= 3) return;
      const avail = timelineAvailCells(detailPrefix, renderer.terminalWidth);
      const content = `${detailPrefix}${clipToCells(stripTerminalControls(String(delta)), avail)}`;
      const d = new TextRenderable(renderer, { id: `${idPrefix}-d${detailCount}`, content, fg: THEME.detailText });
      box.add(d);
      detailCount += 1;
      renderer.requestRender?.();
    },
    update(patch) {
      const status = patch?.status;
      if (status === "ok" || status === "error") {
        const glyph = status === "error" ? "✗" : "✓";
        if (node) { node.content = `${TOOL_INDENT}${glyph} ${name}${tail}`; node.fg = status === "error" ? THEME.routerError : THEME.answerAccent; node._done = true; }
      }
      renderer.requestRender?.();
    },
    end() { if (node) node._done = true; },
  };
}
