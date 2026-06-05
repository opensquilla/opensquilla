import { THEME } from "../theme.mjs";
import { CARD_RULE_LONG, CARD_RULE_SHORT, TOOL_INDENT, stripTerminalControls } from "../primitives.mjs";

export function createAnswerBlock(ctx) {
  const { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, box, idPrefix } = ctx;
  let gap = null, top = null, body = null, md = null, bot = null;
  let text = "";
  return {
    get text() { return text; },
    begin() {
      gap = new TextRenderable(renderer, { id: `${idPrefix}-gap`, content: `${TOOL_INDENT}│`, fg: THEME.detailText }); box.add(gap);
      top = new TextRenderable(renderer, { id: `${idPrefix}-top`, content: `╭─ answer ─ squilla ${CARD_RULE_LONG}`, fg: THEME.toolAccent }); box.add(top);
      body = new BoxRenderable(renderer, { id: `${idPrefix}-body`, width: "100%", flexDirection: "column", border: ["left"], borderColor: THEME.toolAccent, paddingLeft: 1, flexShrink: 0 });
      md = new MarkdownRenderable(renderer, { id: `${idPrefix}-md`, content: "", streaming: true, conceal: true, syntaxStyle, fg: THEME.text, tableOptions: { style: "columns" }, internalBlockMode: "top-level", width: "100%" });
      body.add(md); box.add(body);
      renderer.requestRender?.();
    },
    append(delta) { text += String(delta); if (md) md.content = stripTerminalControls(text); renderer.requestRender?.(); },
    update() {},
    end() {
      if (md) md.streaming = false;
      bot = new TextRenderable(renderer, { id: `${idPrefix}-bot`, content: `╰${CARD_RULE_SHORT}`, fg: THEME.toolAccent }); box.add(bot);
      renderer.requestRender?.();
    },
  };
}
