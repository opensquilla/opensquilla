import { THEME } from "../theme.mjs";
import { CARD_RULE_SHORT, cardHeaderRule, stripTerminalControls } from "../primitives.mjs";

export function createPromptBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let top = null; // the "╭─ prompt ─…" header rule (width-dependent)
  const nodes = []; // every prompt-accent node, so a live /theme can recolor them
  const add = (suffix, content) => {
    const n = new TextRenderable(renderer, { id: `${idPrefix}-${suffix}`, content, fg: THEME.promptAccent });
    box.add(n); nodes.push(n); return n;
  };
  return {
    begin(meta) {
      top = add("top", cardHeaderRule("prompt", renderer.terminalWidth));
      stripTerminalControls(String(meta?.text ?? "")).split("\n").forEach((line, i) => add(`l${i}`, `│ ${line}`));
      add("bot", `╰${CARD_RULE_SHORT}`);
      renderer.requestRender?.();
    },
    append() {}, update() {}, end() {},
    // Re-rule the header to the current width on resize; the body lines re-wrap
    // at layout time and the short ╰──── footer is width-independent.
    relayout() {
      if (top) top.content = cardHeaderRule("prompt", renderer.terminalWidth);
    },
    // Live /theme switch: re-point every prompt node at the updated accent.
    recolor() { for (const n of nodes) n.fg = THEME.promptAccent; },
  };
}
