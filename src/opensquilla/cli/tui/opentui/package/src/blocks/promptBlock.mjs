import { THEME } from "../theme.mjs";
import { stripTerminalControls } from "../primitives.mjs";

// The user's own words render as a quiet, compact row — a dim left rail with
// the text beside it, no header/footer chrome. The user already knows what
// they typed, so the assistant's card stays the visually prominent element.
// A real Box border supplies the "│" rail, so an over-long pasted line
// word-wraps WITH the rail on every continuation row.
export function createPromptBlock(ctx) {
  const { renderer, BoxRenderable, TextRenderable, box, idPrefix } = ctx;
  let body = null;
  const nodes = []; // every prompt text node, so a live /theme can recolor them
  return {
    begin(meta) {
      body = new BoxRenderable(renderer, {
        id: `${idPrefix}-body`, width: "100%", flexDirection: "column",
        border: ["left"], borderColor: THEME.promptAccent, paddingLeft: 1, flexShrink: 0,
      });
      box.add(body);
      stripTerminalControls(String(meta?.text ?? "")).split("\n").forEach((line, i) => {
        const n = new TextRenderable(renderer, {
          id: `${idPrefix}-l${i}`, content: line || " ", fg: THEME.muted,
        });
        body.add(n);
        nodes.push(n);
      });
      renderer.requestRender?.();
    },
    append() {}, update() {}, end() {},
    // Live /theme switch: re-point the rail and every line at the updated
    // tokens. Nothing here is width-dependent, so no relayout is needed.
    recolor() {
      for (const n of nodes) n.fg = THEME.muted;
      if (body) body.borderColor = THEME.promptAccent;
    },
  };
}
