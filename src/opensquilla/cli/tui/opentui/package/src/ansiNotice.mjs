// Parse a Rich-rendered notice line (captured from the Python side's stdout in
// opentui mode) into clean text plus a single semantic severity level, so the
// host can render command notices INSIDE its frame in the active theme's colors
// instead of letting raw ANSI bleed onto the alternate screen.
//
// The Python redirect forwards one console line per notice.write message, still
// carrying Rich's ANSI styling. We strip the control bytes (no more "compact:" ->
// "act:" clipping) and classify the line's dominant foreground color into a
// theme-agnostic level. main.mjs maps the level onto the LIVE THEME tokens, so
// every theme — including light — gets legible, on-brand notices.

// level -> { glyph, token } where token names a THEME color read at render time.
export const NOTICE_LEVELS = Object.freeze({
  error: { glyph: "✗", token: "error" }, // ✗
  warn: { glyph: "⚠", token: "warning" }, // ⚠
  success: { glyph: "✓", token: "success" }, // ✓
  info: { glyph: "›", token: "routeText" }, // ›
  accent: { glyph: "›", token: "brandAccent" }, // › (brand-tinted)
  detail: { glyph: "·", token: "detailText" }, // ·
});

// Box-drawing / block ranges: a line with these is a table/panel border, so it
// renders without a glyph (the glyph only fronts plain status lines).
const BOX_DRAWING = /[─-╿▀-▟]/;

const ESC = String.fromCharCode(27);
const BEL = String.fromCharCode(7);
// CSI ... <final byte>, e.g. SGR (m) and cursor controls.
const CSI_RE = new RegExp(ESC + "\\[[0-9;?]*[ -/]*[@-~]", "g");
// OSC ... (BEL or ST) — hyperlinks etc.
const OSC_RE = new RegExp(ESC + "\\][\\s\\S]*?(?:" + BEL + "|" + ESC + "\\\\)", "g");
// SGR specifically, for color scanning.
const SGR_RE = new RegExp(ESC + "\\[([0-9;]*)m", "g");

// xterm 256-color index -> [r,g,b].
function xterm256ToRgb(n) {
  if (n < 16) {
    const base = [
      [0, 0, 0], [128, 0, 0], [0, 128, 0], [128, 128, 0],
      [0, 0, 128], [128, 0, 128], [0, 128, 128], [192, 192, 192],
      [128, 128, 128], [255, 0, 0], [0, 255, 0], [255, 255, 0],
      [0, 0, 255], [255, 0, 255], [0, 255, 255], [255, 255, 255],
    ];
    return base[n] ?? [128, 128, 128];
  }
  if (n >= 232) {
    const v = 8 + (n - 232) * 10;
    return [v, v, v];
  }
  const c = n - 16;
  const r = Math.floor(c / 36);
  const g = Math.floor((c % 36) / 6);
  const b = c % 6;
  const step = (x) => (x === 0 ? 0 : 55 + x * 40);
  return [step(r), step(g), step(b)];
}

// Standard 8/16-color SGR code -> level (no RGB hue math needed).
function basicCodeLevel(code) {
  switch (code) {
    case 31: case 91: return "error"; // red
    case 32: case 92: return "success"; // green
    case 33: case 93: return "warn"; // yellow
    case 34: case 94: case 36: case 96: return "info"; // blue / cyan
    case 35: case 95: return "accent"; // magenta -> brand-ish
    case 37: case 97: case 90: return "detail"; // white / gray
    default: return null;
  }
}

// RGB -> level by hue (handles Rich truecolor like the #F56600 brand accent).
function rgbLevel([r, g, b]) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max - min < 28) return "detail"; // near-neutral / gray
  const d = max - min;
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h = (((h * 60) % 360) + 360) % 360;
  if (h < 18 || h >= 330) return "error"; // red
  if (h < 40) return "accent"; // orange (brand)
  if (h < 70) return "warn"; // yellow
  if (h < 170) return "success"; // green
  if (h < 270) return "info"; // cyan / blue
  return "accent"; // magenta / purple
}

// Level priority when a line has several colored segments: the most "important"
// wins so a leading dim word never hides a trailing error.
const PRIORITY = { error: 5, warn: 4, success: 3, accent: 2, info: 1, detail: 0 };

// Scan SGR (...m) sequences for the dominant foreground level. Returns null when
// nothing is colored (Rich emitted plain text) so the caller can default.
function dominantLevel(raw) {
  let best = null;
  SGR_RE.lastIndex = 0;
  let m;
  while ((m = SGR_RE.exec(raw)) !== null) {
    const params = m[1].split(";").map((p) => (p === "" ? 0 : Number(p)));
    for (let i = 0; i < params.length; i++) {
      const code = params[i];
      let level = null;
      if (code === 38) {
        if (params[i + 1] === 5) {
          level = rgbLevel(xterm256ToRgb(params[i + 2] ?? 0));
          i += 2;
        } else if (params[i + 1] === 2) {
          level = rgbLevel([params[i + 2] ?? 0, params[i + 3] ?? 0, params[i + 4] ?? 0]);
          i += 4;
        }
      } else {
        level = basicCodeLevel(code);
      }
      if (level && (best === null || PRIORITY[level] > PRIORITY[best])) best = level;
    }
  }
  return best;
}

// Remove every escape sequence (OSC links, CSI/SGR, charset selects) and the
// carriage returns Rich can emit, leaving display text.
function stripAnsi(raw) {
  return String(raw)
    .replace(OSC_RE, "")
    .replace(CSI_RE, "")
    .replace(new RegExp(`${ESC}[()][0-9A-Za-z]`, "g"), "")
    .replace(/\r/g, "");
}

// Parse one captured notice line -> { text, level } (level always present).
export function parseNotice(raw) {
  return { text: stripAnsi(raw), level: dominantLevel(raw) ?? "detail" };
}

export function isStructuredLine(text) {
  return BOX_DRAWING.test(text);
}
