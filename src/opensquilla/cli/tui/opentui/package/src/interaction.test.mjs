// Behavior tests for the conversation interaction helpers:
//   - isPinnedToBottom decides when streaming/new content should auto-follow the
//     bottom (vs the user having scrolled up to read history);
//   - copySelectionToClipboard mirrors an OpenTUI selection into the system
//     clipboard via OSC 52 (the select-to-copy fix, since a mouse-capturing TUI
//     never receives the terminal's Cmd/Ctrl+C);
//   - createTurnFlow routes protocol events to turn views (queued-prompt
//     isolation and late-block tolerance).
//
// Pure logic, so it runs under `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";

import { clampFooterHeight, isPinnedToBottom, copySelectionToClipboard } from "./primitives.mjs";
import { createTurnFlow, isOutOfCardKind } from "./turnView.mjs";

test("clampFooterHeight keeps the footer within the terminal height", () => {
  assert.equal(clampFooterHeight(6, 24), 6); // normal terminal: full footer
  assert.equal(clampFooterHeight(6, 6), 6); // exact fit
  assert.equal(clampFooterHeight(6, 4), 4); // short pane: clamp to terminal (no overflow)
  assert.equal(clampFooterHeight(6, 2), 2);
  assert.equal(clampFooterHeight(6, 1), 1); // never below one row
  assert.equal(clampFooterHeight(6, 0), 6); // unknown/zero height -> fall back to full footer
  assert.equal(clampFooterHeight(6, undefined), 6);
});

test("isPinnedToBottom only follows when at/near the bottom", () => {
  // viewport 30, content 100 => maxTop 70
  assert.equal(isPinnedToBottom(70, 100, 30), true); // exactly at the bottom
  assert.equal(isPinnedToBottom(69, 100, 30), true); // within default slack (2)
  assert.equal(isPinnedToBottom(50, 100, 30), false); // scrolled up to read history
  assert.equal(isPinnedToBottom(0, 100, 30), false); // at the top
  // content shorter than the viewport is always "at the bottom"
  assert.equal(isPinnedToBottom(0, 10, 30), true);
});

test("copySelectionToClipboard copies selected text via OSC 52 when supported", () => {
  const copied = [];
  const renderer = {
    isOsc52Supported: () => true,
    copyToClipboardOSC52: (text) => {
      copied.push(text);
      return true;
    },
  };
  const result = copySelectionToClipboard(renderer, { getSelectedText: () => "hello world" });
  assert.equal(result, true);
  assert.deepEqual(copied, ["hello world"]);
});

test("copySelectionToClipboard is a no-op for empty selection or unsupported terminal", () => {
  let copyCalls = 0;
  const base = {
    copyToClipboardOSC52: () => {
      copyCalls += 1;
      return true;
    },
  };
  // empty selection -> nothing copied
  assert.equal(
    copySelectionToClipboard({ ...base, isOsc52Supported: () => true }, { getSelectedText: () => "" }),
    false,
  );
  // OSC 52 unsupported terminal -> nothing copied (no stray escape bytes)
  assert.equal(
    copySelectionToClipboard({ ...base, isOsc52Supported: () => false }, { getSelectedText: () => "x" }),
    false,
  );
  assert.equal(copyCalls, 0);
});

function stubFlow() {
  let seq = 0;
  const flow = createTurnFlow((id) => ({
    id: id ?? `auto-${seq++}`,
    ended: false,
    cancelled: null,
    finish(c) { this.cancelled = Boolean(c); },
  }));
  return flow;
}

test("a prompt echoed during a streaming turn gets its own view, adopted at the next turn.begin", () => {
  const flow = stubFlow();
  const streaming = flow.ensure("t1"); // turn 1 begins and streams
  const queued = flow.turnForPrompt(); // user submits while it streams
  assert.notEqual(queued, streaming); // never the live turn: its card must not seal
  assert.equal(flow.active(), streaming); // blocks keep streaming into turn 1
  flow.endTurn();
  assert.equal(streaming.ended, true);
  assert.equal(flow.ensure("t2"), queued); // turn 2 adopts the queued view
});

test("queued prompts are adopted in FIFO order", () => {
  const flow = stubFlow();
  flow.ensure("t1");
  const first = flow.turnForPrompt();
  const second = flow.turnForPrompt();
  assert.notEqual(first, second);
  flow.endTurn();
  assert.equal(flow.ensure("t2"), first);
  flow.endTurn();
  assert.equal(flow.ensure("t3"), second);
});

test("a block after turn.end lands in the ended turn, never an orphan that absorbs the next prompt", () => {
  const flow = stubFlow();
  const done = flow.ensure("t1");
  flow.endTurn();
  assert.equal(flow.turnForBlock(), done); // a late usage straggler stays with its turn
  const next = flow.turnForPrompt(); // the NEXT submission starts a fresh turn
  assert.notEqual(next, done);
  assert.equal(flow.active(), next); // and the following turn.begin reuses it
  assert.equal(flow.ensure("t2"), next);
});

test("endTurn passes cancelled through to the view's finish", () => {
  const flow = stubFlow();
  const view = flow.ensure("t1");
  flow.endTurn(true);
  assert.equal(view.cancelled, true);
  assert.equal(view.ended, true);
  const normal = flow.ensure("t2");
  flow.endTurn();
  assert.equal(normal.cancelled, false);
});

test("a cancelled turn.end invalidates queued-prompt views instead of leaving them for adoption", () => {
  // Esc / empty Ctrl+C cancels the streaming turn AND discards the queued
  // submissions server-side. The stale queued views must be flushed — marked
  // cancelled and ended — or the NEXT real submission would be adopted into a
  // discarded prompt's box, rendering its whole turn glued under a dead card.
  const flow = stubFlow();
  flow.ensure("t1"); // turn 1 streams
  const q1 = flow.turnForPrompt(); // two submissions queue behind it
  const q2 = flow.turnForPrompt();
  flow.endTurn(true); // Esc: cancel + queue discard
  assert.equal(q1.ended, true);
  assert.equal(q1.cancelled, true); // visibly unanswered
  assert.equal(q2.ended, true);
  assert.equal(q2.cancelled, true);
  const next = flow.turnForPrompt(); // the next real submission…
  assert.notEqual(next, q1); // …never lands in a discarded prompt's box
  assert.notEqual(next, q2);
  assert.equal(flow.ensure("t2"), next); // and its turn.begin adopts the fresh view
});

test("a normal turn.end keeps queued views for FIFO adoption", () => {
  const flow = stubFlow();
  flow.ensure("t1");
  const queued = flow.turnForPrompt();
  flow.endTurn(); // completed, not cancelled: the queue survives
  assert.equal(queued.ended, false);
  assert.equal(flow.ensure("t2"), queued);
});

test("unknown block kinds stay inside the card; only prompt/usage render outside", () => {
  assert.equal(isOutOfCardKind("prompt"), true);
  assert.equal(isOutOfCardKind("usage"), true);
  for (const kind of ["answer", "thinking", "tool", "reasoning", "error", "future-kind"]) {
    assert.equal(isOutOfCardKind(kind), false, `${kind} must render in-card`);
  }
});
