import assert from "node:assert/strict";
import test from "node:test";

import {
  installConversationWheelHandler,
  invalidateConversationViewport,
  scheduleConversationLayoutCommit,
} from "./opentuiCompat.mjs";
import { createStableTranscriptScroller } from "./stableTranscriptScroller.mjs";

function harness() {
  const scrollBox = { scrollTop: 80, scrollHeight: 100, height: 20 };
  const scheduled = [];
  const states = [];
  let invalidations = 0;
  const scroller = createStableTranscriptScroller({
    scrollBox,
    renderer: {},
    scheduleFrame: (callback) => { scheduled.push(callback); return callback; },
    cancelFrame: () => {},
    invalidate: () => { invalidations += 1; },
    onStateChange: (state) => states.push(state),
  });
  return { scrollBox, scheduled, states, scroller, invalidations: () => invalidations };
}

test("protected OpenTUI wheel interception stays inside the compatibility adapter", () => {
  const calls = [];
  const scrollBox = {
    onMouseEvent(event) { calls.push(["native", event.type]); return "native-result"; },
  };
  assert.equal(installConversationWheelHandler(scrollBox, (event) => {
    calls.push(["app", event.type]);
    return event.type === "scroll";
  }), true);

  assert.equal(scrollBox.onMouseEvent({ type: "scroll" }), true);
  assert.deepEqual(calls, [["app", "scroll"]]);
  assert.equal(scrollBox.onMouseEvent({ type: "down" }), "native-result");
  assert.deepEqual(calls, [["app", "scroll"], ["native", "down"]]);
});

test("routine viewport invalidation never requests a full framebuffer repaint", () => {
  let viewportRenders = 0;
  let rendererRenders = 0;
  const renderer = {
    forceFullRepaintRequested: false,
    requestRender: () => { rendererRenders += 1; },
  };
  const scrollBox = {
    requestRender: () => { viewportRenders += 1; },
  };

  invalidateConversationViewport(renderer, scrollBox);

  assert.equal(renderer.forceFullRepaintRequested, false);
  assert.equal(viewportRenders, 1);
  assert.equal(rendererRenders, 0);
});

test("layout commits run after Yoga calculation and before the paint callback returns", () => {
  let frameCallback = null;
  let calculated = 0;
  const renderer = {
    root: { calculateLayout: () => { calculated += 1; } },
    setFrameCallback: (callback) => { frameCallback = callback; },
    removeFrameCallback: (callback) => {
      if (frameCallback === callback) frameCallback = null;
    },
    requestRender: () => {},
  };
  const bar = { scrollSize: 10, viewportSize: 10 };
  const scrollBox = {
    content: { getLayoutNode: () => ({ getComputedLayout: () => ({ height: 120 }) }) },
    viewport: { getLayoutNode: () => ({ getComputedLayout: () => ({ height: 30 }) }) },
    verticalScrollBar: bar,
  };
  const seen = [];
  scheduleConversationLayoutCommit(renderer, scrollBox, () => {
    seen.push([calculated, bar.scrollSize, bar.viewportSize]);
  });

  assert.equal(typeof frameCallback, "function");
  frameCallback();
  assert.deepEqual(seen, [[1, 120, 30]]);
  assert.equal(frameCallback, null);
});

test("wheel updates are coalesced and upward scrolling enters held mode", () => {
  const h = harness();
  h.scroller.handleWheel({ type: "scroll", scroll: { direction: "up", delta: 1 } });
  h.scroller.handleWheel({ type: "scroll", scroll: { direction: "up", delta: 2 } });
  assert.equal(h.scheduled.length, 1);
  h.scheduled.shift()();
  assert.equal(h.scrollBox.scrollTop, 71);
  assert.equal(h.scroller.followMode, "held");
  assert.equal(h.invalidations(), 1);
});

test("held viewport does not jump when streaming content grows", () => {
  const h = harness();
  h.scroller.handleWheel({ scroll: { direction: "up", delta: 1 } });
  h.scheduled.shift()();
  const top = h.scrollBox.scrollTop;
  h.scroller.mutate(() => { h.scrollBox.scrollHeight += 40; });
  h.scheduled.shift()(); // pre-paint layout/anchor commit
  assert.equal(h.scrollBox.scrollTop, top);
  assert.equal(h.scroller.snapshot().newOutput, true);
});

test("upward intent survives a transient no-range streaming layout", () => {
  const scrollBox = {
    scrollTop: 0,
    scrollHeight: 28,
    height: 28,
    stickyScroll: true,
  };
  const scheduled = [];
  const scroller = createStableTranscriptScroller({
    scrollBox,
    renderer: {},
    scheduleFrame: (callback) => { scheduled.push(callback); return callback; },
    cancelFrame: () => {},
    invalidate: () => {},
  });

  scroller.handleWheel({ type: "scroll", scroll: { direction: "up", delta: 2 } });
  scheduled.shift()();
  assert.equal(scroller.followMode, "held");
  assert.equal(scrollBox.stickyScroll, false);

  scroller.mutate(() => { scrollBox.scrollHeight = 34; });
  scheduled.shift()();
  assert.equal(scrollBox.scrollTop, 0);
  assert.equal(scroller.snapshot().newOutput, true);

  scroller.followLatest();
  assert.equal(scrollBox.scrollTop, 6);
  assert.equal(scrollBox.stickyScroll, true);
  assert.equal(scroller.followMode, "following");
});

test("returning to the bottom resumes following", () => {
  const h = harness();
  h.scroller.handleWheel({ scroll: { direction: "up", delta: 1 } });
  h.scheduled.shift()();
  h.scroller.followLatest();
  assert.equal(h.scrollBox.scrollTop, 80);
  assert.equal(h.scroller.followMode, "following");
  h.scroller.mutate(() => { h.scrollBox.scrollHeight += 10; });
  h.scheduled.shift()();
  assert.equal(h.scrollBox.scrollTop, 90);
});

test("streaming mutations coalesce into one pre-paint anchor restore", () => {
  const h = harness();
  h.scroller.handleWheel({ scroll: { direction: "up", delta: 1 } });
  h.scheduled.shift()();
  const top = h.scrollBox.scrollTop;

  h.scroller.mutate(() => { h.scrollBox.scrollHeight += 10; });
  h.scroller.mutate(() => { h.scrollBox.scrollHeight += 10; });
  h.scroller.mutate(() => { h.scrollBox.scrollHeight += 10; });
  assert.equal(h.scheduled.length, 1);
  h.scheduled.shift()();

  assert.equal(h.scrollBox.scrollTop, top);
  assert.equal(h.scroller.snapshot().newOutput, true);
});
