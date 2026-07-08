import { THEME } from "./theme.mjs";
import { TOOL_INDENT, stripTerminalControls } from "./primitives.mjs";
import { createPromptBlock } from "./blocks/promptBlock.mjs";
import { createThinkingBlock } from "./blocks/thinkingBlock.mjs";
import { createReasoningBlock } from "./blocks/reasoningBlock.mjs";
import { createToolBlock } from "./blocks/toolBlock.mjs";
import { createAnswerBlock } from "./blocks/answerBlock.mjs";
import { createUsageBlock } from "./blocks/usageBlock.mjs";
import { createErrorBlock } from "./blocks/errorBlock.mjs";

const FACTORIES = {
  prompt: createPromptBlock,
  // intermediate narration the model speaks between tool calls (a result the
  // user should see) — verbatim purple ✻ text
  thinking: createThinkingBlock,
  // the model's extended-thinking PROCESS — a live dim peek of the latest
  // lines while streaming, collapsed to "Thought for Ns" when it ends
  reasoning: createReasoningBlock,
  tool: createToolBlock,
  answer: createAnswerBlock,
  usage: createUsageBlock,
  error: createErrorBlock,
};

// The block kind set is a Python→JS protocol surface: a newer renderer emitting
// a kind this host does not know must degrade to visible dim plain text, not
// throw mid-dispatch (which would drop the block's content entirely and leave
// the turn card half-mutated).
function createFallbackBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let node = null;
  let text = "";
  const show = () => {
    const content = `${TOOL_INDENT}${stripTerminalControls(text)}`;
    if (node) {
      node.content = content;
    } else {
      node = new TextRenderable(renderer, { id: `${idPrefix}-fallback`, content, fg: THEME.detailText });
      box.add(node);
    }
    renderer.requestRender?.();
  };
  return {
    begin(meta) {
      const seed = String(meta?.text ?? "");
      if (seed) { text = seed; show(); }
    },
    append(delta) { text += String(delta); show(); },
    update() {},
    end() {},
    recolor() { if (node) node.fg = THEME.detailText; },
  };
}

export function createBlock(kind, ctx) {
  const factory = Object.prototype.hasOwnProperty.call(FACTORIES, kind)
    ? FACTORIES[kind]
    : createFallbackBlock;
  return factory(ctx);
}
