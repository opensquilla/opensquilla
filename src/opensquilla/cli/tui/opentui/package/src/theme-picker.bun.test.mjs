// Theme picker overlay tests:
//   - themePickerKeyAction maps keys to navigate(preview)/confirm/cancel and is
//     modal (swallows every other key while open);
//   - openThemePicker renders a titled panel listing every theme with the active
//     one marked — a real overlay panel, not stray scrollback text.
//
// Run with: bun test src/theme-picker.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import { createComposer, themePickerKeyAction } from "./composer.mjs";
import { THEME_NAMES, applyTheme } from "./theme.mjs";

test("themePickerKeyAction navigates, confirms, cancels, and is modal", () => {
  const picker = { active: true, names: ["a", "b", "c"], selected: 1 };
  expect(themePickerKeyAction(picker, "up")).toMatchObject({ action: "preview", selected: 0 });
  expect(themePickerKeyAction(picker, "down")).toMatchObject({ action: "preview", selected: 2 });
  // clamps at the ends
  expect(themePickerKeyAction({ ...picker, selected: 2 }, "down")).toMatchObject({ selected: 2 });
  expect(themePickerKeyAction({ ...picker, selected: 0 }, "up")).toMatchObject({ selected: 0 });
  expect(themePickerKeyAction(picker, "return")).toMatchObject({ action: "confirm" });
  expect(themePickerKeyAction(picker, "escape")).toMatchObject({ action: "cancel" });
  // every other key is swallowed (modal) so it never leaks into the input
  expect(themePickerKeyAction(picker, "x")).toMatchObject({ handled: true, action: "none" });
  // inactive picker passes keys through
  expect(themePickerKeyAction({ active: false }, "up")).toMatchObject({ handled: false });
});

test("openThemePicker renders a titled panel listing every theme, active one marked", async () => {
  applyTheme("opensquilla-dark");
  const { renderer, renderOnce, captureSpans } = await createTestRenderer({ width: 50, height: 20 });
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation", position: "absolute", left: 0, top: 0, right: 0, height: 14,
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
    footerHeight: 6, sendHostMessage: () => {},
  });
  try {
    composer.install();
  } catch {
    composer.rerender();
  }

  composer.openThemePicker();
  await renderOnce();
  const text = captureSpans()
    .lines.map((line) => line.spans.map((span) => span.text).join(""))
    .join("\n");

  for (const name of THEME_NAMES) expect(text).toContain(name); // every theme listed
  expect(text).toContain("theme"); // panel title
  expect(text).toContain("› opensquilla-dark"); // active theme marked
  expect(text.toLowerCase()).toContain("preview"); // the key hint
  renderer.destroy?.();
});

test("picker survives footer re-renders (pulse tick) instead of flashing away", async () => {
  // Regression: a footer re-render (pulse tick while a turn streams, router
  // update, keystroke) ran renderCompletionMenu -> clearOverlay, wiping the
  // picker while it stayed modally active — picker flashed once then the TUI
  // looked frozen (keys swallowed by an invisible modal). It must stay mounted.
  applyTheme("opensquilla-dark");
  const { renderer, renderOnce, captureSpans } = await createTestRenderer({ width: 50, height: 20 });
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation", position: "absolute", left: 0, top: 0, right: 0, height: 14,
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
    footerHeight: 6, sendHostMessage: () => {},
  });
  try {
    composer.install();
  } catch {
    composer.rerender();
  }

  composer.openThemePicker();
  // Simulate footer re-renders that previously wiped the picker.
  composer.rerender();
  composer.rerender();
  await renderOnce();
  const text = captureSpans()
    .lines.map((line) => line.spans.map((span) => span.text).join(""))
    .join("\n");
  expect(text).toContain("theme"); // panel title still present
  expect(text).toContain("midnight"); // theme rows still present after re-renders
  renderer.destroy?.();
});
