// Tool-row rendering regressions for the opencode/codex alignment pass.
//
// A tool renders as ONE invocation line "<glyph> <name> <args>" (glyph pulses
// while running, line colored by run-state) plus at most ONE dim "└ <result>"
// corner, and on completion flips the glyph to ✓/✗ in place with a " · {dur}"
// suffix. captureSpans reconstructs glyphs (not color), so color is asserted via
// the held node.fg; structure/streaming is asserted via the captured grid.
//
// Must run under bun: @opentui/core/testing needs bun FFI.
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import { createToolBlock } from "./blocks/toolBlock.mjs";
import { STATUS, STATUS_PULSE_FRAMES } from "./theme.mjs";

const WIDTH = 60;
const HEIGHT = 12;

function flatText(frame) {
  return frame.lines.map((line) => line.spans.map((s) => s.text).join("")).join("\n");
}

// node.fg is parsed into an RGBA, so compare colors via a probe node that ran
// the same parse path (RGBA#equals is exact channel comparison).
function isColor(renderer, fg, hex) {
  const probe = new TextRenderable(renderer, { id: "probe", content: " ", fg: hex });
  return fg.equals(probe.fg);
}

async function mountTool(meta) {
  const setup = await createTestRenderer({ width: WIDTH, height: HEIGHT });
  const { renderer } = setup;
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
  const tool = createToolBlock({ renderer, TextRenderable, box, idPrefix: "blk" });
  tool.begin(meta);
  return { ...setup, tool };
}

test("a running tool shows a pulsing glyph + inline args in the run color", async () => {
  const { renderer, renderOnce, captureSpans, tool } = await mountTool({ name: "grep", args: "needle" });
  try {
    await renderOnce();
    let text = flatText(captureSpans());
    // args render INLINE after the name (opencode/codex), not on a separate line
    expect(text).toContain("grep needle");
    expect(text).toContain(STATUS_PULSE_FRAMES.tool[0]); // ◌ initial
    expect(isColor(renderer, tool.node.fg, STATUS.running)).toBe(true); // soft-orange while running

    // the external pulse animates the glyph in place
    tool.setGlyph(STATUS_PULSE_FRAMES.tool[1]);
    await renderOnce();
    expect(flatText(captureSpans())).toContain(`${STATUS_PULSE_FRAMES.tool[1]} grep needle`);
  } finally {
    renderer.destroy?.();
  }
});

test("a tool shows exactly ONE └ result corner; later deltas are ignored", async () => {
  const { renderer, renderOnce, captureSpans, tool } = await mountTool({ name: "glob", args: "*.mjs" });
  try {
    tool.append("42 files matched");
    tool.append("SHOULD BE IGNORED");
    await renderOnce();
    const text = flatText(captureSpans());
    expect(text).toContain("└ 42 files matched");
    expect(text).not.toContain("SHOULD BE IGNORED");
  } finally {
    renderer.destroy?.();
  }
});

test("a successful tool flips to ✓, recolors to ok, and appends a dim duration", async () => {
  const { renderer, renderOnce, captureSpans, tool } = await mountTool({ name: "read_file", args: "README.md" });
  try {
    tool.update({ status: "ok", duration: "0.2s" });
    await renderOnce();
    const text = flatText(captureSpans());
    expect(text).toContain("✓ read_file README.md · 0.2s");
    expect(isColor(renderer, tool.node.fg, STATUS.ok)).toBe(true);
  } finally {
    renderer.destroy?.();
  }
});

test("a failed tool flips to ✗ and recolors to error in place", async () => {
  const { renderer, renderOnce, captureSpans, tool } = await mountTool({ name: "bash", args: "pytest -q" });
  try {
    tool.append("AssertionError: expected 3");
    tool.update({ status: "error", duration: "1.4s" });
    await renderOnce();
    const text = flatText(captureSpans());
    expect(text).toContain("✗ bash pytest -q · 1.4s");
    expect(text).toContain("└ AssertionError: expected 3");
    expect(isColor(renderer, tool.node.fg, STATUS.error)).toBe(true);
  } finally {
    renderer.destroy?.();
  }
});
