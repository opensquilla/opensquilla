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
  // the model's internal extended-thinking PROCESS — collapsed to a single
  // "Thinking…" marker, text never shown
  reasoning: createReasoningBlock,
  tool: createToolBlock,
  answer: createAnswerBlock,
  usage: createUsageBlock,
  error: createErrorBlock,
};

export function createBlock(kind, ctx) {
  const factory = FACTORIES[kind];
  if (!factory) throw new Error(`Unknown block kind: ${kind}`);
  return factory(ctx);
}
