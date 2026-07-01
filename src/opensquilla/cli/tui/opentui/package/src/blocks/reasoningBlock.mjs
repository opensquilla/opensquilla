import { THEME } from "../theme.mjs";
import { TOOL_INDENT } from "../primitives.mjs";

// The model's reasoning (extended-thinking) PROCESS is intentionally not shown
// verbatim — only a single collapsed "Thinking…" marker tells the user the
// model is reasoning. The renderer never streams reasoning text here (it sends
// no block.append for reasoning), so this block has no append/update behaviour:
// begin() draws the transient marker, end() removes it from the timeline.
export function createReasoningBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  const markerId = `${idPrefix}-mark`;
  let node = null;

  function setGlyph(glyph) {
    if (!node) return;
    node.content = `${TOOL_INDENT}${glyph} Thinking…`;
    renderer.requestRender?.();
  }

  return {
    begin() {
      node = new TextRenderable(renderer, {
        id: markerId,
        content: `${TOOL_INDENT}✻ Thinking…`,
        fg: THEME.thinkingAccent,
      });
      box.add(node);
      renderer.requestRender?.();
    },
    append() {},
    update() {},
    setGlyph,
    end() {
      box.remove?.(markerId);
      node = null;
      renderer.requestRender?.();
    },
  };
}
