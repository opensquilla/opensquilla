import { THEME } from "../theme.mjs";
import { stripTerminalControls } from "../primitives.mjs";

// The answer is just the streamed markdown body now: its card chrome (header
// rule, left border, footer) is owned by the turn, which wraps the whole
// assistant turn in ONE card so narration and tool calls share a continuous
// gutter. begin() mounts the markdown into the turn's shared card body.
export function createAnswerBlock(ctx) {
  const { renderer, MarkdownRenderable, syntaxStyle, box, idPrefix } = ctx;
  let md = null;
  let text = "";
  return {
    get text() { return text; },
    begin() {
      md = new MarkdownRenderable(renderer, { id: `${idPrefix}-md`, content: "", streaming: true, conceal: true, syntaxStyle, fg: THEME.text, tableOptions: { style: "columns" }, internalBlockMode: "top-level", width: "100%" });
      box.add(md);
      renderer.requestRender?.();
    },
    append(delta) { text += String(delta); if (md) md.content = stripTerminalControls(text); renderer.requestRender?.(); },
    update() {},
    end() { if (md) md.streaming = false; renderer.requestRender?.(); },
    // Live /theme switch: re-point the body fg at the (in-place updated) THEME.
    // Syntax-highlighted spans track the shared syntaxStyle, which main refreshes
    // on the same theme event, so only the base foreground needs resetting here.
    recolor() { if (md) md.fg = THEME.text; },
  };
}
