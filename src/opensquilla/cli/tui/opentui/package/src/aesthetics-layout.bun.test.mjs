// Layout/spacing regression tests for the modern-TUI refinements:
//   - card header rules adapt to terminal width (align to the full-width body)
//     instead of a fixed length that strands on wide / overflows narrow screens;
//   - turns carry one blank line of vertical rhythm so they read as distinct
//     groups (proximity) and the conversation breathes.
//
// Run with: bun test src/aesthetics-layout.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import { cardHeaderRule, textWidth } from "./primitives.mjs";
import { createTurnView } from "./turnView.mjs";

test("card header rule fills to content width and scales with the terminal", () => {
  // Content width is terminalWidth - 2 (turn box pads 1 cell each side).
  expect(textWidth(cardHeaderRule("answer ─ squilla", 60))).toBe(58);
  expect(textWidth(cardHeaderRule("answer ─ squilla", 120))).toBe(118);
  // Wider terminal => longer rule (adaptive, not fixed).
  expect(textWidth(cardHeaderRule("prompt", 120))).toBeGreaterThan(
    textWidth(cardHeaderRule("prompt", 60)),
  );
  // Keeps the corner + label so the header still reads as a card.
  expect(cardHeaderRule("answer ─ squilla", 80).startsWith("╭─ answer ─ squilla ─")).toBe(true);
  // Never collapses below a sane minimum on tiny widths.
  expect(textWidth(cardHeaderRule("answer ─ squilla", 10))).toBeGreaterThan(
    textWidth("╭─ answer ─ squilla "),
  );
});

test("turns are separated by a blank line of vertical rhythm", async () => {
  const { renderer, renderOnce, captureSpans } = await createTestRenderer({ width: 50, height: 14 });
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
  const deps = {
    renderer,
    BoxRenderable,
    TextRenderable,
    MarkdownRenderable: null,
    syntaxStyle: null,
    conversationBox,
  };
  for (const id of ["A", "B"]) {
    createTurnView(deps, id).begin(`b${id}`, "tool", { name: `tool_${id}`, args: "" });
  }
  await renderOnce();
  const frame = captureSpans();
  const row = (r) => (frame.lines[r] ? frame.lines[r].spans.map((s) => s.text).join("") : "");

  // Find the two tool labels and assert a blank line sits between the turns.
  const aRow = [...Array(10).keys()].find((r) => row(r).includes("tool_A"));
  const bRow = [...Array(10).keys()].find((r) => row(r).includes("tool_B"));
  expect(aRow).toBeGreaterThanOrEqual(0);
  expect(bRow).toBeGreaterThan(aRow);
  // At least one fully-blank row separates the end of turn A from turn B.
  const between = [...Array(bRow - aRow).keys()].map((i) => row(aRow + 1 + i));
  expect(between.some((line) => line.trim() === "")).toBe(true);
  renderer.destroy?.();
});

test("a resize re-rules existing card headers to the new width", async () => {
  // The bug: card header rules are baked TextRenderables created at the width at
  // begin() time, so on resize they wrap (shrink) or strand (grow). relayout()
  // re-rules them to the current width.
  const { renderer, renderOnce, captureSpans, resize } = await createTestRenderer({
    width: 100,
    height: 16,
  });
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height: 16,
    flexDirection: "column",
  });
  renderer.root.add(conversationBox);
  const turn = createTurnView(
    { renderer, BoxRenderable, TextRenderable, MarkdownRenderable: null, syntaxStyle: null, conversationBox },
    "rx",
  );
  turn.begin("p", "prompt", { text: "hi there" });
  turn.begin("tl", "tool", { name: "grep", args: "x" }); // opens the squilla card
  turn.update("tl", { status: "ok" });
  turn.end("tl");
  turn.finish();
  await renderOnce();

  const lines = (f) => f.lines.map((l) => l.spans.map((s) => s.text).join("").trim());

  // At width 100 the rules fill to the wide form.
  expect(lines(captureSpans())).toContain(cardHeaderRule("squilla", 100));
  expect(lines(captureSpans())).toContain(cardHeaderRule("prompt", 100));

  // Shrink to 50 and reflow.
  const doResize = resize || ((w, h) => renderer.resize(w, h));
  await doResize(50, 16);
  conversationBox.height = 16;
  turn.relayout();
  await renderOnce();

  // Both headers re-ruled to the narrow form; the stale wide rule (which would
  // wrap into stray dash lines) is gone.
  const after = lines(captureSpans());
  expect(after).toContain(cardHeaderRule("squilla", 50));
  expect(after).toContain(cardHeaderRule("prompt", 50));
  expect(after).not.toContain(cardHeaderRule("squilla", 100));
  renderer.destroy?.();
});
