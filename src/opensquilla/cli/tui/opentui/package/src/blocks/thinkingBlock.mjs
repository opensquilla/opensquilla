import { THEME } from "../theme.mjs";
import { TOOL_INDENT, cellWidth, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";
import { destroyRenderable } from "../renderableLifecycle.mjs";

// Intermediate assistant narration is useful context, but it should not turn a
// completed turn into an unbounded wall of process prose. Keep a readable
// preview after completion and retain every source byte behind an explicit,
// deterministic expansion API. While the block is live, all narration remains
// visible so the UI never appears to swallow an in-flight update.
const COMPLETED_PREVIEW_ROWS = 6;

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
      const w = cellWidth(rest[cut], rest[cut + 1]);
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

export function createThinkingBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  const contentWidth = typeof ctx.contentWidth === "function"
    ? ctx.contentWidth
    : () => renderer.terminalWidth;
  let rawText = "";
  let done = false;
  let expanded = false;
  const rowNodes = [];
  let summaryNode = null;
  let hiddenLineCount = 0;

  function allRows() {
    // Strip only for display. rawText deliberately remains byte-for-byte equal
    // to the concatenated protocol deltas, including controls split across
    // delta boundaries, so expansion and diagnostics can never lose payload.
    const safe = stripTerminalControls(rawText).replace(/^\n+/, "");
    if (!safe) return [];
    const firstPrefix = `${TOOL_INDENT}✻ `;
    const avail = timelineAvailCells(firstPrefix, contentWidth());
    const rows = [];
    for (const line of safe.split("\n")) {
      for (const row of wrapToCells(line, avail)) rows.push(row);
    }
    return rows;
  }

  function insertAfter(node, previous) {
    const children = box.getChildren?.() ?? [];
    const index = previous ? children.indexOf(previous) : -1;
    box.add(node, index >= 0 ? index + 1 : undefined);
  }

  function reconcileRows(rows) {
    const firstPrefix = `${TOOL_INDENT}✻ `;
    const contPrefix = `${TOOL_INDENT}  `;
    const avail = timelineAvailCells(firstPrefix, contentWidth());
    while (rowNodes.length > rows.length) {
      const node = rowNodes.pop();
      destroyRenderable(box, node);
    }
    while (rowNodes.length < rows.length) {
      const index = rowNodes.length;
      const node = new TextRenderable(renderer, {
        id: `${idPrefix}-l${index}`,
        content: "",
        fg: done ? THEME.detailText : THEME.thinkingAccent,
      });
      insertAfter(node, rowNodes[index - 1] ?? null);
      rowNodes.push(node);
    }
    rows.forEach((row, index) => {
      rowNodes[index].content = `${index === 0 ? firstPrefix : contPrefix}${clipToCells(row, avail)}`;
      rowNodes[index].fg = done ? THEME.detailText : THEME.thinkingAccent;
    });
  }

  function render() {
    const rows = allRows();
    const collapse = done && !expanded && rows.length > COMPLETED_PREVIEW_ROWS;
    const visible = collapse ? rows.slice(0, COMPLETED_PREVIEW_ROWS) : rows;
    hiddenLineCount = collapse ? rows.length - visible.length : 0;
    reconcileRows(visible);

    if (hiddenLineCount > 0) {
      const suffix = hiddenLineCount === 1 ? "line" : "lines";
      const content = `${TOOL_INDENT}  ▸ ${hiddenLineCount} more ${suffix} · expand details`;
      if (!summaryNode) {
        summaryNode = new TextRenderable(renderer, {
          id: `${idPrefix}-summary`,
          content,
          fg: THEME.muted,
        });
        insertAfter(summaryNode, rowNodes.at(-1) ?? null);
      } else {
        summaryNode.content = content;
        summaryNode.fg = THEME.muted;
      }
    } else if (summaryNode) {
      destroyRenderable(box, summaryNode);
      summaryNode = null;
    }
    renderer.requestRender?.();
  }

  function toggleExpanded(force) {
    const next = typeof force === "boolean" ? force : !expanded;
    if (next === expanded) return expanded;
    expanded = next;
    render();
    return expanded;
  }

  return {
    get rawText() { return rawText; },
    get isExpanded() { return expanded; },
    get hiddenLineCount() { return hiddenLineCount; },
    begin(meta = {}) {
      const seed = meta?.text;
      if (seed !== undefined && seed !== null) rawText += String(seed);
      render();
    },
    append(delta) {
      rawText += String(delta ?? "");
      render();
    },
    update(patch = {}) {
      if (typeof patch.expanded === "boolean") toggleExpanded(patch.expanded);
    },
    end() {
      done = true;
      render();
    },
    toggleExpanded,
    relayout() { render(); },
    recolor() {
      for (const node of rowNodes) node.fg = done ? THEME.detailText : THEME.thinkingAccent;
      if (summaryNode) summaryNode.fg = THEME.muted;
    },
  };
}
