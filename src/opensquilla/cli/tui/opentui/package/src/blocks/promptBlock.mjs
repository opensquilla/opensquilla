import { THEME } from "../theme.mjs";
import { CARD_RULE_SHORT, cardHeaderRule, stripTerminalControls } from "../primitives.mjs";

export function createPromptBlock(ctx) {
  const { renderer, BoxRenderable, TextRenderable, box, idPrefix } = ctx;
  let top = null; // the "╭─ prompt ─…" header rule (width-dependent)
  let body = null; // the bordered body box (its left "│" rail survives wrapping)
  const nodes = []; // every prompt-accent text node, so a live /theme can recolor them
  const add = (target, suffix, content) => {
    const n = new TextRenderable(renderer, { id: `${idPrefix}-${suffix}`, content, fg: THEME.promptAccent });
    target.add(n); nodes.push(n); return n;
  };
  return {
    begin(meta) {
      top = add(box, "top", cardHeaderRule("prompt", renderer.terminalWidth));
      // A real Box border supplies the "│" rail (like the assistant card), so an
      // over-long pasted line word-wraps WITH the rail on every continuation row
      // instead of breaking the card between header and footer.
      body = new BoxRenderable(renderer, {
        id: `${idPrefix}-body`, width: "100%", flexDirection: "column",
        border: ["left"], borderColor: THEME.promptAccent, paddingLeft: 1, flexShrink: 0,
      });
      box.add(body);
      stripTerminalControls(String(meta?.text ?? "")).split("\n")
        .forEach((line, i) => add(body, `l${i}`, line || " "));
      add(box, "bot", `╰${CARD_RULE_SHORT}`);
      renderer.requestRender?.();
    },
    append() {}, update() {}, end() {},
    // Re-rule the header to the current width on resize; the body lines re-wrap
    // at layout time and the short ╰──── footer is width-independent.
    relayout() {
      if (top) top.content = cardHeaderRule("prompt", renderer.terminalWidth);
    },
    // Live /theme switch: re-point every prompt node (and the rail) at the
    // updated accent.
    recolor() {
      for (const n of nodes) n.fg = THEME.promptAccent;
      if (body) body.borderColor = THEME.promptAccent;
    },
  };
}
