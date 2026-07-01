// Notice rendering: command notices captured from Python render INSIDE the host
// frame as a severity glyph + theme-colored line (never raw ANSI on the
// terminal). Verifies the exact recipe main.mjs's notice handler uses, including
// cross-theme color correctness (the same notice recolors under a light theme).
//
// Run with: bun test src/notice-render.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import { parseNotice, isStructuredLine, NOTICE_LEVELS } from "./ansiNotice.mjs";
import { TOOL_INDENT } from "./primitives.mjs";
import { applyTheme, THEME } from "./theme.mjs";

const ESC = "\u001b";

// Mirror of main.mjs's notice.write handler so the rendering recipe is verified
// against the real OpenTUI text layer.
function renderNotice(renderer, conversationBox, rawText, idx) {
  const { text, level } = parseNotice(rawText);
  if (!text.trim()) return null;
  const spec = NOTICE_LEVELS[level] ?? NOTICE_LEVELS.detail;
  const fg = THEME[spec.token] ?? THEME.detailText;
  const content = isStructuredLine(text)
    ? `${TOOL_INDENT}${text}`
    : `${TOOL_INDENT}${spec.glyph} ${text}`;
  const node = new TextRenderable(renderer, { id: `notice-${idx}`, content, fg });
  conversationBox.add(node);
  return { content, level };
}

const rgb = (c) => [Math.round(c.r * 255), Math.round(c.g * 255), Math.round(c.b * 255)];

async function renderNotices(width, lines) {
  const { renderer, renderOnce, captureSpans } = await createTestRenderer({ width, height: 12 });
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation", position: "absolute", left: 0, top: 0, right: 0, height: 12,
    flexDirection: "column",
  });
  renderer.root.add(conversationBox);
  lines.forEach((raw, i) => renderNotice(renderer, conversationBox, raw, i));
  await renderOnce();
  const frame = captureSpans();
  return { renderer, frame };
}

const lineText = (line) => line.spans.map((s) => s.text).join("");
const findLine = (frame, needle) => frame.lines.find((l) => lineText(l).includes(needle));

test("notices render with a severity glyph, clean text, and theme color", async () => {
  applyTheme("opensquilla-dark");
  const { renderer, frame } = await renderNotices(70, [
    `${ESC}[31mUnknown command. Use /help.${ESC}[0m`,
    `${ESC}[38;2;245;102;0mcompacting context...${ESC}[0m`,
    `${ESC}[32mStarted new session${ESC}[0m`,
  ]);
  const all = frame.lines.map(lineText).join("\n");
  expect(all).toContain("✗ Unknown command. Use /help."); // error glyph + clean text
  expect(all).toContain("› compacting context..."); // accent (brand) glyph
  expect(all).toContain("✓ Started new session"); // success glyph
  expect(all).not.toContain("[31m"); // no raw ANSI survives -> no compact:->act: clipping

  // The error line is painted THEME.error (#FF6B6B = 255,107,107 on dark).
  const errLine = findLine(frame, "Unknown command");
  const span = errLine.spans.find((s) => s.text.trim().length > 0);
  expect(rgb(span.fg)).toEqual([255, 107, 107]);
  renderer.destroy?.();
});

test("the same notice recolors for a light theme (legible on light bg)", async () => {
  applyTheme("opensquilla-light");
  const { renderer, frame } = await renderNotices(70, [
    `${ESC}[31mUnknown command. Use /help.${ESC}[0m`,
  ]);
  const errLine = findLine(frame, "Unknown command");
  const span = errLine.spans.find((s) => s.text.trim().length > 0);
  // light THEME.error = #C2382E = 194,56,46 (a dark red, legible on the light bg)
  expect(rgb(span.fg)).toEqual([194, 56, 46]);
  renderer.destroy?.();
  applyTheme("opensquilla-dark");
});

test("table/panel border lines render without a glyph", async () => {
  applyTheme("opensquilla-dark");
  const { renderer, frame } = await renderNotices(70, ["│ model   deepseek-v4 │"]);
  const line = findLine(frame, "model");
  const text = lineText(line);
  expect(text).toContain("│ model   deepseek-v4 │");
  expect(text).not.toContain("·"); // structured lines skip the glyph
  renderer.destroy?.();
});
