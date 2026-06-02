import { THEME } from "../theme.mjs";
import { TOOL_INDENT, stripTerminalControls } from "../primitives.mjs";

export function createErrorBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  return {
    begin(meta) {
      const n = new TextRenderable(renderer, {
        id: `${idPrefix}-err`, content: `${TOOL_INDENT}✗ ${stripTerminalControls(String(meta?.text ?? ""))}`, fg: THEME.routerError,
      });
      box.add(n); renderer.requestRender?.();
    },
    append() {}, update() {}, end() {},
  };
}
