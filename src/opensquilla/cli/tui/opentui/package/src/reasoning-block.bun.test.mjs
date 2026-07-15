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
import { createReasoningBlock, livePeekRows } from "./blocks/reasoningBlock.mjs";
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

test("reasoning activity is visible before the provider emits its first delta", async () => {
  const setup = await createTestRenderer({ width: WIDTH, height: HEIGHT });
  const { renderer, renderOnce, captureSpans } = setup;
  const box = new BoxRenderable(renderer, {
    id: "turn", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    flexDirection: "column",
  });
  renderer.root.add(box);
  const block = createReasoningBlock({
    renderer, BoxRenderable, TextRenderable, MarkdownRenderable,
    syntaxStyle: undefined, box, idPrefix: "waiting",
  });
  try {
    block.begin({ waiting: true });
    await renderOnce();
    const waiting = flatText(captureSpans());
    expect(waiting).toContain("Thinking");
    expect(waiting).toContain("Waiting for model output…");

    block.append("Inspecting the first-screen hierarchy.");
    await renderOnce();
    const streaming = flatText(captureSpans());
    expect(streaming).toContain("Inspecting the first-screen hierarchy.");
    expect(streaming).not.toContain("Waiting for model output…");

    block.end();
    await renderOnce();
    expect(flatText(captureSpans())).toContain("Thought for");
  } finally {
    renderer.destroy?.();
  }
});

test("a sub-second silent wait disappears instead of leaving a Worked for 0s row", async () => {
  const setup = await createTestRenderer({ width: WIDTH, height: HEIGHT });
  const { renderer, renderOnce, captureSpans } = setup;
  const box = new BoxRenderable(renderer, {
    id: "turn", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    flexDirection: "column",
  });
  renderer.root.add(box);
  const block = createReasoningBlock({
    renderer, BoxRenderable, TextRenderable, MarkdownRenderable,
    syntaxStyle: undefined, box, idPrefix: "silent",
  });
  try {
    block.begin({ waiting: true });
    block.end();
    await renderOnce();
    const text = flatText(captureSpans());
    expect(text).not.toContain("Worked for 0s");
    expect(text).not.toContain("Thinking");
    expect(text).not.toContain("Waiting for model output…");
    expect(text).not.toContain("reasoning lines");
  } finally {
    renderer.destroy?.();
  }
});

test("completed replay uses the recorded reasoning elapsed time", async () => {
  const setup = await createTestRenderer({ width: WIDTH, height: HEIGHT });
  const { renderer, renderOnce, captureSpans } = setup;
  const box = new BoxRenderable(renderer, {
    id: "turn", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    flexDirection: "column",
  });
  renderer.root.add(box);
  const block = createReasoningBlock({
    renderer, BoxRenderable, TextRenderable, MarkdownRenderable,
    syntaxStyle: undefined, box, idPrefix: "recorded-elapsed",
  });
  try {
    block.begin({ elapsedSeconds: 12 });
    block.append("Retained reasoning text.");
    block.end();
    await renderOnce();
    const text = flatText(captureSpans());
    expect(text).toContain("Thought for 12s");
    expect(text).not.toContain("Thought for 0s");
  } finally {
    renderer.destroy?.();
  }
});

test("live reasoning peek adapts to terminal height", () => {
  expect(livePeekRows(12)).toBe(3);
  expect(livePeekRows(24)).toBe(4);
  expect(livePeekRows(40)).toBe(8);
  expect(livePeekRows(100)).toBe(8);
});

test("finished reasoning reports hidden lines and expands the complete retained payload", async () => {
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
  const initial = "line one\nline two\nline three\nline four";
  block.append(initial);
  await renderOnce();
  // The peek is a rolling tail: only the newest lines stay visible.
  const streaming = flatText(captureSpans());
  expect(streaming).not.toContain("line one");
  expect(streaming).toContain("line four");

  block.end();
  await renderOnce();
  const done = flatText(captureSpans());
  // Collapsed: process text is compact, but the disclosure makes the retained
  // payload and exact hidden-line count explicit.
  expect(done).toContain("Thought for");
  expect(done).toContain("4 reasoning lines");
  expect(done).toContain("expand details");
  expect(done).not.toContain("line four");
  expect(block.rawText).toBe(initial);
  expect(block.hiddenLineCount).toBe(4);

  expect(block.toggleExpanded()).toBe(true);
  await renderOnce();
  const expanded = flatText(captureSpans());
  expect(expanded).toContain("line one");
  expect(expanded).toContain("line four");
  expect(expanded).toContain("collapse details");
  expect(block.hiddenLineCount).toBe(0);

  // Straggling deltas are not discarded after end; expansion updates in place.
  block.append("\nlate reasoning tail");
  await renderOnce();
  expect(block.rawText).toBe(`${initial}\nlate reasoning tail`);
  expect(flatText(captureSpans())).toContain("late reasoning tail");

  expect(block.toggleExpanded(false)).toBe(false);
  await renderOnce();
  expect(flatText(captureSpans())).toContain("5 reasoning lines");
  renderer.destroy?.();
});

test("turn-level details toggles narration, reasoning, and tools together", async () => {
  const setup = await createTestRenderer({ width: 76, height: 42 });
  const { renderer, renderOnce, captureSpans } = setup;
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    flexDirection: "column",
  });
  renderer.root.add(conversationBox);
  const turn = createTurnView(
    { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle: undefined, conversationBox },
    "details",
  );
  const narration = Array.from({ length: 8 }, (_, i) => `narration ${i + 1}`).join("\n");
  const reasoning = "reason one\nreason two\nreason three\nreason four";
  const output = "output one\noutput two\noutput three\noutput four";

  turn.begin("n", "thinking", {});
  turn.append("n", narration);
  turn.end("n");
  turn.begin("r", "reasoning", {});
  turn.append("r", reasoning);
  turn.end("r");
  turn.begin("t", "tool", { name: "probe", args: "value" });
  turn.append("t", output);
  turn.update("t", { status: "ok" });
  turn.end("t");
  turn.finish();
  try {
    await renderOnce();
    const collapsed = flatText(captureSpans());
    expect(collapsed).not.toContain("narration 8");
    expect(collapsed).not.toContain("reason four");
    expect(collapsed).not.toContain("output four");
    expect(turn.blockState("n").rawText).toBe(narration);
    expect(turn.blockState("r").rawText).toBe(reasoning);
    expect(turn.blockState("t").rawText).toBe(output);

    const toggle = turn.toggleDetails;
    expect(toggle()).toBe(true); // callback-safe, no `this` dependency
    await renderOnce();
    const expanded = flatText(captureSpans());
    expect(expanded).toContain("narration 8");
    expect(expanded).toContain("reason four");
    expect(expanded).toContain("output four");
    expect(expanded.indexOf("narration 8")).toBeLessThan(expanded.indexOf("Thought for"));
    expect(expanded.indexOf("reason four")).toBeLessThan(expanded.indexOf("probe value"));
    for (const id of ["n", "r", "t"]) expect(turn.blockState(id).isExpanded).toBe(true);

    expect(turn.setDetailsExpanded(false)).toBe(false);
    for (const id of ["n", "r", "t"]) expect(turn.blockState(id).isExpanded).toBe(false);
  } finally {
    renderer.destroy?.();
  }
});
