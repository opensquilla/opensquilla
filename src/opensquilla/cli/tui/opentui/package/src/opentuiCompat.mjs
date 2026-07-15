// Transcript viewport culling remains disabled until the real-terminal
// framebuffer gate proves that an OpenTUI release is safe for dynamic-height
// turns. A wheel gesture therefore only needs a normal dirty render. Forcing a
// complete terminal repaint here makes every scroll frame clear and redraw the
// alternate screen, which is visible as a flash in Terminal.app and embedded
// terminals.
//
// Keep this compatibility boundary even though requestRender() is public: a
// future OpenTUI upgrade can change the narrow invalidation strategy here
// without leaking renderer internals into the product components.
export function invalidateConversationViewport(renderer, scrollBox) {
  if (typeof scrollBox?.requestRender === "function") {
    scrollBox.requestRender();
    return;
  }
  renderer?.requestRender?.();
}

// OpenTUI recalculates Yoga immediately before painting a frame. Transcript
// mutations need to restore their semantic anchor *after* that calculation but
// *before* the new frame reaches the terminal; restoring from the previous
// frame's height either jumps the held viewport or paints one visibly wrong
// frame first. Keep the one OpenTUI-specific pre-paint hook here.
//
// `setFrameCallback` is public in OpenTUI 0.4.x. The small scrollbar sync is a
// compatibility shim for the ordering inside that public callback: ScrollBox's
// normal size-change callback has not run yet, so its public scrollTop setter
// would otherwise clamp against the previous frame's range. Product components
// never reach into those host details themselves.
export function scheduleConversationLayoutCommit(
  renderer,
  scrollBox,
  callback,
  {
    scheduleFallback = (fn) => setTimeout(fn, 0),
    cancelFallback = clearTimeout,
  } = {},
) {
  if (typeof callback !== "function") return () => {};
  let active = true;
  let fallback = null;

  const prepareLayout = () => {
    renderer?.root?.calculateLayout?.();
    const contentLayout = scrollBox?.content?.getLayoutNode?.()?.getComputedLayout?.();
    const viewportLayout = scrollBox?.viewport?.getLayoutNode?.()?.getComputedLayout?.();
    const bar = scrollBox?.verticalScrollBar;
    if (bar && Number.isFinite(Number(contentLayout?.height))) {
      bar.scrollSize = Math.max(0, Number(contentLayout.height));
    }
    if (bar && Number.isFinite(Number(viewportLayout?.height))) {
      bar.viewportSize = Math.max(0, Number(viewportLayout.height));
    }
  };

  const run = () => {
    if (!active) return;
    active = false;
    if (fallback !== null) cancelFallback(fallback);
    fallback = null;
    prepareLayout();
    callback();
  };

  if (
    typeof renderer?.setFrameCallback === "function"
    && typeof renderer?.removeFrameCallback === "function"
  ) {
    const onFrame = () => {
      renderer.removeFrameCallback(onFrame);
      run();
    };
    renderer.setFrameCallback(onFrame);
    renderer.requestRender?.();
    return () => {
      if (!active) return;
      active = false;
      renderer.removeFrameCallback(onFrame);
    };
  }

  // Synthetic/unit renderers do not expose frame callbacks. Their geometry is
  // synchronous, so a scheduled fallback preserves the same coalescing
  // contract without depending on production renderer internals.
  fallback = scheduleFallback(run);
  return () => {
    if (!active) return;
    active = false;
    if (fallback !== null) cancelFallback(fallback);
    fallback = null;
  };
}

// ScrollBox.onMouseEvent is protected rather than public in OpenTUI's type
// surface. The application needs to intercept wheel input before the engine's
// own accelerator, so keep that one dependency inside this adapter and protect
// it with the real-terminal wheel gate on every OpenTUI upgrade.
export function installConversationWheelHandler(scrollBox, handleWheel) {
  if (!scrollBox || typeof handleWheel !== "function") return false;
  const nativeMouseHandler = typeof scrollBox.onMouseEvent === "function"
    ? scrollBox.onMouseEvent.bind(scrollBox)
    : null;
  scrollBox.onMouseEvent = (event) => {
    if (event?.type === "scroll" && handleWheel(event)) return true;
    return nativeMouseHandler?.(event);
  };
  return true;
}
