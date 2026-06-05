export const TOOL_INDENT = " ";
export const CARD_RULE_LONG = "─".repeat(48);
export const CARD_RULE_SHORT = "─".repeat(8);
export const TIMELINE_WRAP_GUARD_CELLS = 6;

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
