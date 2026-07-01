import assert from "node:assert/strict";
import test, { afterEach } from "node:test";

import { applyTheme, STATUS, THEME } from "./theme.mjs";
import { createTurnView } from "./turnView.mjs";
import { createPromptBlock } from "./blocks/promptBlock.mjs";
import { createToolBlock } from "./blocks/toolBlock.mjs";
import { createThinkingBlock } from "./blocks/thinkingBlock.mjs";

// A live /theme switch mutates THEME/STATUS in place. Renderables captured their
// fg at creation, so a dark→light switch would leave prior transcript unreadable
// unless recolor() re-points every node at the updated tokens. These tests lock
// that contract at the node level with a minimal fake renderable.

class FakeNode {
  constructor(_renderer, options = {}) {
    Object.assign(this, options);
    this.children = [];
  }
  add(node) {
    this.children.push(node);
    return this.children.length;
  }
  remove(id) {
    this.children = this.children.filter((child) => child.id !== id);
  }
  getChildren() {
    return this.children;
  }
}

const renderer = { requestRender() {}, terminalWidth: 80, terminalHeight: 24 };

function findById(node, id) {
  for (const child of node.getChildren?.() ?? node.children ?? []) {
    if (child.id === id) return child;
    const hit = findById(child, id);
    if (hit) return hit;
  }
  return null;
}

afterEach(() => applyTheme("opensquilla-dark"));

test("prompt block recolors every node to the new theme accent", () => {
  applyTheme("opensquilla-dark");
  const box = new FakeNode();
  const block = createPromptBlock({ renderer, TextRenderable: FakeNode, box, idPrefix: "p" });
  block.begin({ text: "line one\nline two" });

  const dark = THEME.promptAccent;
  assert.ok(box.children.length >= 3);
  assert.ok(box.children.every((n) => n.fg === dark));

  applyTheme("opensquilla-light");
  block.recolor();
  assert.notStrictEqual(THEME.promptAccent, dark); // the two themes genuinely differ
  assert.ok(box.children.every((n) => n.fg === THEME.promptAccent));
});

test("tool block recolor re-derives the run-state color for its current state", () => {
  applyTheme("opensquilla-dark");
  const box = new FakeNode();
  const block = createToolBlock({ renderer, TextRenderable: FakeNode, box, idPrefix: "t" });
  block.begin({ name: "grep" });
  const node = box.children[0];
  assert.equal(node.fg, STATUS.running);

  block.update({ status: "ok" });
  assert.equal(node.fg, STATUS.ok);

  applyTheme("opensquilla-light");
  block.recolor();
  // Still the OK color, but from the new palette (not the stale dark one).
  assert.equal(node.fg, STATUS.ok);
});

test("thinking block recolors in place without recreating its nodes", () => {
  applyTheme("opensquilla-dark");
  const box = new FakeNode();
  const block = createThinkingBlock({ renderer, TextRenderable: FakeNode, box, idPrefix: "th" });
  block.append("line one\nline two");
  const before = box.children.map((n) => n.id);
  const dark = THEME.thinkingAccent;
  assert.ok(box.children.length >= 2);
  assert.ok(box.children.every((n) => n.fg === dark));

  applyTheme("opensquilla-light");
  block.recolor();
  // Same node objects, same order — recolor must not remove/re-add (which would
  // re-append the lines after later blocks in a shared card body).
  assert.deepEqual(box.children.map((n) => n.id), before);
  assert.ok(box.children.every((n) => n.fg === THEME.thinkingAccent));
});

test("recolor preserves block order in the shared card body", () => {
  applyTheme("opensquilla-dark");
  const conversationBox = new FakeNode();
  const turn = createTurnView(
    {
      renderer,
      BoxRenderable: FakeNode,
      TextRenderable: FakeNode,
      MarkdownRenderable: FakeNode,
      syntaxStyle: {},
      conversationBox,
    },
    "y",
  );
  turn.begin("th", "thinking", {});
  turn.append("th", "reasoning one\nreasoning two");
  turn.begin("tl", "tool", { name: "grep" });

  const cardBody = findById(conversationBox.children[0], "turn-y-cardbody");
  const before = cardBody.children.map((c) => c.id);
  assert.ok(before.indexOf("turn-y-th-l0") < before.indexOf("turn-y-tl-node"));

  applyTheme("opensquilla-light");
  turn.recolor();
  // Thinking lines must still precede the tool row — order unchanged.
  assert.deepEqual(
    cardBody.children.map((c) => c.id),
    before,
  );
});

test("turn card chrome recolors on a theme switch", () => {
  applyTheme("opensquilla-dark");
  const conversationBox = new FakeNode();
  const turn = createTurnView(
    {
      renderer,
      BoxRenderable: FakeNode,
      TextRenderable: FakeNode,
      MarkdownRenderable: FakeNode,
      syntaxStyle: {},
      conversationBox,
    },
    "x",
  );
  turn.begin("b1", "tool", { name: "grep" }); // opens the card (header/body/gutter)

  const box = conversationBox.children[0];
  const darkFrame = THEME.answerFrame;
  const cardTop = findById(box, "turn-x-cardtop");
  const cardBody = findById(box, "turn-x-cardbody");
  assert.ok(cardTop && cardBody);
  assert.equal(cardTop.fg, darkFrame);
  assert.equal(cardBody.borderColor, darkFrame);

  applyTheme("opensquilla-light");
  turn.recolor();
  assert.notStrictEqual(THEME.answerFrame, darkFrame);
  assert.equal(cardTop.fg, THEME.answerFrame);
  assert.equal(cardBody.borderColor, THEME.answerFrame);
});
