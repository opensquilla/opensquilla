import { THEME } from "../theme.mjs";
import { TOOL_INDENT, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

export function createThinkingBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let text = "";
  let rendered = false;
  function flush() {
    const trimmed = stripTerminalControls(text).replace(/^\n+|\n+$/g, "");
    if (!trimmed) return;
    const gt = new TextRenderable(renderer, { id: `${idPrefix}-gt`, content: `${TOOL_INDENT}│`, fg: THEME.detailText }); box.add(gt);
    trimmed.split("\n").forEach((line, i) => {
      const prefix = i === 0 ? `${TOOL_INDENT}✱ ` : `${TOOL_INDENT}  `;
      const avail = timelineAvailCells(prefix, renderer.terminalWidth);
      const n = new TextRenderable(renderer, { id: `${idPrefix}-l${i}`, content: `${prefix}${clipToCells(line, avail)}`, fg: THEME.modelText }); box.add(n);
    });
    const gb = new TextRenderable(renderer, { id: `${idPrefix}-gb`, content: `${TOOL_INDENT}│`, fg: THEME.detailText }); box.add(gb);
    rendered = true;
    renderer.requestRender?.();
  }
  return {
    seedText(t) { text = t; },
    begin() {},
    append(delta) { text += String(delta); },
    update() {}, retype() {},
    end() { if (!rendered) flush(); },
  };
}
