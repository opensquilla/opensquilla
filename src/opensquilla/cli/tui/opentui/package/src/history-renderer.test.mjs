import assert from "node:assert/strict";
import test from "node:test";

import { historyBoundaryText, replayHistory, replaceHistoryConversation } from "./historyRenderer.mjs";

function harness() {
  const views = [];
  let active = null;
  const makeView = (id) => {
    const events = [];
    const view = {
      id,
      ended: false,
      events,
      begin: (blockId, kind, meta) => events.push(["begin", blockId, kind, meta]),
      append: (blockId, delta) => events.push(["append", blockId, delta]),
      update: (blockId, patch) => events.push(["update", blockId, patch]),
      end: (blockId) => events.push(["end", blockId]),
      finish: (cancelled) => events.push(["finish", cancelled]),
    };
    views.push(view);
    return view;
  };
  const flow = {
    ensure(id) {
      if (!active || active.ended) active = makeView(id);
      return active;
    },
    turnForPrompt(id) { return this.ensure(id); },
    endTurn(cancelled) {
      if (!active) return;
      active.finish(cancelled);
      active.ended = true;
    },
  };
  return { flow, views };
}

test("history boundary labels complete, windowed, and compacted snapshots", () => {
  assert.equal(historyBoundaryText({ history_scope: "complete", loaded_count: 4 }), "history · complete · 4 messages");
  assert.equal(historyBoundaryText({ history_scope: "latest_window", loaded_count: 20 }), "history · latest 20 messages · older messages available");
  assert.equal(historyBoundaryText({ history_scope: "compacted", loaded_count: 8, compaction_summaries: [{ id: "s1" }] }), "history · compacted · 8 recent messages · 1 earlier summary");
  assert.equal(historyBoundaryText({ history_scope: "complete", loaded_count: 0 }), "");
});

test("history replacement clears old conversation children before replay", () => {
  const children = [{ id: "old-turn" }, { id: "old-notice" }];
  const conversationBox = {
    getChildren: () => [...children],
    remove(id) {
      const index = children.findIndex((child) => child.id === id);
      if (index >= 0) children.splice(index, 1);
    },
    add(child) { children.push(child); },
  };
  const { flow, views } = harness();

  const replaced = replaceHistoryConversation({
    message: {
      history_scope: "complete",
      loaded_count: 1,
      messages: [{ id: "m1", role: "assistant", text: "fresh" }],
    },
    conversationBox,
    flowFactory: () => flow,
    addBoundary: (content) => conversationBox.add({ id: "new-boundary", content }),
    nextId: (id) => id,
  });

  assert.equal(replaced, flow);
  assert.deepEqual(children, [{ id: "new-boundary", content: "history · complete · 1 messages" }]);
  assert.equal(views.length, 1);
  assert.ok(views[0].events.some((event) => event[0] === "append" && event[2] === "fresh"));
});

test("canonical history reuses live turn blocks and deduplicates durable ids", () => {
  const { flow, views } = harness();
  replayHistory({
    flow,
    nextId: (id) => `history-${id}`,
    messages: [
      { id: "m1", role: "user", text: "hello", attachments: [{ name: "brief.pdf" }] },
      {
        id: "m2",
        role: "assistant",
        text: "done",
        reasoning: "checked",
        tool_calls: [{ id: "t1", name: "read_file", input: { path: "brief.pdf" }, result: "ok" }],
        artifacts: [{ name: "report.md" }],
        usage: { input_tokens: 3, output_tokens: 5, model: "openai/test" },
      },
      { id: "m2", role: "assistant", text: "duplicate" },
    ],
  });

  assert.equal(views.length, 1);
  const events = views[0].events;
  assert.ok(events.some((event) => event[0] === "begin" && event[2] === "prompt" && event[3].text.includes("brief.pdf")));
  assert.ok(events.some((event) => event[0] === "begin" && event[2] === "reasoning"));
  assert.ok(events.some((event) => event[0] === "begin" && event[2] === "tool" && event[3].name === "read_file"));
  assert.ok(events.some((event) => event[0] === "begin" && event[2] === "answer"));
  assert.ok(events.some((event) => event[0] === "begin" && event[2] === "history-detail"));
  assert.ok(events.some((event) => event[0] === "begin" && event[2] === "usage"));
  assert.equal(events.filter((event) => event[0] === "finish").length, 1);
  assert.equal(events.some((event) => event.includes("duplicate")), false);
});
