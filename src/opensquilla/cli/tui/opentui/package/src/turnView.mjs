import { createBlock } from "./blockRegistry.mjs";
import { STATUS_PULSE_FRAMES, THEME } from "./theme.mjs";
import { TOOL_INDENT, stripTerminalControls } from "./primitives.mjs";

// Block kinds that render OUTSIDE the assistant's single per-turn card: the
// prompt is the user's own compact row and the usage summary folds into the
// card footer. Everything else — answer markdown, intermediate narration, tool
// calls, the reasoning marker, errors, and any kind this host does not know yet
// (a newer Python may add block kinds) — shares ONE continuous left-border
// gutter so a multi-step turn reads as one assistant block (opencode/codex
// style) instead of a stack of repeated cards. Unknown kinds default INTO the
// card so a protocol addition can never seal it mid-turn; only the known
// trailing kind (usage) closes it.
const OUT_OF_CARD_KINDS = new Set(["prompt", "usage"]);

export function isOutOfCardKind(kind) {
  return OUT_OF_CARD_KINDS.has(kind);
}

export function createTurnView(deps, id) {
  const { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, conversationBox } = deps;
  // marginTop gives each turn a blank line of vertical rhythm so turns read as
  // distinct groups (proximity) and the conversation has room to breathe.
  const box = new BoxRenderable(renderer, { id: `turn-${id}`, flexDirection: "column", marginTop: 1, paddingLeft: 1, paddingRight: 1 });
  conversationBox.add(box);
  const blocks = new Map();      // blockId -> { kind, r }
  const runningTools = new Set(); // toolBlock renderers animating
  const runningReasoning = new Set(); // reasoning markers animating

  // One card per assistant turn: a short "╭ squilla" label, a single
  // left-border gutter that runs unbroken through narration and tool calls, and
  // a "╰ …" footer that carries the usage summary. The chrome is deliberately
  // width-INDEPENDENT — a full-width header rule wraps a stray dash onto the
  // next row the moment the scrollbar steals a viewport column, so no rule may
  // depend on the terminal width. The card opens lazily on the first in-card
  // block so a turn that only echoes a prompt never draws an empty card.
  let cardBody = null;
  let cardTop = null; // the "╭ squilla" header label
  let cardBot = null; // the "╰ …" footer (usage summary / cancelled marker)
  let cancelNode = null; // "⚠ cancelled" fallback for card-less views (queued prompts)
  let usageText = null; // trailing usage summary, folded into the footer
  const gapRows = []; // prose<->procedure spacer rows (detailText)
  let cardOpen = false;
  let cardClosed = false;
  let cardCancelled = false;
  let lastInCardKind = null; // for prose<->procedure spacing inside the card
  let gapSeq = 0;
  let lastRelayoutWidth = renderer.terminalWidth; // block content is clipped at this width

  function openCard() {
    if (cardOpen) return;
    cardOpen = true;
    cardTop = new TextRenderable(renderer, { id: `turn-${id}-cardtop`, content: "╭ squilla", fg: THEME.answerFrame });
    box.add(cardTop);
    cardBody = new BoxRenderable(renderer, { id: `turn-${id}-cardbody`, width: "100%", flexDirection: "column", border: ["left"], borderColor: THEME.answerFrame, paddingLeft: 1, flexShrink: 0 });
    box.add(cardBody);
  }

  function footerContent() {
    if (cardCancelled) {
      return usageText ? `╰ ⚠ cancelled · ${usageText}` : "╰ ⚠ cancelled";
    }
    return usageText ? `╰ ${usageText}` : "╰";
  }

  function footerColor() {
    if (cardCancelled) return THEME.warning;
    return usageText ? THEME.muted : THEME.answerFrame;
  }

  function standaloneUsageRow() {
    if (!usageText) return;
    const row = new TextRenderable(renderer, { id: `turn-${id}-usage`, content: `${TOOL_INDENT}${usageText}`, fg: THEME.muted });
    box.add(row);
  }

  function closeCard() {
    if (!cardOpen) {
      // No card to close (e.g. a turn that only echoed a prompt): a usage
      // summary still deserves its receipt row.
      standaloneUsageRow();
      usageText = null;
      return;
    }
    if (cardClosed) {
      // Already closed: a late usage/cancel still refreshes the footer text.
      if (cardBot) {
        cardBot.content = footerContent();
        cardBot.fg = footerColor();
        renderer.requestRender?.();
      }
      return;
    }
    // A body that kept no children would close into an empty "╭ squilla … ╰"
    // shell (e.g. a turn cancelled during extended thinking: the transient
    // Thinking… marker removes itself when the reasoning block ends). Drop the
    // chrome instead — keeping any usage receipt as a plain row — and let a
    // later in-card block simply re-open a fresh card.
    const kept = cardBody?.getChildrenCount?.() ?? cardBody?.getChildren?.().length ?? 0;
    if (kept === 0) {
      box.remove?.(cardTop.id);
      box.remove?.(cardBody.id);
      cardTop = cardBody = null;
      cardOpen = false;
      lastInCardKind = null;
      standaloneUsageRow();
      usageText = null;
      renderer.requestRender?.();
      return;
    }
    cardClosed = true;
    cardBot = new TextRenderable(renderer, { id: `turn-${id}-cardbot`, content: footerContent(), fg: footerColor() });
    box.add(cardBot);
    renderer.requestRender?.();
  }

  function ctxFor(blockId, kind) {
    // In-card blocks draw into the shared bordered body so the gutter stays
    // continuous; everything else draws straight into the turn box.
    const target = !isOutOfCardKind(kind) && cardBody ? cardBody : box;
    return { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, box: target, idPrefix: `turn-${id}-${blockId}` };
  }

  return {
    box,
    ended: false,
    begin(blockId, kind, meta) {
      if (kind === "usage") {
        // The usage summary is the card's own trailing line, not a block: fold
        // it into the "╰ …" footer so the card closes into its receipt instead
        // of a floating row. append/update/end for this id stay safe no-ops.
        usageText = stripTerminalControls(String(meta?.text ?? "")).trim() || null;
        closeCard();
        return;
      }
      if (!isOutOfCardKind(kind)) {
        openCard();
        // Separate the markdown answer (prose) from procedure rows (tools and
        // narration) with one blank gutter row, but pack consecutive procedure
        // rows tight — mirrors opencode's part spacing without an even gap
        // between every step. The card border keeps the gutter continuous.
        if (lastInCardKind !== null && (kind === "answer") !== (lastInCardKind === "answer")) {
          const gap = new TextRenderable(renderer, { id: `turn-${id}-gap-${gapSeq++}`, content: TOOL_INDENT, fg: THEME.detailText });
          cardBody.add(gap);
          gapRows.push(gap);
        }
        lastInCardKind = kind;
      }
      const r = createBlock(kind, ctxFor(blockId, kind));
      blocks.set(blockId, { kind, r });
      r.begin(meta ?? {});
      if (kind === "tool") runningTools.add(r);
      if (kind === "reasoning") runningReasoning.add(r);
    },
    append(blockId, delta) { blocks.get(blockId)?.r.append(delta); },
    update(blockId, patch) {
      const entry = blocks.get(blockId);
      if (!entry) return;
      entry.r.update(patch);
      if (entry.kind === "tool" && (patch?.status === "ok" || patch?.status === "error")) runningTools.delete(entry.r);
    },
    end(blockId) {
      const entry = blocks.get(blockId);
      if (!entry) return;
      entry.r.end();
      if (entry.kind === "tool") runningTools.delete(entry.r);
      if (entry.kind === "reasoning") runningReasoning.delete(entry.r);
    },
    // Close the single per-turn card once the turn is over (the runtime calls
    // this on turn.end). Idempotent and a no-op when no card ever opened. A
    // cancelled turn (Esc mid-stream) closes into a "╰ ⚠ cancelled" footer so
    // the transcript records that this answer was cut short; a card-less view
    // (a discarded queued prompt) gets a standalone marker row instead.
    finish(cancelled) {
      if (cancelled) cardCancelled = true;
      closeCard();
      if (cancelled && !cardOpen && !cancelNode) {
        cancelNode = new TextRenderable(renderer, { id: `turn-${id}-cancelled`, content: `${TOOL_INDENT}⚠ cancelled`, fg: THEME.warning });
        box.add(cancelNode);
        renderer.requestRender?.();
      }
    },
    // Re-clip width-clipped block content to the current terminal width on
    // resize. The card chrome itself is width-independent by design, so only
    // the blocks (tool corners, narration wraps) need reflow work — and a
    // height-only resize skips even that, so a long session does not pay
    // O(turns) text-buffer work per resize frame.
    relayout() {
      const width = renderer.terminalWidth;
      if (width === lastRelayoutWidth) return;
      lastRelayoutWidth = width;
      for (const entry of blocks.values()) entry.r.relayout?.();
      renderer.requestRender?.();
    },
    // Live /theme switch: re-point this turn's card chrome at the (in-place
    // updated) THEME, then let each block recolor its own nodes. Existing
    // renderables captured their fg at creation, so without this a dark→light
    // switch leaves prior transcript unreadable on the new background.
    recolor() {
      if (cardTop) cardTop.fg = THEME.answerFrame;
      if (cardBody) cardBody.borderColor = THEME.answerFrame;
      if (cardBot) cardBot.fg = footerColor();
      if (cancelNode) cancelNode.fg = THEME.warning;
      for (const gap of gapRows) gap.fg = THEME.detailText;
      for (const entry of blocks.values()) entry.r.recolor?.();
    },
    refreshPulse(frame) {
      const toolGlyph = STATUS_PULSE_FRAMES.tool[frame % STATUS_PULSE_FRAMES.tool.length];
      const thinkingGlyph = STATUS_PULSE_FRAMES.thinking[frame % STATUS_PULSE_FRAMES.thinking.length];
      for (const r of runningTools) r.setGlyph(toolGlyph);
      for (const r of runningReasoning) r.setGlyph(thinkingGlyph);
    },
  };
}

