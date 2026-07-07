// Layout/spacing regression tests for the modern-TUI refinements:
//   - card header rules adapt to terminal width (align to the full-width body)
//     instead of a fixed length that strands on wide / overflows narrow screens;
//   - turns carry one blank line of vertical rhythm so they read as distinct
//     groups (proximity) and the conversation breathes;
//   - card open/close discipline (empty shells removed, prompts never seal a
//     streaming card, cancelled turns are marked) and the ScrollBox
//     manual-scroll contract the bottom-follow logic relies on.
//
// Run with: bun test src/aesthetics-layout.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, ScrollBoxRenderable, TextRenderable } from "@opentui/core";

import { cardHeaderRule, textWidth } from "./primitives.mjs";
import { shouldFollowBottom } from "./main.mjs";
import { createTurnView } from "./turnView.mjs";
import { applyTheme } from "./theme.mjs";

const frameText = (frame) => frame.lines.map((l) => l.spans.map((s) => s.text).join("")).join("\n");
const rgb = (c) => [Math.round(c.r * 255), Math.round(c.g * 255), Math.round(c.b * 255)];

async function makeTurnHarness({ width = 60, height = 14 } = {}) {
  const setup = await createTestRenderer({ width, height });
  const { renderer } = setup;
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height,
    flexDirection: "column",
  });
  renderer.root.add(conversationBox);
  const turn = createTurnView(
    { renderer, BoxRenderable, TextRenderable, MarkdownRenderable: null, syntaxStyle: null, conversationBox },
    "t",
  );
  return { ...setup, conversationBox, turn };
}

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

test("relayout skips re-ruling when the terminal width is unchanged", async () => {
  const { renderer, renderOnce, resize, turn } = await makeTurnHarness({ width: 80, height: 16 });
  turn.begin("tl", "tool", { name: "grep", args: "x" }); // opens the squilla card
  await renderOnce();

  let renders = 0;
  const original = renderer.requestRender?.bind(renderer);
  renderer.requestRender = () => { renders += 1; original?.(); };

  // Same width (a height-only resize path): no text-buffer work at all.
  turn.relayout();
  expect(renders).toBe(0);

  // A real width change still re-rules.
  const doResize = resize || ((w, h) => renderer.resize(w, h));
  await doResize(50, 16);
  const before = renders;
  turn.relayout();
  expect(renders).toBeGreaterThan(before);
  renderer.requestRender = original;
  await renderOnce();
  renderer.destroy?.();
});

test("a reasoning-only turn leaves no empty card shell behind", async () => {
  // Cancel during extended thinking: the transient Thinking… marker removes
  // itself when the reasoning block ends, then the trailing usage block closes
  // the card — which must drop its chrome instead of framing nothing.
  const { renderer, renderOnce, captureSpans, turn } = await makeTurnHarness();
  turn.begin("r1", "reasoning", {});
  turn.end("r1");
  turn.begin("u1", "usage", { text: "in 10 / out 0" });
  turn.end("u1");
  turn.finish(true);
  await renderOnce();
  const text = frameText(captureSpans());
  expect(text).not.toContain("╭"); // no stranded header rule
  expect(text).not.toContain("╰"); // no footer wrapping an empty body
  expect(text).toContain("in 10 / out 0"); // the usage line still renders
  expect(text).toContain("cancelled"); // and the cancel marker tells the story
  renderer.destroy?.();
});

test("turn.end with cancelled=true appends a warning cancel marker; a normal finish does not", async () => {
  applyTheme("opensquilla-dark");
  const { renderer, renderOnce, captureSpans, turn } = await makeTurnHarness();
  turn.begin("tl", "tool", { name: "grep", args: "x" });
  turn.update("tl", { status: "ok" });
  turn.end("tl");
  turn.finish();
  await renderOnce();
  expect(frameText(captureSpans())).not.toContain("cancelled"); // normal turns unchanged
  turn.finish(true); // late cancel signal is still honored once
  await renderOnce();
  const frame = captureSpans();
  const line = frame.lines.find((l) => l.spans.map((s) => s.text).join("").includes("cancelled"));
  expect(line).toBeTruthy();
  const span = line.spans.find((s) => s.text.includes("cancelled"));
  expect(rgb(span.fg)).toEqual([232, 178, 58]); // dark THEME.warning #E8B23A
  renderer.destroy?.();
});

