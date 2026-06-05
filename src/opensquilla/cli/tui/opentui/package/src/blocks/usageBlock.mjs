import { THEME } from "../theme.mjs";
import { stripTerminalControls } from "../primitives.mjs";

export function createUsageBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  return {
    begin(meta) {
      const n = new TextRenderable(renderer, {
        id: `${idPrefix}-usage`, content: `  · ${stripTerminalControls(String(meta?.text ?? ""))}`, fg: THEME.muted,
      });
      box.add(n); renderer.requestRender?.();
    },
    append() {}, update() {}, end() {},
  };
}
