import { THEME } from "../theme.mjs";
import { CARD_RULE_LONG, CARD_RULE_SHORT, stripTerminalControls } from "../primitives.mjs";

export function createPromptBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  const add = (suffix, content) => {
    const n = new TextRenderable(renderer, { id: `${idPrefix}-${suffix}`, content, fg: THEME.promptAccent });
    box.add(n); return n;
  };
  return {
    begin(meta) {
      add("top", `╭─ prompt ${CARD_RULE_LONG}`);
      stripTerminalControls(String(meta?.text ?? "")).split("\n").forEach((line, i) => add(`l${i}`, `│ ${line}`));
      add("bot", `╰${CARD_RULE_SHORT}`);
      renderer.requestRender?.();
    },
    append() {}, update() {}, end() {},
  };
}
