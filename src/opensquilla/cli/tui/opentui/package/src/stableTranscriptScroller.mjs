import { isPinnedToBottom } from "./primitives.mjs";
import {
  invalidateConversationViewport,
  scheduleConversationLayoutCommit,
} from "./opentuiCompat.mjs";

export const SCROLL_ROWS_PER_TICK = 3;
export const SCROLL_MAX_ROWS_PER_FRAME = 24;
export const SCROLL_FRAME_MS = 16;

function directionOf(event) {
  const direction = String(event?.scroll?.direction ?? "").toLowerCase();
  if (direction === "up") return -1;
  if (direction === "down") return 1;
  const delta = Number(event?.scroll?.delta ?? event?.deltaY ?? 0);
  return delta < 0 ? -1 : delta > 0 ? 1 : 0;
}

function tickCount(event) {
  const raw = Math.abs(Number(event?.scroll?.delta ?? event?.deltaY ?? 1));
  return Math.max(1, Number.isFinite(raw) ? Math.round(raw) : 1);
}

function maxScrollTop(scrollBox) {
  return Math.max(0, Number(scrollBox?.scrollHeight ?? 0) - Number(scrollBox?.height ?? 0));
}

function clampRow(value, scrollBox) {
  return Math.max(0, Math.min(maxScrollTop(scrollBox), Number(value) || 0));
}

