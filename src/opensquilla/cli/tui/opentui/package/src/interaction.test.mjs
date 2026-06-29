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

import { isPinnedToBottom, copySelectionToClipboard } from "./primitives.mjs";

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

test("copySelectionToClipboard is a no-op for empty selection or unsupported terminal", () => {
  let copyCalls = 0;
  const base = {
    copyToClipboardOSC52: () => {
      copyCalls += 1;
      return true;
    },
  };
  // empty selection -> nothing copied
  assert.equal(
    copySelectionToClipboard({ ...base, isOsc52Supported: () => true }, { getSelectedText: () => "" }),
    false,
  );
  // OSC 52 unsupported terminal -> nothing copied (no stray escape bytes)
  assert.equal(
    copySelectionToClipboard({ ...base, isOsc52Supported: () => false }, { getSelectedText: () => "x" }),
    false,
  );
  assert.equal(copyCalls, 0);
});
