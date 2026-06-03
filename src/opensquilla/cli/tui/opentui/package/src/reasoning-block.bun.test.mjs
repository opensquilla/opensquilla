// Renderer-level regression for the reasoning/answer block split.
//
// The original bug: a streaming thinking block briefly flashed the cyan answer
// CARD (╭─ answer ─ … ╰─) because the renderer opened text as an answer block
// and only later retyped it to thinking. With reasoning now a first-class
// stream, a thinking block must render as plain purple ✱ lines with NO card
// border, while an answer block keeps its card. A text-snapshot harness could
// miss colour, but the card is made of border glyphs, so we assert on the
// captured glyphs directly.
//
// Must run under bun: @opentui/core/testing needs bun FFI.
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable, MarkdownRenderable } from "@opentui/core";

import { createThinkingBlock } from "./blocks/thinkingBlock.mjs";
import { createReasoningBlock } from "./blocks/reasoningBlock.mjs";
import { createAnswerBlock } from "./blocks/answerBlock.mjs";

const WIDTH = 60;
const HEIGHT = 12;

async function renderBlock(makeBlock) {
  const setup = await createTestRenderer({ width: WIDTH, height: HEIGHT });
  const { renderer, renderOnce, captureSpans } = setup;
  const box = new BoxRenderable(renderer, {
    id: "turn",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    flexDirection: "column",
  });
  renderer.root.add(box);

  const ctx = {
    renderer,
    BoxRenderable,
    TextRenderable,
    MarkdownRenderable,
    syntaxStyle: undefined,
    box,
    idPrefix: "blk",
  };
  const block = makeBlock(ctx);
  block.begin({});
  // Stream a couple of deltas, capturing mid-stream (before end()).
  block.append("partial reasoning ");
  block.append("still streaming");
  await renderOnce();
  const frame = captureSpans();
  renderer.destroy?.();
  return frame;
}

function flatText(frame) {
  return frame.lines
    .map((line) => line.spans.map((s) => s.text).join(""))
    .join("\n");
}

test("a streaming thinking block shows purple ✱ text with no answer card", async () => {
  const text = flatText(await renderBlock(createThinkingBlock));
  // reasoning is visible while still streaming (incremental render)
  expect(text).toContain("partial reasoning");
  expect(text).toContain("✱");
  // the decisive check: NO answer card border leaks around the thinking stream
  expect(text).not.toContain("answer");
  expect(text).not.toContain("╭");
  expect(text).not.toContain("╰");
});

test("a streaming answer block does render its card border", async () => {
  const text = flatText(await renderBlock(createAnswerBlock));
  // contrast case proving the assertion above discriminates: the answer block
  // paints its card top rail immediately.
  expect(text).toContain("answer");
  expect(text).toContain("╭");
});

test("a reasoning block shows only a collapsed Thinking… marker, never the process text", async () => {
  // The reasoning block is fed the same deltas via renderBlock (which calls
  // append), but it must NOT surface the verbatim reasoning — only the marker.
  const text = flatText(await renderBlock(createReasoningBlock));
  expect(text).toContain("✱");
  expect(text).toContain("Thinking");
  // the decisive checks: the reasoning PROCESS text is never shown, and no card
  expect(text).not.toContain("partial reasoning");
  expect(text).not.toContain("still streaming");
  expect(text).not.toContain("answer");
  expect(text).not.toContain("╭");
  expect(text).not.toContain("╰");
});
