// Light-theme answer-body legibility:
//   The markdown answer body is colored by the SyntaxStyle "default" token. A
//   bare SyntaxStyle.create() registers no "default", so unstyled paragraph text
//   gets fg:undefined and falls back to an invisible light foreground — the
//   answer looked blank under opensquilla-light. registerThemeStyles must give it
//   a theme-tracked color, and onThemeApplied must refresh it on a live switch.
//
// Run with: bun test src/light-theme-markdown.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { SyntaxStyle } from "@opentui/core";

import { registerThemeStyles } from "./syntaxTheme.mjs";
import { applyTheme, THEME, onThemeApplied } from "./theme.mjs";

const lum = (c) => 0.299 * c.r + 0.587 * c.g + 0.114 * c.b; // scale-free for comparisons

test("a bare SyntaxStyle has no 'default' style — reproduces the faint-text bug", async () => {
  await createTestRenderer({ width: 10, height: 4 }); // initialize the native render lib
  const s = SyntaxStyle.create();
  // This undefined is exactly why light-theme markdown body text was invisible.
  expect(s.getStyle("default")).toBeUndefined();
});

test("registerThemeStyles gives the body a theme-tracked, legible color", async () => {
  await createTestRenderer({ width: 10, height: 4 });
  const s = SyntaxStyle.create();

  applyTheme("opensquilla-light");
  registerThemeStyles(s, THEME);
  const light = s.getStyle("default");
  expect(light).toBeDefined();
  expect(light.fg).toBeDefined();
  const lightLum = lum(light.fg);

  applyTheme("opensquilla-dark");
  registerThemeStyles(s, THEME);
  const dark = s.getStyle("default");
  const darkLum = lum(dark.fg);

  // Body text inverts with the theme: light theme -> dark text (low luminance),
  // dark theme -> light text (high luminance). They must differ and invert.
  expect(darkLum).toBeGreaterThan(lightLum);
  applyTheme("opensquilla-dark"); // leave a stable default for other tests
});

test("onThemeApplied fires listeners after THEME is repopulated, and unsubscribes", () => {
  let seen = null;
  const off = onThemeApplied((_t, name) => {
    seen = name;
  });
  applyTheme("midnight");
  expect(seen).toBe("midnight");
  // THEME must already be the new palette when the listener runs.
  expect(THEME.appBg).toBe("#0B1021");

  off();
  applyTheme("opensquilla-dark");
  expect(seen).toBe("midnight"); // listener removed -> not called again
});
