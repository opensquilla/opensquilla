// Composer input hygiene: a single keystroke must only insert real text, never
// control bytes. Pressing Tab with no completion menu used to inject a literal
// "\t" that got submitted in the message; unhandled special keys (home/end/
// F-keys) likewise must not leak their ESC sequences into the input. Paste keeps
// its own handler, so multi-line / tab-containing pastes are unaffected.
//
// Run with: bun test src/composer-input.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import { createComposer } from "./composer.mjs";
import { applyTheme } from "./theme.mjs";

async function setupComposer() {
  applyTheme("opensquilla-dark");
  const sent = [];
  const { renderer } = await createTestRenderer({ width: 50, height: 10 });
  const mk = (id, height) => {
    const box = new BoxRenderable(renderer, {
      id, position: "absolute", left: 0, right: 0, bottom: 0, height,
    });
    renderer.root.add(box);
    return box;
  };
  const conversationBox = mk("conversation", 4);
  const inputBox = mk("input-region", 6);
  const overlayLayer = new BoxRenderable(renderer, {
    id: "overlay-layer", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    zIndex: 1000, shouldFill: false, visible: false,
  });
  renderer.root.add(overlayLayer);
  const composer = createComposer({
    renderer, BoxRenderable, TextRenderable, conversationBox, inputBox, overlayLayer,
    footerHeight: 6, sendHostMessage: (m) => sent.push(m),
  });
  try {
    composer.install();
  } catch {
    composer.rerender();
  }
  return { renderer, sent };
}

async function submittedAfter(keys) {
  const { renderer, sent } = await setupComposer();
  for (const key of keys) renderer.keyInput.emit("keypress", key);
  renderer.keyInput.emit("keypress", { name: "return" });
  const text = sent.find((m) => m.type === "input.submit")?.text;
  renderer.destroy?.();
  return text;
}

test("Tab with no completion menu does not insert a literal tab", async () => {
  const text = await submittedAfter([
    { name: "h", sequence: "h" },
    { name: "i", sequence: "i" },
    { name: "tab", sequence: "\t" },
  ]);
  expect(text).toBe("hi"); // no trailing control byte got submitted
});

test("unhandled special keys never leak control/escape bytes into the input", async () => {
  const text = await submittedAfter([
    { name: "a", sequence: "a" },
    { name: "home", sequence: "\u001b[H" }, // ESC sequence from an unhandled key
    { name: "b", sequence: "b" },
  ]);
  expect(text).toBe("ab");
});

test("normal printable typing (incl. space) is unaffected", async () => {
  const text = await submittedAfter(
    [..."hello world"].map((c) => ({ name: c === " " ? "space" : c, sequence: c })),
  );
  expect(text).toBe("hello world");
});

async function pastedThenSubmitted(text) {
  const { renderer, sent } = await setupComposer();
  renderer.keyInput.emit("paste", { bytes: new TextEncoder().encode(text) });
  renderer.keyInput.emit("keypress", { name: "return" });
  const submitted = sent.find((m) => m.type === "input.submit")?.text;
  renderer.destroy?.();
  return submitted;
}

test("pasted ANSI/terminal output is stripped of escape and control bytes", async () => {
  const submitted = await pastedThenSubmitted("a\u001b[31mred\u001b[0m b");
  expect(submitted).toBe("ared b"); // colors removed
  expect(submitted.includes("\u001b")).toBe(false); // no raw control bytes submitted
});

test("paste preserves newlines and tabs (multi-line / indented paste)", async () => {
  const submitted = await pastedThenSubmitted("line1\nline2\tindented");
  expect(submitted).toBe("line1\nline2\tindented");
});