test("a prompt block never seals an open card; only usage closes it", async () => {
  // A queued submission's echo can land while the assistant card is still
  // streaming; the prompt kind must not draw the card footer under it.
  const { renderer, renderOnce, captureSpans, turn } = await makeTurnHarness();
  const footerCount = () => (frameText(captureSpans()).match(/╰/g) ?? []).length;
  turn.begin("tl", "tool", { name: "grep", args: "x" }); // opens the squilla card
  turn.begin("p1", "prompt", { text: "queued question" });
  await renderOnce();
  // Exactly one ╰ on screen: the prompt block's own footer. The assistant card
  // is still open (no second footer).
  expect(footerCount()).toBe(1);
  turn.begin("u1", "usage", { text: "in 5 / out 2" });
  await renderOnce();
  expect(footerCount()).toBe(2); // the trailing usage summary closed the card
  renderer.destroy?.();
});

test("scrollbox flags manual scrolls and clears the flag on snap-to-bottom", async () => {
  // main.mjs's bottom-follow gates on _hasManualScroll: a wheel-up mid-stream
  // must pause following (no yank back on the next append), and snapping to
  // the bottom must resume it. Pin the engine contract those rules rely on.
  const { renderer, renderOnce } = await createTestRenderer({ width: 40, height: 10 });
  const scrollBox = new ScrollBoxRenderable(renderer, {
    id: "conv",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height: 6,
    stickyScroll: true,
    stickyStart: "bottom",
    scrollY: true,
    scrollX: false,
  });
  renderer.root.add(scrollBox);
  scrollBox.focusable = false; // keyboard stays with the composer
  for (let i = 0; i < 30; i += 1) {
    scrollBox.add(new TextRenderable(renderer, { id: `l${i}`, content: `line ${i}` }));
  }
  await renderOnce();

  expect(scrollBox._hasManualScroll).toBe(false); // following by default
  scrollBox.scrollTop = 0; // the user scrolls up to read history
  expect(scrollBox._hasManualScroll).toBe(true); // following pauses
  scrollBox.scrollTop = scrollBox.scrollHeight; // snap back to the bottom
  expect(scrollBox._hasManualScroll).toBe(false); // following resumes

  // focusable=false keeps a click from focusing the transcript scroller, so
  // arrows/j/k can never double-drive it alongside the composer.
  scrollBox.focus();
  expect(scrollBox.focused).toBe(false);
  renderer.destroy?.();
});

test("wheel-scrolling back to the bottom re-engages bottom-follow for the next append", async () => {
  // The engine flags EVERY wheel event in _hasManualScroll — including the
  // wheel-down that lands exactly on the bottom row — and its own reengage
  // check only clears the flag when a layout pass grows content by at most
  // one row. Multi-row mutations (a tool block's gap+row, batched stream
  // deltas, a wrapped paragraph) miss that point, so trusting the stale flag
  // would stream the rest of the turn below the fold. shouldFollowBottom
  // must treat a verified at-bottom position as re-consent to follow.
  const { renderer, renderOnce } = await createTestRenderer({ width: 40, height: 10 });
  const scrollBox = new ScrollBoxRenderable(renderer, {
    id: "conv",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height: 6,
    stickyScroll: true,
    stickyStart: "bottom",
    scrollY: true,
    scrollX: false,
  });
  renderer.root.add(scrollBox);
  scrollBox.focusable = false;
  for (let i = 0; i < 30; i += 1) {
    scrollBox.add(new TextRenderable(renderer, { id: `l${i}`, content: `line ${i}` }));
  }
  await renderOnce();
  const wheel = (direction, delta) =>
    scrollBox.onMouseEvent({ type: "scroll", scroll: { direction, delta }, modifiers: {} });

  expect(shouldFollowBottom(scrollBox)).toBe(true); // following by default

  // Wheel up mid-stream: the hold sticks — appends must not yank back down.
  wheel("up", 3);
  expect(scrollBox._hasManualScroll).toBe(true);
  expect(shouldFollowBottom(scrollBox)).toBe(false);
  expect(scrollBox._hasManualScroll).toBe(true); // the hold survives the check

  // Wheel back down to the bottom: the engine re-flags the manual scroll even
  // though the user landed exactly on the bottom row…
  wheel("down", 30);
  expect(scrollBox._hasManualScroll).toBe(true); // the engine quirk guarded against
  // …but being verifiably at the bottom re-consents to following,
  expect(shouldFollowBottom(scrollBox)).toBe(true);
  expect(scrollBox._hasManualScroll).toBe(false); // and re-arms the engine's stickiness.

  // So a multi-row append right after the return still snaps to the new bottom.
  const pinned = shouldFollowBottom(scrollBox);
  scrollBox.add(new TextRenderable(renderer, { id: "n1", content: "new 1" }));
  scrollBox.add(new TextRenderable(renderer, { id: "n2", content: "new 2" }));
  await renderOnce();
  if (pinned) scrollBox.scrollTop = scrollBox.scrollHeight;
  expect(shouldFollowBottom(scrollBox)).toBe(true);
  renderer.destroy?.();
});
