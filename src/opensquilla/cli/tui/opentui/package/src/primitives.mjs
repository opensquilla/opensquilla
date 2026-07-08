export const TOOL_INDENT = " ";
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
// True when a scroll position is within `slack` rows of the bottom — i.e. the
// view should keep following new content as it streams in. When the user has
// scrolled up to read history this is false, so auto-follow never yanks them
// down. (stickyScroll alone does not re-follow while a child grows in place.)
export function isPinnedToBottom(scrollTop, scrollHeight, viewportHeight, slack = 2) {
  const maxTop = Math.max(0, scrollHeight - viewportHeight);
  return scrollTop >= maxTop - slack;
}

// Mirror an OpenTUI selection into the system clipboard via OSC 52. A
// mouse-capturing TUI never receives the terminal's Cmd/Ctrl+C, so the renderer's
// "selection" event (fired on a completed drag-select) is the copy trigger.
// Guarded by isOsc52Supported so unsupported terminals are a silent no-op rather
// than emitting stray escape bytes. Returns whether bytes were written.
export function copySelectionToClipboard(renderer, selection) {
  const text =
    selection?.getSelectedText?.() ?? renderer?.getSelection?.()?.getSelectedText?.() ?? "";
  if (!text || !renderer?.isOsc52Supported?.()) return false;
  return renderer.copyToClipboardOSC52?.(text) ?? false;
}

// Zero-width: combining marks attach to the previous cell, and the
// ZWSP/ZWNJ/ZWJ joiners and variation selectors are invisible — none of
// them advance the terminal cursor, so counting them as 1 would drift the
// caret on composed text (e+U+0301, emoji families, flag pairs).
const ZERO_WIDTH_RE = /[\p{Mn}\p{Me}\u200b-\u200d\ufe00-\ufe0f]/u;
// Double-width: the East Asian wide/fullwidth ranges plus pictographs that
// DEFAULT to emoji presentation (mainstream terminals render those over two
// cells, wcwidth-style). Text-presentation pictographs (© ® ™ ↔ ♥ ⚠ …) render
// in ONE cell unless an explicit VS16 follows, so the broader
// Extended_Pictographic class would count them a cell wider than the terminal
// draws them and drift the caret.
const WIDE_RE =
  /[ᄀ-ᅟ〈〉⺀-꓏가-힣豈-﫿︐-︙︰-﹯＀-｠￠-￦]|\p{Emoji_Presentation}|[\u{1f300}-\u{1faff}]/u;
// VS16 (U+FE0F) forces emoji presentation: a narrow pictograph followed by it
// renders wide. The selector itself stays zero-width (ZERO_WIDTH_RE); the
// extra cell is charged to the base character via the `next` lookahead.
const VS16 = "\ufe0f";
const PICTOGRAPH_RE = /\p{Extended_Pictographic}/u;

export function cellWidth(char, next) {
  if (ZERO_WIDTH_RE.test(char)) return 0;
  if (WIDE_RE.test(char)) return 2;
  return next === VS16 && PICTOGRAPH_RE.test(char) ? 2 : 1;
}

export function textWidth(text) {
  const chars = Array.from(text);
  let width = 0;
  for (let i = 0; i < chars.length; i += 1) width += cellWidth(chars[i], chars[i + 1]);
  return width;
}

export function clipToCells(text, cells) {
  if (textWidth(text) <= cells) return text;
  const chars = Array.from(text);
  const budget = Math.max(1, cells - 1); // reserve one cell for the ellipsis
  let out = "";
  let used = 0;
  for (let i = 0; i < chars.length; i += 1) {
    const w = cellWidth(chars[i], chars[i + 1]);
    if (used + w > budget) break;
    out += chars[i];
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
