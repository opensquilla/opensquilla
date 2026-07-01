export const TOOL_INDENT = " ";
export const CARD_RULE_SHORT = "─".repeat(8);
export const TIMELINE_WRAP_GUARD_CELLS = 6;
// A single codex-style result-preview corner under a tool row, and the dim
// separator before a completed tool's duration (e.g. "✓ grep foo · 0.2s").
export const RESULT_CORNER = "└ ";
export const DURATION_SEP = " · ";

// Clamp the footer height to the terminal: never taller than the screen (a short
// pane would otherwise overflow the fixed-height footer and corrupt the layout),
// never less than one row.
export function clampFooterHeight(footerHeight, terminalHeight) {
  return Math.max(1, Math.min(footerHeight, Number(terminalHeight) || footerHeight));
}
// Turn boxes pad 1 cell each side; card headers/bodies start at content column 0.
const CARD_CONTENT_INSET = 2;

// A card header rule ("╭─ <label> ───…") that fills to the turn's content width so
// it aligns with the full-width card body below it, instead of a fixed length that
// looks stranded on wide terminals and overflows narrow ones. (textWidth is a
// hoisted function declaration below.)
export function cardHeaderRule(label, terminalWidth) {
  const prefix = `╭─ ${label} `;
  const width = Math.max(textWidth(prefix) + 4, (terminalWidth ?? 80) - CARD_CONTENT_INSET);
  return prefix + "─".repeat(width - textWidth(prefix));
}

// True when a scroll position is within `slack` rows of the bottom — i.e. the
// view should keep following new content as it streams in. When the user has
// scrolled up to read history this is false, so auto-follow never yanks them
// down. (stickyScroll alone does not re-follow while a child grows in place.)
export function isPinnedToBottom(scrollTop, scrollHeight, viewportHeight, slack = 2) {
  const maxTop = Math.max(0, scrollHeight - viewportHeight);
  return scrollTop >= maxTop - slack;
}

// Emit an OSC 52 clipboard-write sequence directly to the terminal. This is the
// fallback for when OpenTUI's native path declines (see copySelectionToClipboard).
// OSC 52 is write-only: a terminal that doesn't understand it ignores the bytes,
// so emitting unconditionally here is safe. tmux only forwards escape sequences
// wrapped in its passthrough envelope (and needs `set -g set-clipboard on` +
// `set -g allow-passthrough on`).
export function writeOsc52Clipboard(text, { env = process.env, out = process.stdout } = {}) {
  try {
    const b64 = Buffer.from(String(text), "utf8").toString("base64");
    let seq = `\x1b]52;c;${b64}\x07`;
    if (env?.TMUX) seq = `\x1bPtmux;\x1b${seq}\x1b\\`;
    out.write(seq);
    return true;
  } catch {
    return false;
  }
}

// Mirror an OpenTUI selection into the system clipboard via OSC 52. A
// mouse-capturing TUI never receives the terminal's Cmd/Ctrl+C, so the renderer's
// "selection" event (fired on a completed drag-select) is the copy trigger.
//
// OpenTUI's own copyToClipboardOSC52 (and isOsc52Supported) gate on a terminal
// capability PROBE — getTerminalCapabilities().osc52 — which many terminals that
// actually accept OSC 52 (and tmux / embedded terminals) don't advertise, so the
// native path silently no-ops and copy looks broken. Try the native, managed
// path first; if the probe declined it, emit OSC 52 ourselves. Returns whether
// bytes were written.
export function copySelectionToClipboard(renderer, selection) {
  const text =
    selection?.getSelectedText?.() ?? renderer?.getSelection?.()?.getSelectedText?.() ?? "";
  if (!text) return false;
  if (renderer?.isOsc52Supported?.() && renderer.copyToClipboardOSC52?.(text)) return true;
  return writeOsc52Clipboard(text);
}

export function cellWidth(char) {
  return /[ᄀ-ᅟ〈〉⺀-꓏가-힣豈-﫿︐-︙︰-﹯＀-｠￠-￦]/u.test(char)
    ? 2
    : 1;
}

export function textWidth(text) {
  let width = 0;
  for (const char of Array.from(text)) width += cellWidth(char);
  return width;
}

export function clipToCells(text, cells) {
  if (textWidth(text) <= cells) return text;
  const budget = Math.max(1, cells - 1); // reserve one cell for the ellipsis
  let out = "";
  let used = 0;
  for (const char of Array.from(text)) {
    const w = cellWidth(char);
    if (used + w > budget) break;
    out += char;
    used += w;
  }
  return `${out}…`;
}

export function stripTerminalControls(text) {
  return text
    .replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|P[^\x1b]*\x1b\\|[@-Z\\-_])/g, "")
    .replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
}

export function timelineAvailCells(prefix, terminalWidth) {
  return Math.max(8, (terminalWidth ?? 80) - textWidth(prefix) - TIMELINE_WRAP_GUARD_CELLS);
}
