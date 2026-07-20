// Tool-approval overlay tests:
//   - approvalKeyAction maps keys to approve/deny/navigate/choose, is modal
//     (swallows every other key while open), and passes Ctrl+C through so the
//     interrupt path is never trapped behind a pending approval;
//   - the composer mounts the overlay on approval.request, sends one
//     approval.response frame per decision, and clears the overlay afterwards.
//
// Run with: bun test src/approval-overlay.bun.test.mjs
import { test, expect } from "bun:test";

import { createComposer, approvalKeyAction } from "./composer.mjs";
import { THEME, applyTheme } from "./theme.mjs";

// Minimal fake renderable mirroring the add/remove/getChildren contract the
// composer relies on (same shape as overlay-mount.test.mjs).
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
  remove(node) {
    this.children = this.children.filter((child) => child !== node);
  }
  getChildren() {
    return this.children;
  }
}

function makeHarness({ terminalWidth = 100, terminalHeight = 24 } = {}) {
  applyTheme("opensquilla-dark");
  const keypressHandlers = [];
  const pasteHandlers = [];
  const sent = [];
  let renderRequests = 0;
  const renderer = {
    terminalWidth,
    terminalHeight,
    keyInput: {
      on(event, handler) {
        if (event === "keypress") keypressHandlers.push(handler);
        if (event === "paste") pasteHandlers.push(handler);
      },
    },
    setCursorPosition() {},
    requestRender() { renderRequests += 1; },
  };
  const conversationBox = new FakeNode(renderer, { id: "conversation" });
  conversationBox.scrollBy = () => {};
  const inputBox = new FakeNode(renderer, { id: "input-region" });
  const overlayLayer = new FakeNode(renderer, { id: "overlay-layer", zIndex: 1000 });
  const composer = createComposer({
    renderer,
    BoxRenderable: FakeNode,
    TextRenderable: FakeNode,
    conversationBox,
    inputBox,
    overlayLayer,
    footerHeight: 6,
    sendHostMessage: (m) => sent.push(m),
  });
  composer.install();
  const press = (key) => keypressHandlers.forEach((handler) => handler(key));
  const paste = (text) =>
    pasteHandlers.forEach((handler) => handler({ bytes: new TextEncoder().encode(text) }));
  const type = (text) => {
    for (const ch of text) press({ name: ch === " " ? "space" : ch, sequence: ch });
  };
  return {
    composer,
    press,
    paste,
    type,
    overlayLayer,
    sent,
    renderRequests: () => renderRequests,
  };
}

function findDeep(node, id) {
  if (node.id === id) return node;
  for (const child of node.getChildren?.() ?? []) {
    const hit = findDeep(child, id);
    if (hit) return hit;
  }
  return null;
}

const request = (overrides = {}) => ({
  id: "appr-1",
  tool: "shell",
  summary: "touch demo.txt",
  choices: [],
  ...overrides,
});

const CHOICES = ["allow_once", "allow_same_type", "deny"];

test("approvalKeyAction maps decision keys, is modal, and passes Ctrl+C through", () => {
  const overlay = { active: true, choices: CHOICES, selected: 1 };
  expect(approvalKeyAction(overlay, { name: "y" })).toMatchObject({ action: "approve" });
  expect(approvalKeyAction(overlay, { name: "n" })).toMatchObject({ action: "deny" });
  expect(approvalKeyAction(overlay, { name: "escape" })).toMatchObject({ action: "deny" });
  expect(approvalKeyAction(overlay, { name: "up" })).toMatchObject({
    action: "navigate", selected: 0,
  });
  expect(approvalKeyAction(overlay, { name: "down" })).toMatchObject({
    action: "navigate", selected: 2,
  });
  // clamps at the ends
  expect(approvalKeyAction({ ...overlay, selected: 0 }, { name: "up" })).toMatchObject({
    selected: 0,
  });
  expect(approvalKeyAction({ ...overlay, selected: 2 }, { name: "down" })).toMatchObject({
    selected: 2,
  });
  expect(approvalKeyAction(overlay, { name: "return" })).toMatchObject({
    action: "choose", selected: 1,
  });
  // without choices, Enter approves and Up/Down are swallowed as plain keys
  const bare = { active: true, choices: [], selected: 0 };
  expect(approvalKeyAction(bare, { name: "return" })).toMatchObject({ action: "approve" });
  expect(approvalKeyAction(bare, { name: "up" })).toMatchObject({ handled: true, action: "none" });
  // modal: every other key is swallowed so it never leaks into the input
  expect(approvalKeyAction(overlay, { name: "x", sequence: "x" })).toMatchObject({
    handled: true, action: "none",
  });
  // Ctrl+C must fall through to the interrupt path
  expect(approvalKeyAction(overlay, { name: "c", ctrl: true })).toMatchObject({
    handled: false, action: "pass",
  });
  // inactive overlay passes keys through
  expect(approvalKeyAction(null, { name: "y" })).toMatchObject({ handled: false });
});

