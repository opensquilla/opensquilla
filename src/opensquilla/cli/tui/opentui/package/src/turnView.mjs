import { createBlock } from "./blockRegistry.mjs";
import { STATUS_PULSE_FRAMES, THEME } from "./theme.mjs";
import { TOOL_INDENT, CARD_RULE_SHORT, cardHeaderRule } from "./primitives.mjs";

// Block kinds that live INSIDE the assistant's single per-turn card. Answer
// markdown, intermediate narration, tool calls, the reasoning marker and errors
// all share ONE continuous left-border gutter so a multi-step turn reads as one
// assistant block (opencode/codex style) instead of a stack of repeated
// "╭─ answer ─ squilla ─ … ╰─" cards. The prompt is the user's own card and the
// usage line is a trailing summary, so neither joins the assistant card.
const IN_CARD_KINDS = new Set(["answer", "thinking", "tool", "reasoning", "error"]);

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
  let cardOpen = false;
  let cardClosed = false;
  let lastInCardKind = null; // for prose<->procedure spacing inside the card
  let gapSeq = 0;

  function openCard() {
    if (cardOpen) return;
    cardOpen = true;
    box.add(new TextRenderable(renderer, { id: `turn-${id}-cardgap`, content: `${TOOL_INDENT}│`, fg: THEME.detailText }));
    cardTop = new TextRenderable(renderer, { id: `turn-${id}-cardtop`, content: cardHeaderRule("squilla", renderer.terminalWidth), fg: THEME.answerFrame });
    box.add(cardTop);
    cardBody = new BoxRenderable(renderer, { id: `turn-${id}-cardbody`, width: "100%", flexDirection: "column", border: ["left"], borderColor: THEME.answerFrame, paddingLeft: 1, flexShrink: 0 });
    box.add(cardBody);
  }

  function closeCard() {
    if (!cardOpen || cardClosed) return;
    cardClosed = true;
    box.add(new TextRenderable(renderer, { id: `turn-${id}-cardbot`, content: `╰${CARD_RULE_SHORT}`, fg: THEME.answerFrame }));
    renderer.requestRender?.();
  }

  function ctxFor(blockId, kind) {
    // In-card blocks draw into the shared bordered body so the gutter stays
    // continuous; everything else draws straight into the turn box.
    const target = IN_CARD_KINDS.has(kind) && cardBody ? cardBody : box;
    return { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, box: target, idPrefix: `turn-${id}-${blockId}` };
  }

  return {
    box,
    ended: false,
    begin(blockId, kind, meta) {
      if (IN_CARD_KINDS.has(kind)) {
        openCard();
        // Separate the markdown answer (prose) from procedure rows (tools and
        // narration) with one blank gutter row, but pack consecutive procedure
        // rows tight — mirrors opencode's part spacing without an even gap
        // between every step. The card border keeps the gutter continuous.
        if (lastInCardKind !== null && (kind === "answer") !== (lastInCardKind === "answer")) {
          cardBody.add(new TextRenderable(renderer, { id: `turn-${id}-gap-${gapSeq++}`, content: TOOL_INDENT, fg: THEME.detailText }));
        }
        lastInCardKind = kind;
      } else {
        closeCard(); // a trailing out-of-card block (usage) sits below the footer
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
    // this on turn.end). Idempotent and a no-op when no card ever opened.
    finish() { closeCard(); },
    // Reflow width-dependent chrome to the current terminal width on resize, so
    // existing cards re-rule instead of leaving their baked full-width header to
    // wrap (shrink) or strand (grow). Markdown bodies and text lines already
    // re-wrap at layout time; only the rule strings must be recomputed. The
    // prompt block reflows its own header via the per-block relayout() below.
    relayout() {
      if (cardTop) cardTop.content = cardHeaderRule("squilla", renderer.terminalWidth);
      for (const entry of blocks.values()) entry.r.relayout?.();
      renderer.requestRender?.();
    },
    refreshPulse(frame) {
      const toolGlyph = STATUS_PULSE_FRAMES.tool[frame % STATUS_PULSE_FRAMES.tool.length];
      const thinkingGlyph = STATUS_PULSE_FRAMES.thinking[frame % STATUS_PULSE_FRAMES.thinking.length];
      for (const r of runningTools) r.setGlyph(toolGlyph);
      for (const r of runningReasoning) r.setGlyph(thinkingGlyph);
    },
  };
}
