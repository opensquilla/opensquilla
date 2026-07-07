import { createBlock } from "./blockRegistry.mjs";
import { STATUS_PULSE_FRAMES, THEME } from "./theme.mjs";
import { TOOL_INDENT, CARD_RULE_SHORT, cardHeaderRule } from "./primitives.mjs";

// Block kinds that render OUTSIDE the assistant's single per-turn card: the
// prompt is the user's own card and the usage line is a trailing summary.
// Everything else — answer markdown, intermediate narration, tool calls, the
// reasoning marker, errors, and any kind this host does not know yet (a newer
// Python may add block kinds) — shares ONE continuous left-border gutter so a
// multi-step turn reads as one assistant block (opencode/codex style) instead
// of a stack of repeated "╭─ answer ─ squilla ─ … ╰─" cards. Unknown kinds
// default INTO the card so a protocol addition can never seal it mid-turn;
// only the known trailing kind (usage) closes it.
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

  // One card per assistant turn: a single header rule, a single left-border
  // gutter that runs unbroken through narration and tool calls, and a single
  // footer. The card opens lazily on the first in-card block so a turn that only
  // emits e.g. a usage summary never draws an empty card, and closes once on
  // turn end (or when a trailing out-of-card block such as usage begins).
  let cardBody = null;
  let cardTop = null; // the "╭─ squilla ─…" header rule (width-dependent)
  let cardGap = null; // the leading "│" gap row above the header
  let cardBot = null; // the "╰────" footer rule
  let cancelNode = null; // the "⚠ cancelled" marker (turn.end with cancelled)
  const gapRows = []; // prose<->procedure spacer rows (detailText)
  let cardOpen = false;
  let cardClosed = false;
  let lastInCardKind = null; // for prose<->procedure spacing inside the card
  let gapSeq = 0;
  let lastRuledWidth = renderer.terminalWidth; // rules are baked at this width

  function openCard() {
    if (cardOpen) return;
    cardOpen = true;
    cardGap = new TextRenderable(renderer, { id: `turn-${id}-cardgap`, content: `${TOOL_INDENT}│`, fg: THEME.detailText });
    box.add(cardGap);
    cardTop = new TextRenderable(renderer, { id: `turn-${id}-cardtop`, content: cardHeaderRule("squilla", renderer.terminalWidth), fg: THEME.answerFrame });
    box.add(cardTop);
    cardBody = new BoxRenderable(renderer, { id: `turn-${id}-cardbody`, width: "100%", flexDirection: "column", border: ["left"], borderColor: THEME.answerFrame, paddingLeft: 1, flexShrink: 0 });
    box.add(cardBody);
  }

  function closeCard() {
    if (!cardOpen || cardClosed) return;
    // A body that kept no children would close into an empty "╭─ squilla ─ …
    // ╰─" shell (e.g. a turn cancelled during extended thinking: the transient
    // Thinking… marker removes itself when the reasoning block ends). Drop the
    // chrome instead; a later in-card block simply re-opens a fresh card.
    const kept = cardBody?.getChildrenCount?.() ?? cardBody?.getChildren?.().length ?? 0;
    if (kept === 0) {
      box.remove?.(cardGap.id);
      box.remove?.(cardTop.id);
      box.remove?.(cardBody.id);
      cardGap = cardTop = cardBody = null;
      cardOpen = false;
      lastInCardKind = null;
      renderer.requestRender?.();
      return;
    }
    cardClosed = true;
    cardBot = new TextRenderable(renderer, { id: `turn-${id}-cardbot`, content: `╰${CARD_RULE_SHORT}`, fg: THEME.answerFrame });
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
      } else if (kind === "usage") {
        closeCard(); // the trailing usage summary sits below the card footer
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
    // cancelled turn (Esc mid-stream) gets a trailing warning marker so the
    // transcript records that this answer was cut short.
    finish(cancelled) {
      closeCard();
      if (cancelled && !cancelNode) {
        cancelNode = new TextRenderable(renderer, { id: `turn-${id}-cancelled`, content: `${TOOL_INDENT}⚠ cancelled`, fg: THEME.warning });
        box.add(cancelNode);
        renderer.requestRender?.();
      }
    },
    // Reflow width-dependent chrome to the current terminal width on resize, so
    // existing cards re-rule instead of leaving their baked full-width header to
    // wrap (shrink) or strand (grow). Markdown bodies and text lines already
    // re-wrap at layout time; only the rule strings must be recomputed. The
    // prompt block reflows its own header via the per-block relayout() below.
    // Height-only resizes leave every rule valid, so re-ruling is skipped and a
    // long session does not pay O(turns) text-buffer work per resize frame.
    relayout() {
      const width = renderer.terminalWidth;
      if (width === lastRuledWidth) return;
      lastRuledWidth = width;
      if (cardTop) cardTop.content = cardHeaderRule("squilla", width);
      for (const entry of blocks.values()) entry.r.relayout?.();
      renderer.requestRender?.();
    },
    // Live /theme switch: re-point this turn's card chrome at the (in-place
    // updated) THEME, then let each block recolor its own nodes. Existing
    // renderables captured their fg at creation, so without this a dark→light
    // switch leaves prior transcript unreadable on the new background.
    recolor() {
      if (cardGap) cardGap.fg = THEME.detailText;
      if (cardTop) cardTop.fg = THEME.answerFrame;
      if (cardBody) cardBody.borderColor = THEME.answerFrame;
      if (cardBot) cardBot.fg = THEME.answerFrame;
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
