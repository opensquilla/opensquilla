// Behavior tests for the conversation interaction helpers:
//   - isPinnedToBottom decides when streaming/new content should auto-follow the
//     bottom (vs the user having scrolled up to read history);
//   - copySelectionToClipboard mirrors an OpenTUI selection into the system
//     clipboard via OSC 52 (the select-to-copy fix, since a mouse-capturing TUI
//     never receives the terminal's Cmd/Ctrl+C).
//
// Pure logic, so it runs under `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";

import { clampFooterHeight, isPinnedToBottom, copySelectionToClipboard } from "./primitives.mjs";

test("clampFooterHeight keeps the footer within the terminal height", () => {
  assert.equal(clampFooterHeight(6, 24), 6); // normal terminal: full footer
  assert.equal(clampFooterHeight(6, 6), 6); // exact fit
  assert.equal(clampFooterHeight(6, 4), 4); // short pane: clamp to terminal (no overflow)
  assert.equal(clampFooterHeight(6, 2), 2);
  assert.equal(clampFooterHeight(6, 1), 1); // never below one row
  assert.equal(clampFooterHeight(6, 0), 6); // unknown/zero height -> fall back to full footer
  assert.equal(clampFooterHeight(6, undefined), 6);
});

test("isPinnedToBottom only follows when at/near the bottom", () => {
  // viewport 30, content 100 => maxTop 70
  assert.equal(isPinnedToBottom(70, 100, 30), true); // exactly at the bottom
  assert.equal(isPinnedToBottom(69, 100, 30), true); // within default slack (2)
  assert.equal(isPinnedToBottom(50, 100, 30), false); // scrolled up to read history
  assert.equal(isPinnedToBottom(0, 100, 30), false); // at the top
  // content shorter than the viewport is always "at the bottom"
  assert.equal(isPinnedToBottom(0, 10, 30), true);
});

test("copySelectionToClipboard copies selected text via OSC 52 when supported", () => {
  const copied = [];
  const renderer = {
    isOsc52Supported: () => true,
    copyToClipboardOSC52: (text) => {
      copied.push(text);
      return true;
    },
  };
  const result = copySelectionToClipboard(renderer, { getSelectedText: () => "hello world" });
  assert.equal(result, true);
  assert.deepEqual(copied, ["hello world"]);
});

test("copySelectionToClipboard is a no-op for an empty selection", () => {
  let copyCalls = 0;
  const renderer = {
    isOsc52Supported: () => true,
    copyToClipboardOSC52: () => {
      copyCalls += 1;
      return true;
    },
  };
  assert.equal(copySelectionToClipboard(renderer, { getSelectedText: () => "" }), false);
  assert.equal(copyCalls, 0);
});

test("copySelectionToClipboard falls back to direct OSC 52 on an unsupported terminal", () => {
  // The capability probe reports false even on many terminals that DO accept
  // OSC 52, so an unsupported result must fall back to emitting the sequence
  // directly rather than silently copying nothing. Capture stdout so the escape
  // bytes don't leak into the test runner's output.
  const restore = process.stdout.write.bind(process.stdout);
  const writes = [];
  process.stdout.write = (s) => {
    writes.push(s);
    return true;
  };
  let result;
  try {
    result = copySelectionToClipboard(
      { isOsc52Supported: () => false, copyToClipboardOSC52: () => true },
      { getSelectedText: () => "x" },
    );
  } finally {
    process.stdout.write = restore;
  }
  assert.equal(result, true);
  assert.equal(writes.length, 1);
  assert.ok(writes[0].includes("]52;c;"));
});