test("modified chords are swallowed, never treated as decisions", () => {
  // Ctrl+Y is the composer's yank chord: reaching for it just as the overlay
  // pops must NOT approve a permission-gated tool the user never read.
  const bare = { active: true, choices: [], selected: 0 };
  const withChoices = { active: true, choices: CHOICES, selected: 1 };
  const swallowed = { handled: true, action: "none" };
  expect(approvalKeyAction(bare, { name: "y", ctrl: true })).toMatchObject(swallowed);
  expect(approvalKeyAction(bare, { name: "y", meta: true })).toMatchObject(swallowed);
  expect(approvalKeyAction(bare, { name: "y", option: true })).toMatchObject(swallowed);
  expect(approvalKeyAction(bare, { name: "n", ctrl: true })).toMatchObject(swallowed);
  expect(approvalKeyAction(bare, { name: "n", alt: true })).toMatchObject(swallowed);
  expect(approvalKeyAction(bare, { name: "return", ctrl: true })).toMatchObject(swallowed);
  expect(approvalKeyAction(withChoices, { name: "return", alt: true })).toMatchObject(swallowed);
  expect(approvalKeyAction(withChoices, { name: "escape", ctrl: true })).toMatchObject(swallowed);
});

test("Ctrl+Y while the overlay is open neither approves nor yanks into the draft", () => {
  const { composer, press, type, overlayLayer, sent } = makeHarness();
  // Kill some text so the yank chord has something it WOULD re-insert.
  type("draft");
  press({ name: "u", ctrl: true }); // kill: input empty, kill buffer "draft"
  composer.openApprovalOverlay(request());

  press({ name: "y", ctrl: true }); // muscle-memory yank mid-approval

  expect(sent.some((m) => m.type === "approval.response")).toBe(false);
  expect(findDeep(overlayLayer, "approval-overlay")).not.toBeNull();

  press({ name: "n", sequence: "n" }); // deny, close the overlay
  // Enter on an empty draft is a no-op (no submit frame), so prove the chord
  // inserted nothing with a sentinel: the submission must be ONLY the sentinel.
  type("X");
  press({ name: "return" });
  expect(sent.find((m) => m.type === "input.submit")?.text).toBe("X");
});

test("overlay mounts on approval.request with tool, summary, and hint", () => {
  const { composer, overlayLayer } = makeHarness();
  composer.openApprovalOverlay(request());

  const overlay = findDeep(overlayLayer, "approval-overlay");
  expect(overlay).not.toBeNull();
  expect(overlayLayer.visible).toBe(true);
  expect(findDeep(overlay, "approval-overlay-tool").options.content).toContain("shell");
  expect(findDeep(overlay, "approval-overlay-summary").options.content)
    .toContain("touch demo.txt");
  expect(findDeep(overlay, "approval-overlay-hint").options.content).toContain("approve");
});

test("a request without an id never mounts an unanswerable overlay", () => {
  const { composer, overlayLayer } = makeHarness();
  composer.openApprovalOverlay({ tool: "shell", summary: "no id" });
  expect(findDeep(overlayLayer, "approval-overlay")).toBeNull();
});

test("y approves and clears the overlay", () => {
  const { composer, press, overlayLayer, sent } = makeHarness();
  composer.openApprovalOverlay(request());

  press({ name: "y", sequence: "y" });

  expect(sent).toContainEqual({
    type: "approval.response", id: "appr-1", approved: true, choice: null,
  });
  expect(findDeep(overlayLayer, "approval-overlay")).toBeNull();
});

test("n and Escape deny", () => {
  const denyByN = makeHarness();
  denyByN.composer.openApprovalOverlay(request());
  denyByN.press({ name: "n", sequence: "n" });
  expect(denyByN.sent).toContainEqual({
    type: "approval.response", id: "appr-1", approved: false, choice: null,
  });

  const denyByEscape = makeHarness();
  denyByEscape.composer.openApprovalOverlay(request());
  denyByEscape.press({ name: "escape" });
  expect(denyByEscape.sent).toContainEqual({
    type: "approval.response", id: "appr-1", approved: false, choice: null,
  });
  expect(findDeep(denyByEscape.overlayLayer, "approval-overlay")).toBeNull();
});

test("Up/Down navigate choices and Enter confirms the highlighted one", () => {
  const { composer, press, overlayLayer, sent } = makeHarness();
  composer.openApprovalOverlay(request({ choices: CHOICES }));

  press({ name: "down" });
  const overlay = findDeep(overlayLayer, "approval-overlay");
  expect(findDeep(overlay, "approval-overlay-choice-1").options.content).toContain("› ");
  expect(findDeep(overlay, "approval-overlay-choice-1").options.content)
    .toContain("allow same type");

  press({ name: "return" });
  expect(sent).toContainEqual({
    type: "approval.response", id: "appr-1", approved: true, choice: "allow_same_type",
  });
  expect(findDeep(overlayLayer, "approval-overlay")).toBeNull();
});

