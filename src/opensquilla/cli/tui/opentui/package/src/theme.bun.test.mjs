// Theme registry + live-switch regression tests.
//
// Guarantees: every theme supplies a complete, valid render-token set; theme
// resolution is forgiving (unknown -> default, case/space-insensitive); and a
// non-default theme actually paints its own background when rendered.
//
// Run with: bun test src/theme.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import {
  THEME,
  THEME_NAMES,
  PALETTES,
  DEFAULT_THEME,
  applyTheme,
  resolveThemeName,
  activeThemeName,
} from "./theme.mjs";
import { createComposer } from "./composer.mjs";

// The render tokens every block/composer consumer relies on.
const REQUIRED_TOKENS = [
  "brandAccent", "brandAccentSoft", "text", "muted", "detailText",
  "appBg", "overlayBg", "footerBg", "composerBorder", "composerDisabledBorder",
  "answerFrame", "thinkingAccent", "routeText", "promptAccent",
  "success", "warning", "error", "metricPositive",
];
const HEX = /^#[0-9a-fA-F]{6}$/;

test("every theme supplies a complete, valid-hex render-token set", () => {
  expect(THEME_NAMES.length).toBeGreaterThanOrEqual(6);
  for (const name of THEME_NAMES) {
    applyTheme(name);
    for (const token of REQUIRED_TOKENS) {
      expect(THEME[token], `${name}.${token}`).toBeDefined();
      expect(THEME[token], `${name}.${token}=${THEME[token]}`).toMatch(HEX);
    }
  }
  applyTheme(DEFAULT_THEME);
});

test("every semantic palette defines the OpenSquilla base tokens", () => {
  const base = ["bg", "bgSurface", "bgElevated", "text", "textMuted", "textDim",
    "accent", "accentSecondary", "ok", "warn", "danger", "info", "queued"];
  for (const name of THEME_NAMES) {
    for (const token of base) {
      expect(PALETTES[name][token], `${name}.${token}`).toMatch(HEX);
    }
  }
});

test("theme resolution is forgiving and defaults safely", () => {
  expect(resolveThemeName("midnight")).toBe("midnight");
  expect(resolveThemeName(" MIDNIGHT ")).toBe("midnight"); // trim + case-insensitive
  expect(resolveThemeName("nope")).toBe(DEFAULT_THEME);
  expect(resolveThemeName(undefined)).toBe(DEFAULT_THEME);
  expect(resolveThemeName("")).toBe(DEFAULT_THEME);
});

test("applyTheme mutates the live THEME and tracks the active name", () => {
  applyTheme("opensquilla-dark");
  expect(THEME.appBg).toBe("#121212");
  expect(activeThemeName()).toBe("opensquilla-dark");
  applyTheme("midnight");
  expect(THEME.appBg).toBe("#0B1021");
  expect(THEME.brandAccent).toBe("#EC6A1A");
  expect(activeThemeName()).toBe("midnight");
  applyTheme(DEFAULT_THEME);
});

test("a non-default theme paints its own footer background when rendered", async () => {
  applyTheme("ember"); // bgSurface (footerBg) = #1F1810 -> rgba(31,24,16)
  const { renderer, renderOnce, captureSpans } = await createTestRenderer({ width: 60, height: 12 });
  const inputBox = new BoxRenderable(renderer, {
    id: "input-region", position: "absolute", left: 0, right: 0, bottom: 0, height: 6,
    backgroundColor: THEME.footerBg,
  });
  renderer.root.add(inputBox);
  const overlayLayer = new BoxRenderable(renderer, {
    id: "overlay-layer", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    zIndex: 1000, shouldFill: false, visible: false,
  });
  renderer.root.add(overlayLayer);
  const conversationBox = new BoxRenderable(renderer, {
    id: "conversation", position: "absolute", left: 0, top: 0, right: 0, height: 6,
  });
  renderer.root.add(conversationBox);
  const composer = createComposer({
    renderer, BoxRenderable, TextRenderable, conversationBox, inputBox, overlayLayer,
    footerHeight: 6, sendHostMessage: () => {},
  });
  try { composer.install(); } catch { composer.rerender(); }
  await renderOnce();
  const frame = captureSpans();
  // ember footerBg = #1F1810 = rgb(31,24,16); read the footer margin cell bg.
  const line = frame.lines[12 - 3];
  let col = 0, bg = null;
  for (const span of line.spans) {
    const w = Math.max(1, span.width || 1);
    for (let i = 0; i < w; i += 1) { if (col === 0) bg = span.bg; col += 1; }
  }
  expect(bg).not.toBeNull();
  expect(bg.a).toBeGreaterThan(0); // opaque
  expect(Math.round(bg.r * 255)).toBe(31);
  expect(Math.round(bg.g * 255)).toBe(24);
  expect(Math.round(bg.b * 255)).toBe(16);
  renderer.destroy?.();
  applyTheme(DEFAULT_THEME);
});
