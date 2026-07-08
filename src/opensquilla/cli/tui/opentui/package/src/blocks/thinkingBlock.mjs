import { THEME } from "../theme.mjs";
import { TOOL_INDENT, cellWidth, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

// Greedy soft-wrap a logical line into rows of at most `cells` columns,
// breaking after the last space that fits so words stay whole; a single
// overwide word hard-breaks at the budget so wrapping always makes progress.
function wrapToCells(line, cells) {
  const budget = Math.max(1, cells);
  const rows = [];
  let rest = Array.from(line);
  while (rest.length) {
    let used = 0;
    let cut = 0;
    let lastSpace = -1;
    while (cut < rest.length) {
      const w = cellWidth(rest[cut]);
      if (used + w > budget) break;
      used += w;
      cut += 1;
      if (rest[cut - 1] === " ") lastSpace = cut;
    }
    if (cut >= rest.length) {
      rows.push(rest.join(""));
      break;
    }
    const breakAt = lastSpace > 0 ? lastSpace : Math.max(1, cut);
    rows.push(rest.slice(0, breakAt).join("").trimEnd());
    rest = rest.slice(breakAt);
    while (rest.length && rest[0] === " ") rest.shift();
  }
  return rows.length ? rows : [""];
}

// Thinking renders incrementally as reasoning streams in. Each append re-lays
// the visible lines in place (purple ✻, no card) so the model's thinking
// scrolls live rather than appearing all at once when the block closes.
export function createThinkingBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  let text = "";
  const nodes = new Map(); // id -> row node, for in-place update/recolor (no reordering)

  function render() {
    const trimmed = stripTerminalControls(text).replace(/^\n+/, "");
    if (!trimmed) return;
    // The turn card's left border supplies the gutter; the first visual row
    // carries the ✻ marker and every other row — a wrapped continuation or a
    // later logical line — indents to align under it. Long lines soft-wrap
    // into continuation rows so no narration is lost to the viewport edge
    // (both prefixes are 3 cells, so one budget serves every row).
    const firstPrefix = `${TOOL_INDENT}✻ `;
    const contPrefix = `${TOOL_INDENT}  `;
    const avail = timelineAvailCells(firstPrefix, renderer.terminalWidth);
    const rows = [];
    for (const line of trimmed.split("\n")) {
      for (const row of wrapToCells(line, avail)) rows.push(row);
    }
    rows.forEach((row, i) => {
      // clipToCells is a no-op after the wrap; it guards a row against any
      // width drift between wrap-time and render-time cell accounting.
      const content = `${i === 0 ? firstPrefix : contPrefix}${clipToCells(row, avail)}`;
      const id = `${idPrefix}-l${i}`;
      const existing = nodes.get(id);
      if (existing) {
        // Update the node IN PLACE. box.remove()+box.add() would re-append the
        // row after any later blocks in the shared card body — reordering the
        // transcript — and would churn one renderable per row per delta.
        existing.content = content;
      } else {
        const n = new TextRenderable(renderer, { id, content, fg: THEME.thinkingAccent });
        // Insert directly AFTER the previous row node. The card body is shared
        // by every in-card block, so once later blocks (tool rows, the answer)
        // exist, a plain append would mount rows that only appear at a
        // narrower relayout — a resize-shrink re-wrap grows the row count —
        // BELOW those blocks, splitting the narration around them.
        const prev = i > 0 ? nodes.get(`${idPrefix}-l${i - 1}`) : null;
        const prevIndex = prev ? box.getChildren().indexOf(prev) : -1;
        box.add(n, prevIndex >= 0 ? prevIndex + 1 : undefined);
        nodes.set(id, n);
      }
    });
    // A re-wrap at a wider terminal can shrink the row count; drop the orphans.
    for (let i = rows.length; nodes.has(`${idPrefix}-l${i}`); i += 1) {
      box.remove?.(`${idPrefix}-l${i}`);
      nodes.delete(`${idPrefix}-l${i}`);
    }
    renderer.requestRender?.();
  }

  return {
    begin() {},
    append(delta) { text += String(delta); render(); },
    update() {},
    end() {},
    // Re-wrap every row from the raw text at the current terminal width, so a
    // resize re-flows narration instead of leaving rows wrapped or clipped to
    // the old width.
    relayout() { render(); },
    // Live /theme switch: re-point the existing row nodes at the updated accent.
    recolor() { for (const n of nodes.values()) n.fg = THEME.thinkingAccent; },
  };
}