test("the overlay swallows typing and paste so keys never leak into the draft", () => {
  const { composer, press, paste, type, sent } = makeHarness();
  composer.openApprovalOverlay(request());

  type("abc");
  paste("sneaky");
  press({ name: "n", sequence: "n" }); // deny, close the overlay
  // Enter on an empty draft is a no-op (no submit frame): a sentinel typed
  // after the deny proves nothing leaked — the submission is ONLY the sentinel.
  type("X");
  press({ name: "return" });

  expect(sent.find((m) => m.type === "input.submit")?.text).toBe("X");
});

test("Ctrl+C keeps its cancel path while the overlay is open", () => {
  const { composer, press, overlayLayer, sent } = makeHarness();
  composer.openApprovalOverlay(request());

  press({ name: "c", ctrl: true });

  expect(sent).toContainEqual({ type: "input.cancel" });
  // Cancelling the turn is not a decision: the overlay stays until one is made
  // (or the Python side times the request out into a deny).
  expect(findDeep(overlayLayer, "approval-overlay")).not.toBeNull();
});

test("the overlay survives ordinary footer re-renders instead of flashing away", () => {
  const { composer, overlayLayer } = makeHarness();
  composer.openApprovalOverlay(request({ choices: CHOICES }));

  composer.rerender();

  const overlays = overlayLayer
    .getChildren()
    .filter((child) => child.id === "approval-overlay");
  expect(overlays.length).toBe(1);
});

test("overlay chrome and rows use active THEME tokens", () => {
  const { composer, overlayLayer } = makeHarness();
  composer.openApprovalOverlay(request({ choices: CHOICES }));

  const overlay = findDeep(overlayLayer, "approval-overlay");
  expect(overlay.options.borderColor).toBe(THEME.warning);
  expect(overlay.options.backgroundColor).toBe(THEME.overlayBg);
  expect(findDeep(overlay, "approval-overlay-tool").options.fg).toBe(THEME.text);
  expect(findDeep(overlay, "approval-overlay-summary").options.fg).toBe(THEME.muted);
  expect(findDeep(overlay, "approval-overlay-choice-0").options.fg).toBe(THEME.brandAccentSoft);
  expect(findDeep(overlay, "approval-overlay-choice-1").options.fg).toBe(THEME.muted);
  expect(findDeep(overlay, "approval-overlay-hint").options.fg).toBe(THEME.detailText);
});

test("an approval request closes an open theme picker instead of stacking overlays", () => {
  const { composer, press, overlayLayer, sent } = makeHarness();
  composer.openThemePicker();
  composer.openApprovalOverlay(request());

  expect(findDeep(overlayLayer, "theme-picker")).toBeNull();
  expect(findDeep(overlayLayer, "approval-overlay")).not.toBeNull();

  // Approval keys drive the approval overlay, not the (closed) picker.
  press({ name: "y", sequence: "y" });
  expect(sent).toContainEqual({
    type: "approval.response", id: "appr-1", approved: true, choice: null,
  });
});

test("approval.dismiss closes the overlay with one footer redraw", () => {
  const { composer, press, overlayLayer, sent, renderRequests } = makeHarness();
  composer.openApprovalOverlay(request());
  const beforeDismiss = renderRequests();

  // A dismiss for some other (older) request must not touch the live overlay.
  composer.dismissApprovalOverlay("appr-0");
  expect(findDeep(overlayLayer, "approval-overlay")).not.toBeNull();
  expect(renderRequests()).toBe(beforeDismiss);

  // The matching dismiss closes the overlay without emitting a decision:
  // Python already resolved the request, so a response would only be dropped.
  composer.dismissApprovalOverlay("appr-1");
  expect(findDeep(overlayLayer, "approval-overlay")).toBeNull();
  expect(renderRequests()).toBe(beforeDismiss + 1);
  expect(sent.filter((m) => m.type === "approval.response")).toEqual([]);

  // Keys reach the composer again once the modal is gone: a bare "y" is
  // ordinary typed input, never a decision for the dismissed request.
  press({ name: "y", sequence: "y" });
  expect(sent.filter((m) => m.type === "approval.response")).toEqual([]);
});

test("approval.dismiss with no overlay open is a safe no-op", () => {
  const { composer, overlayLayer } = makeHarness();
  composer.dismissApprovalOverlay("appr-1");
  expect(findDeep(overlayLayer, "approval-overlay")).toBeNull();
});
