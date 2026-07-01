// End-to-end completion-confirm behavior, driven through real keypresses:
//   - Enter on a highlighted slash command RUNS it in one keystroke (it used to
//     just insert the text and wait for a second Enter — "Tab adds a blank, the
//     command only appears after the next Enter").
//   - Tab completes the command (so you can still type arguments) without
//     submitting.
//
// Run with: bun test src/completion-submit.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import { createComposer } from "./composer.mjs";
import { applyTheme } from "./theme.mjs";

async function setupComposer() {
  applyTheme("opensquilla-dark");
  const sent = [];
  const { renderer } = await createTestRenderer({ width: 60, height: 12 });
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation", position: "absolute", left: 0, top: 0, right: 0, height: 6,
  });
  renderer.root.add(conversationBox);
  const inputBox = new BoxRenderable(renderer, {
    id: "input-region", position: "absolute", left: 0, right: 0, bottom: 0, height: 6,
  });
  renderer.root.add(inputBox);
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
  composer.setCompletionContext({
    catalog: [{ label: "/theme", insert_text: "/theme ", description: "List or switch the OpenTUI color theme." }],
  });
  return { renderer, composer, sent };
}

const press = (renderer, name, sequence = name) =>
  renderer.keyInput.emit("keypress", { name, sequence });
const type = (renderer, text) => {
  for (const ch of text) press(renderer, ch, ch);
};

test("Enter on the /theme suggestion runs it in one keystroke", async () => {
  const { renderer, sent } = await setupComposer();
  type(renderer, "/theme"); // the slash menu opens with /theme highlighted
  press(renderer, "return");

  const submits = sent.filter((m) => m.type === "input.submit");
  expect(submits.length).toBe(1); // exactly one Enter ran the command
  expect(submits[0].text).toBe("/theme "); // completed command was submitted
  renderer.destroy?.();
});

test("Tab on the /theme suggestion completes without submitting", async () => {
  const { renderer, sent } = await setupComposer();
  type(renderer, "/theme");
  press(renderer, "tab");

  // Tab completes (for typing arguments) — it must NOT submit on its own.
  expect(sent.some((m) => m.type === "input.submit")).toBe(false);
  renderer.destroy?.();
});
