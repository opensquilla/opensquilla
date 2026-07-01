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

function makeHarness({ terminalWidth = 100, terminalHeight = 24 } = {}) {
  const keypressHandlers = [];
  const cursorPositions = [];
  const renderer = {
    terminalWidth,
    terminalHeight,
    keyInput: {
      on(event, handler) {
        if (event === "keypress") keypressHandlers.push(handler);
      },
    },
    setCursorPosition(x, y, visible) {
      cursorPositions.push({ x, y, visible });
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
  const lastCursor = () => cursorPositions.at(-1);
  return { composer, press, inputBox, overlayLayer, conversationBox, lastCursor };
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

test("composer clamps its box to a short terminal so the footer never overflows", () => {
  // main.mjs clamps inputBox.height with clampFooterHeight on short panes; the
  // composer must lay out against the SAME clamped height, not the fixed 6, or a
  // 3–5 row terminal overflows. composer height = clampFooterHeight(6, H) - 1.
  const tall = makeHarness({ terminalHeight: 24 });
  assert.equal(findDeep(tall.inputBox, "composer-box").options.height, 5);

  const short = makeHarness({ terminalHeight: 4 });
  const shortHeight = findDeep(short.inputBox, "composer-box").options.height;
  assert.equal(shortHeight, 3); // clamp(6,4)=4 → 4-1, not the unclamped 5
  assert.ok(shortHeight < 5);
});

test("composer shows the terminal cursor at the visual caret for IME popovers", () => {
  // visible MUST be true: macOS IME anchors the candidate popover to the VISIBLE
  // hardware cursor. With visible:false OpenTUI keeps the cursor hidden at home
  // and the popover drifts to a corner. x advances by display cells (CJK = 2).
  // Coordinates are 1-based (0-based cell + 1) to match OpenTUI's native cursor
  // convention (TextEditor.renderCursor passes screenX/Y + visual + 1).
  const { press, lastCursor } = makeHarness();

  assert.deepEqual(lastCursor(), { x: 4, y: 21, visible: true });

  press({ name: "h", sequence: "h" });
  press({ name: "i", sequence: "i" });
  assert.deepEqual(lastCursor(), { x: 6, y: 21, visible: true });

  press({ name: "backspace" });
  press({ name: "backspace" });
  press({ name: "你", sequence: "你" });
  press({ name: "好", sequence: "好" });
  assert.deepEqual(lastCursor(), { x: 8, y: 21, visible: true });

  press({ name: "return", option: true });
  press({ name: "a", sequence: "a" });
  assert.deepEqual(lastCursor(), { x: 5, y: 22, visible: true });
});
