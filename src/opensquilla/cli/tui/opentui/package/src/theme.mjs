// Multi-theme palette for the OpenTUI footer host.
//
// Each theme is an OpenSquilla SEMANTIC palette using the same token names as the
// web UI design system (src/assets/base.css): bg / surfaces, text tints, the
// brand accent family, and the run-state hues (ok / warn / danger / info /
// queued). The host's render tokens are DERIVED from these (see toTokens), so
// every theme is internally consistent and on-brand by construction — adding a
// theme is just supplying one semantic palette.
//
// opensquilla-dark / -light are mirrored verbatim from the web UI; the rest are
// distinct on-brand aesthetics that keep the orange accent family and the
// semantic run-state structure. All foregrounds clear WCAG AA on their own bg.

export const PALETTES = Object.freeze({
  // Canonical — verbatim from opensquilla-webui/src/assets/base.css.
  "opensquilla-dark": {
    bg: "#121212", bgSurface: "#1A1A1B", bgElevated: "#232325",
    text: "#ECECEC", textMuted: "#A6A6A8", textDim: "#878789",
    accent: "#EC6A1A", accentSecondary: "#FF8A4C",
    ok: "#39D7A2", warn: "#E8B23A", danger: "#FF6B6B", info: "#56C2E6", queued: "#8C7DF2",
  },
  "opensquilla-light": {
    bg: "#F7F7F8", bgSurface: "#FFFFFF", bgElevated: "#F0F0F2",
    text: "#18181A", textMuted: "#56565A", textDim: "#6C6C70",
    accent: "#B0440A", accentSecondary: "#DD6224",
    ok: "#0E7A52", warn: "#8A6410", danger: "#C2382E", info: "#1E6E8C", queued: "#5A48C0",
  },
  // Deep indigo night — cool and calm, brand orange for warmth.
  midnight: {
    bg: "#0B1021", bgSurface: "#121831", bgElevated: "#1A2342",
    text: "#DCE3F2", textMuted: "#93A0C0", textDim: "#6E7BA0",
    accent: "#EC6A1A", accentSecondary: "#FF9A52",
    ok: "#4FD6B0", warn: "#F0C674", danger: "#FF6B8A", info: "#6AB7FF", queued: "#A78BFA",
  },
  // Warm charcoal/amber — cozy, orange-forward.
  ember: {
    bg: "#16110C", bgSurface: "#1F1810", bgElevated: "#2A2015",
    text: "#F5ECE0", textMuted: "#C2AD92", textDim: "#9A856C",
    accent: "#FF7A1A", accentSecondary: "#FFA45C",
    ok: "#8BD88F", warn: "#F6C177", danger: "#FF7B6B", info: "#E0A878", queued: "#C9A0FF",
  },
  // Cool neutral gray-blue — understated and professional.
  slate: {
    bg: "#15181C", bgSurface: "#1C2026", bgElevated: "#252B33",
    text: "#E2E6EB", textMuted: "#99A2AE", textDim: "#727B86",
    accent: "#EC6A1A", accentSecondary: "#FF8A4C",
    ok: "#5FB89A", warn: "#D7B86A", danger: "#E47C7C", info: "#6FA8C9", queued: "#9384C7",
  },
  // Maximum contrast on pure black — accessibility-first.
  "high-contrast": {
    bg: "#000000", bgSurface: "#0B0B0B", bgElevated: "#151515",
    text: "#FFFFFF", textMuted: "#D0D0D0", textDim: "#ABABAB",
    accent: "#FF8A1F", accentSecondary: "#FFB266",
    ok: "#3DF0A8", warn: "#FFD24A", danger: "#FF5C5C", info: "#5AC8FF", queued: "#BB9CFF",
  },
  // Nordic polar night — recognizable cool palette with the brand accent.
  nord: {
    bg: "#2E3440", bgSurface: "#3B4252", bgElevated: "#434C5E",
    text: "#ECEFF4", textMuted: "#C0C7D4", textDim: "#9AA3B4",
    accent: "#EC6A1A", accentSecondary: "#FF9A52",
    ok: "#A3BE8C", warn: "#EBCB8B", danger: "#BF616A", info: "#88C0D0", queued: "#B48EAD",
  },
  // Near-monochrome — the orange accent is the only saturated hue.
  mono: {
    bg: "#0F0F0F", bgSurface: "#181818", bgElevated: "#222222",
    text: "#EAEAEA", textMuted: "#9A9A9A", textDim: "#6E6E6E",
    accent: "#EC6A1A", accentSecondary: "#FF8A4C",
    ok: "#A7C2B0", warn: "#C9B98A", danger: "#CE9A9A", info: "#9FB3C0", queued: "#B0A6C8",
  },
});

export const DEFAULT_THEME = "opensquilla-dark";
export const THEME_NAMES = Object.freeze(Object.keys(PALETTES));

// Derive the host's render tokens from an OpenSquilla semantic palette. This is
// the single source of how a theme maps onto the UI, so all themes are coherent.
function toTokens(p) {
  return {
    // Brand
    brandAccent: p.accent,
    brandAccentSoft: p.accentSecondary,
    // Neutrals
    text: p.text,
    muted: p.textMuted,
    detailText: p.textDim,
    // Opaque surfaces (the UI owns its background on every surface)
    appBg: p.bg,
    overlayBg: p.bgElevated,
    footerBg: p.bgSurface,
    // Chrome
    composerBorder: p.accent,
    composerDisabledBorder: p.textDim,
    // Roles
    answerFrame: p.accent,
    thinkingAccent: p.queued,
    routeText: p.info,
    promptAccent: p.textDim,
    // Semantic status triad + savings metric
    success: p.ok,
    warning: p.warn,
    error: p.danger,
    metricPositive: p.ok,
  };
}

export function resolveThemeName(name) {
  const n = String(name ?? "").trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(PALETTES, n) ? n : DEFAULT_THEME;
}

// Live, mutable active-theme token set. Blocks and the composer read THEME.<token>
// at render time, so applyTheme() repopulates this object IN PLACE and a re-render
// recolors the UI without recreating any imports.
export const THEME = {};
let activeTheme = DEFAULT_THEME;

// Listeners fired AFTER THEME is repopulated, so host-owned derived state that is
// NOT a THEME token (e.g. the markdown SyntaxStyle) can refresh on every live
// /theme switch. A listener must never throw — theming must not be breakable.
const _themeListeners = new Set();

export function onThemeApplied(listener) {
  _themeListeners.add(listener);
  return () => _themeListeners.delete(listener);
}

export function applyTheme(name) {
  const resolved = resolveThemeName(name);
  Object.assign(THEME, toTokens(PALETTES[resolved]));
  activeTheme = resolved;
  for (const listener of _themeListeners) {
    try {
      listener(THEME, resolved);
    } catch {
      // A faulty listener must not break theme application.
    }
  }
  return resolved;
}

export function activeThemeName() {
  return activeTheme;
}

// Populate THEME at import so every consumer sees a complete token set.
applyTheme(DEFAULT_THEME);

export const STATUS_PULSE_FRAMES = Object.freeze({
  thinking: ["∙", "•", "●", "•"],
  tool: ["◌", "◔", "◑", "◕"],
  output: ["◇", "◆", "◇", "◆"],
});
