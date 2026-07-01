import assert from "node:assert/strict";
import test from "node:test";

import { copySelectionToClipboard, writeOsc52Clipboard } from "./primitives.mjs";

// OpenTUI gates its native OSC52 writer on a terminal capability probe that many
// capable terminals don't satisfy, so copy silently failed. These lock the
// direct-emit fallback that makes drag-select copy actually work.

function fakeOut() {
  const writes = [];
  return { writes, write: (s) => writes.push(s) };
}

const b64 = (s) => Buffer.from(s, "utf8").toString("base64");

test("writeOsc52Clipboard emits a bare OSC52 sequence outside tmux", () => {
  const out = fakeOut();
  const ok = writeOsc52Clipboard("hello", { env: {}, out });
  assert.equal(ok, true);
  assert.equal(out.writes.length, 1);
  assert.equal(out.writes[0], `\x1b]52;c;${b64("hello")}\x07`);
});

test("writeOsc52Clipboard wraps the sequence in tmux passthrough under TMUX", () => {
  const out = fakeOut();
  writeOsc52Clipboard("hi", { env: { TMUX: "/tmp/tmux-1/default,1,0" }, out });
  assert.equal(out.writes[0], `\x1bPtmux;\x1b\x1b]52;c;${b64("hi")}\x07\x1b\\`);
});

test("copy falls back to direct OSC52 when the native probe declines", () => {
  const out = fakeOut();
  // Terminal that OpenTUI reports as unsupported (isOsc52Supported=false): the old
  // code returned early here and copied nothing.
  const renderer = {
    isOsc52Supported: () => false,
    copyToClipboardOSC52: () => {
      throw new Error("must not be called when unsupported");
    },
  };
  const selection = { getSelectedText: () => "grep foo" };
  const restore = process.stdout.write.bind(process.stdout);
  process.stdout.write = out.write;
  try {
    const ok = copySelectionToClipboard(renderer, selection);
    assert.equal(ok, true);
  } finally {
    process.stdout.write = restore;
  }
  assert.equal(out.writes[0], `\x1b]52;c;${b64("grep foo")}\x07`);
});

test("copy uses the native managed path when the probe supports it", () => {
  let nativeArg = null;
  const renderer = {
    isOsc52Supported: () => true,
    copyToClipboardOSC52: (t) => {
      nativeArg = t;
      return true;
    },
  };
  const out = fakeOut();
  const restore = process.stdout.write.bind(process.stdout);
  process.stdout.write = out.write;
  try {
    const ok = copySelectionToClipboard(renderer, { getSelectedText: () => "abc" });
    assert.equal(ok, true);
  } finally {
    process.stdout.write = restore;
  }
  assert.equal(nativeArg, "abc"); // native path used
  assert.equal(out.writes.length, 0); // no direct emit
});

test("copy is a no-op for an empty selection", () => {
  const renderer = { isOsc52Supported: () => true, copyToClipboardOSC52: () => true };
  assert.equal(copySelectionToClipboard(renderer, { getSelectedText: () => "" }), false);
});
