import { THEME } from "../theme.mjs";
import { TOOL_INDENT, clipToCells, stripTerminalControls, timelineAvailCells } from "../primitives.mjs";

// The model's reasoning (extended-thinking) stream renders as a live PEEK: a
// pulsing "✻ Thinking · Ns" header with a rolling tail of the last few
// reasoning lines beneath it (dim — it is process, not the answer). When the
// reasoning ends the tail disappears and the header collapses to a single
// "✻ Thought for Ns" line, so long thinking gives live feedback while the
// finished transcript stays tidy. Providers that expose no reasoning stream
// never open this block; the composer's pulsing status pill covers them.
const TAIL_LINES = 3;

export function createReasoningBlock(ctx) {
  const { renderer, TextRenderable, box, idPrefix } = ctx;
  const headerId = `${idPrefix}-mark`;
  let header = null;
  const tailNodes = []; // rolling peek rows, newest last
  let text = "";
  let startedAt = null;
  let done = false;
  let glyph = "✻";

  const elapsedSeconds = () =>
    startedAt === null ? 0 : Math.max(0, Math.floor((Date.now() - startedAt) / 1000));

  function headerContent() {
    if (done) return `${TOOL_INDENT}✻ Thought for ${elapsedSeconds()}s`;
    const elapsed = elapsedSeconds();
    const timer = elapsed >= 2 ? ` · ${elapsed}s` : "";
    return `${TOOL_INDENT}${glyph} Thinking${timer}`;
  }

  function tailContent(line) {
    const prefix = `${TOOL_INDENT}  `;
    return `${prefix}${clipToCells(line, timelineAvailCells(prefix, renderer.terminalWidth))}`;
  }

  function tailLines() {
    const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
    return lines.slice(-TAIL_LINES);
  }

  function renderTail() {
    const lines = done ? [] : tailLines();
    // Reuse row nodes in place; grow/shrink to the current tail length.
    while (tailNodes.length > lines.length) {
      const node = tailNodes.pop();
      box.remove?.(node.id);
    }
    while (tailNodes.length < lines.length) {
      const node = new TextRenderable(renderer, {
        id: `${idPrefix}-t${tailNodes.length}`,
        content: "",
        fg: THEME.detailText,
      });
      box.add(node);
      tailNodes.push(node);
    }
    lines.forEach((line, i) => { tailNodes[i].content = tailContent(line); });
  }

  function setGlyph(next) {
    if (!header || done) return;
    glyph = next;
    // The pulse tick doubles as the live-seconds refresh for the header.
    header.content = headerContent();
    renderer.requestRender?.();
  }

  return {
    begin() {
      startedAt = Date.now();
      header = new TextRenderable(renderer, {
        id: headerId,
        content: headerContent(),
        fg: THEME.thinkingAccent,
      });
      box.add(header);
      renderer.requestRender?.();
    },
    append(delta) {
      if (done) return;
      text += stripTerminalControls(String(delta ?? ""));
      renderTail();
      renderer.requestRender?.();
    },
    update() {},
    setGlyph,
    // Collapse: drop the peek rows and settle the header into the one-line
    // record of how long the model thought.
    end() {
      done = true;
      renderTail();
      if (header) header.content = headerContent();
      renderer.requestRender?.();
    },
    // Re-clip the peek rows to the current width on resize.
    relayout() {
      renderTail();
    },
    // Live /theme switch: re-point the header and peek rows at the new tokens.
    recolor() {
      if (header) header.fg = THEME.thinkingAccent;
      for (const node of tailNodes) node.fg = THEME.detailText;
    },
  };
}
