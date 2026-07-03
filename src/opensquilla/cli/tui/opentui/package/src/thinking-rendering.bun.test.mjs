// Renderer-level regressions for transient reasoning and intermediate rails.
//
// Must run under bun: @opentui/core/testing needs bun FFI.
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, MarkdownRenderable, TextRenderable } from "@opentui/core";

import { createTurnView } from "./turnView.mjs";
import { STATUS_PULSE_FRAMES } from "./theme.mjs";

function flatText(frame) {
  return frame.lines
    .map((line) => line.spans.map((span) => span.text).join(""))
    .join("\n");
}

async function createTurnHarness({ width = 52, height = 14 } = {}) {
  const setup = await createTestRenderer({ width, height });
  const { renderer } = setup;
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
    {
      renderer,
      BoxRenderable,
      TextRenderable,
      MarkdownRenderable,
      syntaxStyle: undefined,
      conversationBox,
    },
    "probe",
  );
  return { ...setup, turn };
}

function visibleLines(text) {
  return text.split("\n").filter((line) => line.trim());
}

test("reasoning marker is transient and disappears when the block ends", async () => {
  const { renderer, renderOnce, captureSpans, turn } = await createTurnHarness();
  try {
    turn.begin("r1", "reasoning", {});
    turn.append("r1", "private reasoning text");
    await renderOnce();
    expect(flatText(captureSpans())).toContain("Thinking");

    turn.refreshPulse(1);
    await renderOnce();
    expect(flatText(captureSpans())).toContain(`${STATUS_PULSE_FRAMES.thinking[1]} Thinking`);

    turn.end("r1");
    turn.begin("tool1", "tool", { name: "web_search", args: "" });
    await renderOnce();

    const text = flatText(captureSpans());
    expect(text).not.toContain("Thinking");
    expect(text).toContain("web_search");
  } finally {
    renderer.destroy?.();
  }
});

test("intermediate narration keeps the timeline rail on every rendered line", async () => {
  const { renderer, renderOnce, captureSpans, turn } = await createTurnHarness({
    width: 42,
    height: 14,
  });
  try {
    turn.begin("thinking1", "thinking", {});
    turn.append(
      "thinking1",
      "first intermediate line that is intentionally long\nsecond line should keep rail\nthird line should keep rail",
    );
    await renderOnce();

    const lines = visibleLines(flatText(captureSpans()));
    const narrationLines = lines.filter(
      (line) =>
        line.includes("first intermediate") ||
        line.includes("second line") ||
        line.includes("third line"),
    );

    expect(narrationLines.length).toBe(3);
    for (const line of narrationLines) {
      expect(line.trimStart()).toMatch(/^[│✻]/);
    }
    expect(narrationLines[1].trimStart().startsWith("│")).toBe(true);
    expect(narrationLines[2].trimStart().startsWith("│")).toBe(true);
  } finally {
    renderer.destroy?.();
  }
});
