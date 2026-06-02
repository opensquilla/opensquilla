import { createBlock } from "./blockRegistry.mjs";
import { STATUS_PULSE_FRAMES } from "./theme.mjs";

export function createTurnView(deps, id) {
  const { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, conversationBox } = deps;
  const box = new BoxRenderable(renderer, { id: `turn-${id}`, flexDirection: "column", paddingLeft: 1, paddingRight: 1 });
  conversationBox.add(box);
  const blocks = new Map();      // blockId -> { kind, r }
  const runningTools = new Set(); // toolBlock renderers animating

  function ctxFor(blockId) {
    return { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, box, idPrefix: `turn-${id}-${blockId}` };
  }

  return {
    box,
    ended: false,
    begin(blockId, kind, meta) {
      const r = createBlock(kind, ctxFor(blockId));
      blocks.set(blockId, { kind, r });
      r.begin(meta ?? {});
      if (kind === "tool") runningTools.add(r);
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
    },
    refreshPulse(frame) {
      const glyph = STATUS_PULSE_FRAMES.tool[frame % STATUS_PULSE_FRAMES.tool.length];
      for (const r of runningTools) r.setGlyph(glyph);
    },
  };
}