export function createStableTranscriptScroller({
  scrollBox,
  renderer,
  beforeWheel = null,
  captureAnchor = null,
  restoreAnchor = null,
  onStateChange = null,
  scheduleFrame = (callback) => setTimeout(callback, SCROLL_FRAME_MS),
  cancelFrame = clearTimeout,
  invalidate = invalidateConversationViewport,
  scheduleLayout = null,
} = {}) {
  let followMode = "following";
  let anchor = null;
  let surfaceEpoch = 0;
  let pendingRows = 0;
  let pendingDirection = 0;
  let frame = null;
  let layoutCancel = null;
  let layoutPending = null;
  let newOutput = false;

  function snapshot() {
    return { followMode, anchor, surfaceEpoch, newOutput };
  }

  function notify() {
    onStateChange?.(snapshot());
  }

  function setMode(mode) {
    // The application owns follow/held semantics. Disable OpenTUI's public
    // sticky-scroll behavior as soon as an upward gesture declares held mode;
    // otherwise a streaming child's deferred Yoga height can grow after the
    // wheel frame and silently snap the viewport back to the bottom before the
    // application has a scrollable range to mark as manual.
    if (scrollBox && mode === "held") scrollBox.stickyScroll = false;
    else if (scrollBox && mode === "following") scrollBox.stickyScroll = true;
    if (followMode === mode) return;
    followMode = mode;
    notify();
  }

  function recordAnchor() {
    const row = clampRow(scrollBox?.scrollTop ?? 0, scrollBox);
    const resolved = captureAnchor?.(row);
    anchor = resolved && typeof resolved === "object"
      ? resolved
      : { turn_id: "viewport", block_id: "row", row_within_block: row };
  }

  function cancelLayoutCommit() {
    layoutCancel?.();
    layoutCancel = null;
    layoutPending = null;
  }

  function commitLayout() {
    const pending = layoutPending;
    layoutPending = null;
    layoutCancel = null;
    if (!pending || !scrollBox) return;

    // Wheel input may arrive between a transcript mutation and this pre-paint
    // commit. The latest application state always wins: an explicit hold must
    // never be overwritten by the mutation's older following snapshot.
    const target = followMode === "restoring"
      ? pending.restoreMode ?? "held"
      : followMode;
    if (target === "following") {
      scrollBox.scrollTop = maxScrollTop(scrollBox);
      scrollBox.stickyScroll = true;
      anchor = null;
      newOutput = false;
      followMode = "following";
    } else {
      scrollBox.stickyScroll = false;
      const heldTop = Number(pending.heldTop ?? scrollBox.scrollTop ?? 0);
      const heldAnchor = anchor ?? pending.anchor;
      const restored = heldAnchor ? restoreAnchor?.(heldAnchor) : null;
      scrollBox.scrollTop = clampRow(
        Number.isFinite(Number(restored)) ? Number(restored) : heldTop,
        scrollBox,
      );
      followMode = "held";
      if (pending.output) newOutput = true;
      recordAnchor();
    }
    notify();
    invalidate(renderer, scrollBox);
  }

  function queueLayoutCommit({ output = false, restoreMode = null } = {}) {
    if (layoutPending) {
      layoutPending.output ||= Boolean(output);
      if (restoreMode) layoutPending.restoreMode = restoreMode;
      return;
    }
    if (followMode !== "following" && followMode !== "restoring" && !anchor) {
      recordAnchor();
    }
    layoutPending = {
      anchor,
      heldTop: Number(scrollBox?.scrollTop ?? 0),
      output: Boolean(output),
      restoreMode,
    };
    const install = typeof scheduleLayout === "function"
      ? scheduleLayout
      : (callback) => scheduleConversationLayoutCommit(
        renderer,
        scrollBox,
        callback,
        { scheduleFallback: scheduleFrame, cancelFallback: cancelFrame },
      );
    const cancel = install(commitLayout);
    // A synthetic scheduler may execute synchronously. Do not retain a stale
    // cancellation handle after that commit has already cleared the pending
    // state.
    if (layoutPending) layoutCancel = cancel;
    else cancel?.();
  }

  function followLatest() {
    if (!scrollBox) return;
    scrollBox.scrollTop = maxScrollTop(scrollBox);
    anchor = null;
    newOutput = false;
    setMode("following");
    notify();
    invalidate(renderer, scrollBox);
    // If Yoga is dirty, the current max is from the prior frame. Re-apply at
    // the pre-paint layout boundary so End/follow never lands one frame short.
    queueLayoutCommit({ restoreMode: "following" });
  }

  function flushWheel() {
    frame = null;
    const rows = pendingRows;
    pendingRows = 0;
    pendingDirection = 0;
    if (!rows || !scrollBox) return;
    scrollBox.scrollTop = clampRow(Number(scrollBox.scrollTop ?? 0) + rows, scrollBox);
    const atBottom = isPinnedToBottom(
      scrollBox.scrollTop,
      scrollBox.scrollHeight,
      scrollBox.height,
      0,
    );
    // An upward gesture is an explicit hold intent even when OpenTUI has not
    // committed the streaming child's new Yoga height yet. Only downward
    // movement that actually reaches the bottom may re-enable following.
    if (atBottom && rows > 0) {
      anchor = null;
      newOutput = false;
      setMode("following");
    } else {
      recordAnchor();
      setMode("held");
    }
    notify();
    invalidate(renderer, scrollBox);
  }

  function handleWheel(event) {
    beforeWheel?.();
    const direction = directionOf(event);
    if (!direction) return false;
    if (pendingDirection && pendingDirection !== direction) pendingRows = 0;
    pendingDirection = direction;
    const delta = direction * SCROLL_ROWS_PER_TICK * tickCount(event);
    pendingRows = Math.max(
      -SCROLL_MAX_ROWS_PER_FRAME,
      Math.min(SCROLL_MAX_ROWS_PER_FRAME, pendingRows + delta),
    );
    if (direction < 0) {
      recordAnchor();
      setMode("held");
    }
    if (frame === null) frame = scheduleFrame(flushWheel);
    return true;
  }

  function scrollBy(rows) {
    const amount = Number(rows) || 0;
    if (!amount) return false;
    beforeWheel?.();
    if (pendingDirection && Math.sign(amount) !== pendingDirection) pendingRows = 0;
    pendingDirection = Math.sign(amount);
    pendingRows = Math.max(
      -SCROLL_MAX_ROWS_PER_FRAME,
      Math.min(SCROLL_MAX_ROWS_PER_FRAME, pendingRows + amount),
    );
    if (amount < 0) {
      recordAnchor();
      setMode("held");
    }
    if (frame === null) frame = scheduleFrame(flushWheel);
    return true;
  }

  function mutate(mutation, { output = true } = {}) {
    const wasFollowing = followMode === "following";
    if (!wasFollowing && !anchor) recordAnchor();
    const result = mutation();
    queueLayoutCommit({ output: !wasFollowing && output });
    return result;
  }

  function restore(mutation) {
    const prior = followMode;
    const heldTop = Number(scrollBox?.scrollTop ?? 0);
    if (prior !== "following" && !anchor) {
      anchor = captureAnchor?.(heldTop) || null;
    }
    followMode = "restoring";
    notify();
    const result = mutation();
    queueLayoutCommit({ restoreMode: prior === "following" ? "following" : "held" });
    return result;
  }

  function bumpSurfaceEpoch() {
    const restoreMode = followMode === "restoring"
      ? layoutPending?.restoreMode ?? "held"
      : followMode === "following" ? "following" : "held";
    surfaceEpoch += 1;
    pendingRows = 0;
    pendingDirection = 0;
    if (frame !== null) cancelFrame(frame);
    frame = null;
    cancelLayoutCommit();
    followMode = "restoring";
    queueLayoutCommit({ restoreMode });
    invalidate(renderer, scrollBox);
    notify();
  }

  function dispose() {
    if (frame !== null) cancelFrame(frame);
    frame = null;
    cancelLayoutCommit();
  }

  return {
    handleWheel,
    scrollBy,
    mutate,
    restore,
    followLatest,
    bumpSurfaceEpoch,
    dispose,
    snapshot,
    get followMode() { return followMode; },
  };
}
