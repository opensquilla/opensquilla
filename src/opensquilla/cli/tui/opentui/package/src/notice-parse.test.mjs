import assert from "node:assert/strict";
import test from "node:test";

import { NOTICE_LEVELS, isStructuredLine, parseNotice } from "./ansiNotice.mjs";

const ESC = "\u001b";

test("parseNotice strips ANSI and classifies the dominant severity level", () => {
  const cases = [
    // [raw, expected level, expected clean text]
    [`${ESC}[38;2;245;102;0mcompacting context...${ESC}[0m`, "accent", "compacting context..."],
    [`${ESC}[33mcompact: flush service is unavailable${ESC}[0m`, "warn", "compact: flush service is unavailable"],
    [`${ESC}[31mUnknown command. Use /help.${ESC}[0m`, "error", "Unknown command. Use /help."],
    [`${ESC}[32mStarted new session${ESC}[0m`, "success", "Started new session"],
    [`${ESC}[38;2;14;122;82mcompacted ok${ESC}[0m`, "success", "compacted ok"],
    [
      `${ESC}[38;2;245;102;0mcompact skipped${ESC}[0m ${ESC}[2malready within budget${ESC}[0m`,
      "accent",
      "compact skipped already within budget",
    ],
    ["plain status", "detail", "plain status"],
    [`${ESC}[2mdim only${ESC}[0m`, "detail", "dim only"],
  ];
  for (const [raw, level, text] of cases) {
    const result = parseNotice(raw);
    assert.equal(result.level, level, `level for ${JSON.stringify(raw)}`);
    assert.equal(result.text, text, `text for ${JSON.stringify(raw)}`);
    assert.ok(!/\u001b/.test(result.text), "no escape bytes survive (no compact:->act: clipping)");
  }
});

test("the most severe colored segment wins over a leading dim word", () => {
  const raw = `${ESC}[2mnote:${ESC}[0m ${ESC}[31mflush failed${ESC}[0m`;
  assert.equal(parseNotice(raw).level, "error");
});

test("every notice level has a glyph and a THEME color token", () => {
  for (const [name, spec] of Object.entries(NOTICE_LEVELS)) {
    assert.ok(spec.glyph, `${name} glyph`);
    assert.ok(spec.token, `${name} token`);
  }
});

test("isStructuredLine flags box-drawing borders so they skip the glyph", () => {
  assert.equal(isStructuredLine("│ model    deepseek │"), true);
  assert.equal(isStructuredLine("╭─ router ─╮"), true);
  assert.equal(isStructuredLine("compact skipped"), false);
});
