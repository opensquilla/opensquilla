export const TOOL_INDENT = " ";
export const CARD_RULE_SHORT = "─".repeat(8);
export const TIMELINE_WRAP_GUARD_CELLS = 6;
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