// Decides which turn view receives each protocol event. Kept apart from the
// renderer wiring so queued-prompt routing and late-block tolerance are plain
// logic: newView(id) creates a view (createTurnView bound to real deps).
export function createTurnFlow(newView) {
  const turns = []; // every view ever created, for resize reflow + theme recolor
  const pending = []; // queued-prompt views waiting for their turn.begin (FIFO)
  let active = null;

  function create(id) {
    const view = newView(id);
    turns.push(view);
    return view;
  }

  function ensure(id) {
    if (!active || active.ended) active = pending.shift() ?? create(id);
    return active;
  }

  return {
    turns,
    active: () => active,
    ensure,
    // block.begin after turn.end is a late straggler (e.g. a trailing usage
    // line) that belongs to the turn that just ended. Routing it there keeps
    // it from spawning a fresh un-ended turn that would absorb the next
    // prompt.echo into the same box.
    turnForBlock(id) {
      return active && active.ended ? active : ensure(id);
    },
    // prompt.echo while a turn is still streaming means the submission was
    // QUEUED behind it: give the echo its own view — reusing the live turn
    // would seal its card mid-stream and glue its usage line to the new
    // prompt. ensure() then adopts queued views in order as their turns begin.
    turnForPrompt(id) {
      if (active && !active.ended) {
        const view = create(id);
        pending.push(view);
        return view;
      }
      return ensure(id);
    },
    endTurn(cancelled = false) {
      // A cancelled turn.end only comes from the cancel path (Esc / empty
      // Ctrl+C), which already discarded every queued submission server-side.
      // Invalidate their views too, or ensure() would adopt a stale discarded
      // prompt's box for the NEXT real submission — fusing the new prompt and
      // its whole answer under a dead prompt card. Marking each flushed view
      // cancelled makes the discarded prompt visibly unanswered.
      if (cancelled) {
        for (const view of pending.splice(0)) {
          view.finish?.(true);
          view.ended = true;
        }
      }
      if (!active) return;
      active.finish?.(cancelled);
      active.ended = true;
    },
  };
}
