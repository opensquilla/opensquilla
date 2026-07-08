// Renderer-level regression for the reasoning/answer block split.
//
// The original bug: a streaming thinking block briefly flashed the cyan answer
// card because the renderer opened text as an answer block and only later
// retyped it to thinking. With reasoning now a first-class stream, a thinking
// block must render as plain purple ✻ lines with NO card border, while an
// answer block keeps its card. A text-snapshot harness could miss colour, but
// the card is made of corner glyphs (╭/╰), so we assert on the captured glyphs
// directly.
//
// Must run under bun: @opentui/core/testing needs bun FFI.
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable, MarkdownRenderable } from "@opentui/core";

import { createThinkingBlock } from "./blocks/thinkingBlock.mjs";
import { createReasoningBlock } from "./blocks/reasoningBlock.mjs";
import { createTurnView } from "./turnView.mjs";

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

test("a streaming thinking block shows purple ✻ text with no answer card", async () => {
  const text = flatText(await renderBlock(createThinkingBlock));
  // reasoning is visible while still streaming (incremental render)
  expect(text).toContain("partial reasoning");
  expect(text).toContain("✻");
  // the decisive check: NO answer card border leaks around the thinking stream
  expect(text).not.toContain("answer");
  expect(text).not.toContain("╭");
  expect(text).not.toContain("╰");
});

test("an assistant turn wraps its answer in a single squilla card", async () => {
  // Contrast case proving the assertion above discriminates. The card chrome now
  // belongs to the TURN (one card per turn), not the answer block, so drive a
  // turn view: an answer renders inside a card with the short "╭ squilla" label
  // on top and a "╰" footer below.
  const { renderer, renderOnce, captureSpans } = await createTestRenderer({ width: WIDTH, height: HEIGHT });
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    flexDirection: "column",
  });
  renderer.root.add(conversationBox);
  const turn = createTurnView(
    { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle: undefined, conversationBox },
    "ans",
  );
  turn.begin("a1", "answer", {});
  turn.append("a1", "the final answer text");
  turn.end("a1");
  turn.finish();
  await renderOnce();
  const text = flatText(captureSpans());
  renderer.destroy?.();

  expect(text).toContain("╭ squilla");
  expect(text).toContain("╰");
});

test("a streaming reasoning block shows a live peek under the Thinking header", async () => {
  // Mid-stream (before end()), the latest reasoning lines are visible as a
  // dim peek beneath the pulsing header — live feedback while the model thinks.
  const text = flatText(await renderBlock(createReasoningBlock));
  expect(text).toContain("✻");
  expect(text).toContain("Thinking");
  expect(text).toContain("partial reasoning still streaming");
  // no card chrome leaks around the peek
  expect(text).not.toContain("╭");
  expect(text).not.toContain("╰");
});

test("a finished reasoning block collapses to a one-line Thought record", async () => {
  const setup = await createTestRenderer({ width: WIDTH, height: HEIGHT });
  const { renderer, renderOnce, captureSpans } = setup;
  const box = new BoxRenderable(renderer, {
    id: "turn", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    flexDirection: "column",
  });
  renderer.root.add(box);
  const block = createReasoningBlock({
    renderer, BoxRenderable, TextRenderable, MarkdownRenderable,
    syntaxStyle: undefined, box, idPrefix: "blk",
  });
  block.begin({});
  block.append("line one\nline two\nline three\nline four");
  await renderOnce();
  // The peek is a rolling tail: only the newest lines stay visible.
  const streaming = flatText(captureSpans());
  expect(streaming).not.toContain("line one");
  expect(streaming).toContain("line four");

  block.end();
  await renderOnce();
  const done = flatText(captureSpans());
  // Collapsed: the process text is gone, the one-line record remains.
  expect(done).toContain("Thought for");
  expect(done).not.toContain("line four");
  renderer.destroy?.();
});
