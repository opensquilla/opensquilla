import assert from "node:assert/strict";
import test from "node:test";

import { createComposer } from "./composer.mjs";
import { textWidth } from "./primitives.mjs";

// Minimal fake renderable that records its children by id, mirroring the
// add/remove/getChildren contract the composer relies on. Nodes carry the
// option bag so tests can assert positioning/zIndex.
// Mirrors the real `new BoxRenderable(renderer, options)` two-arg constructor;
// the composer always passes the renderer first, options second.
class FakeNode {
  constructor(_renderer, options = {}) {
    this.options = options;
    this.id = options.id;
    this.zIndex = options.zIndex ?? 0;
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

function makeHarness({ terminalWidth = 100 } = {}) {
  const keypressHandlers = [];
  const renderer = {
    terminalWidth,
    keyInput: {
      on(event, handler) {
        if (event === "keypress") keypressHandlers.push(handler);
      },
    },
    requestRender() {},
  };
  const rootNode = new FakeNode(renderer, { id: "root" });
  const conversationBox = new FakeNode(renderer, { id: "conversation", zIndex: 0 });
  const inputBox = new FakeNode(renderer, { id: "input-region", zIndex: 0 });
  const overlayLayer = new FakeNode(renderer, { id: "overlay-layer", zIndex: 100 });
  rootNode.add(conversationBox);
  rootNode.add(inputBox);
  rootNode.add(overlayLayer);

  const composer = createComposer({
    renderer,
    BoxRenderable: FakeNode,
    TextRenderable: FakeNode,
    conversationBox,
    inputBox,
    overlayLayer,
    footerHeight: 6,
    sendHostMessage: () => {},
  });
  composer.install();
  const press = (key) => keypressHandlers.forEach((handler) => handler(key));
  return { composer, press, inputBox, overlayLayer, conversationBox };
}

function findDeep(node, id) {
  if (node.id === id) return node;
  for (const child of node.getChildren?.() ?? []) {
    const hit = findDeep(child, id);
    if (hit) return hit;
  }
  return null;
}

test("completion menu mounts on the overlay layer, never inside the footer box", () => {
  const { composer, press, inputBox, overlayLayer } = makeHarness();
  composer.setCompletionContext({
    catalog: [{ label: "/compact", description: "compact", insert_text: "/compact " }],
  });

  press({ name: "/", sequence: "/" });

  assert.ok(
    findDeep(overlayLayer, "completion-menu"),
    "menu should be mounted on the overlay layer",
  );
  assert.equal(
    findDeep(inputBox, "completion-menu"),
    null,
    "menu must not be mounted inside the footer/input box",
  );
});

test("closing the menu removes it from the overlay layer", () => {
  const { composer, press, overlayLayer } = makeHarness();
  composer.setCompletionContext({
    catalog: [{ label: "/compact", description: "compact", insert_text: "/compact " }],
  });

  press({ name: "/", sequence: "/" });
  assert.ok(findDeep(overlayLayer, "completion-menu"), "menu present after trigger");

  press({ name: "escape" });
  assert.equal(
    findDeep(overlayLayer, "completion-menu"),
    null,
    "menu node must be cleared from the overlay on close",
  );
});

test("re-rendering the active menu does not stack duplicate nodes", () => {
  const { composer, press, overlayLayer } = makeHarness();
  composer.setCompletionContext({
    catalog: [
      { label: "/compact", description: "compact", insert_text: "/compact " },
      { label: "/compress", description: "compress", insert_text: "/compress " },
    ],
  });

  press({ name: "/", sequence: "/" });
  press({ name: "c", sequence: "c" });
  press({ name: "down" });
  press({ name: "up" });

  const menus = overlayLayer
    .getChildren()
    .filter((child) => child.id === "completion-menu");
  assert.equal(menus.length, 1, "exactly one menu node should exist after several re-renders");
});

test("completion menu clips long rows to the menu body width", () => {
  const { composer, press, overlayLayer } = makeHarness({ terminalWidth: 72 });
  composer.setCompletionContext({
    catalog: [
      {
        label: "/cost",
        description: "Show current REPL session usage.",
        insert_text: "/cost ",
      },
      {
        label: "/compact",
        description: "Compact older context in the current session.",
        insert_text: "/compact ",
      },
      {
        label: "Cost",
        description: "Show current session usage and cost.",
        insert_text: "/cost",
      },
      {
        label: "/html-coder",
        description: "Expert HTML development skill for building web pages and forms.",
        insert_text: "use the html-coder skill: ",
      },
    ],
  });

  press({ name: "/", sequence: "/" });
  press({ name: "c", sequence: "c" });
  press({ name: "o", sequence: "o" });

  const menu = findDeep(overlayLayer, "completion-menu");
  const rowContents = menu.getChildren().map((child) => child.options.content);

  assert.ok(rowContents.some((content) => content.includes("/compact")));
  assert.ok(
    rowContents.every((content) => textWidth(content) <= 33),
    "row content must fit the 72-column menu body",
  );
});
