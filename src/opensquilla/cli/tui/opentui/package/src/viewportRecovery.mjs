import process from "node:process";

// Embedded terminals (including Codex's side terminal) can hide/remount their
// physical alternate-screen surface without giving OpenTUI a useful resize.
// The renderer then believes its old back-buffer is still visible and emits
// only diffs, leaving static cells blank while streaming cells reappear.

// OpenTUI releases debounce their own SIGWINCH handling. Our final pass runs
// after that window so an early stale WriteStream sample cannot overwrite the
// direct getWindowSize() result applied by this controller.
export const VIEWPORT_RECOVERY_SETTLE_MS = 150;

// A periodic full-screen watchdog writes complete frames into terminal
// scrollback if alternate-screen mode was lost. Recovery is event-driven and
// the transcript scroller also calls recover on the first wheel after blur.
// Keep an explicit diagnostic override for testing unusual embedded hosts, but
// never enable it implicitly in production.
export const VIEWPORT_RECOVERY_WATCHDOG_MS = 750;
const VIEWPORT_RECOVERY_MIN_WATCHDOG_MS = 250;
const VIEWPORT_RECOVERY_WATCHDOG_ENV = "OPENSQUILLA_TUI_REPAINT_WATCHDOG_MS";

// A Codex pane remount can forget terminal modes as well as cell contents. A
// full repaint issued while DECSET 1049 is off lands in the ordinary scrollback
// as repeated full-screen logos and leaves the hardware cursor below the
// composer. Re-enter the alternate surface before asking OpenTUI to paint.
export const TERMINAL_SURFACE_REASSERT_SEQUENCE = (
  "\x1b[?1049h" // alternate screen
  + "\x1b[?1004h" // focus reporting
  + "\x1b[?1003h" // all-motion mouse reporting (OpenTUI default)
  + "\x1b[?1006h" // SGR mouse coordinates
  + "\x1b[?2004h" // bracketed paste
);

export function viewportRecoveryWatchdogMs(env = process.env) {
  const explicit = String(env?.[VIEWPORT_RECOVERY_WATCHDOG_ENV] ?? "").trim();
  if (explicit) {
    const parsed = Number(explicit);
    if (Number.isFinite(parsed)) {
      if (parsed <= 0) return 0;
      return Math.max(VIEWPORT_RECOVERY_MIN_WATCHDOG_MS, Math.floor(parsed));
    }
  }

  return 0;
}

export function requestFullRepaint(renderer) {
  if (!renderer) return;
  // OpenTUI exposes no public full-repaint method in the supported 0.4.x line.
  // Isolate the internal hook in this one compatibility module.
  renderer.forceFullRepaintRequested = true;
  renderer.requestRender?.();
}

export function reassertTerminalSurface(output = process.stdout) {
  if (typeof output?.write !== "function") return false;
  try {
    output.write(TERMINAL_SURFACE_REASSERT_SEQUENCE);
    return true;
  } catch {
    return false;
  }
}

function positiveDimension(value) {
  const dimension = Number(value);
  return Number.isFinite(dimension) && dimension > 0 ? Math.floor(dimension) : 0;
}

function terminalViewportSize(output) {
  let direct = null;
  try {
    direct = output?.getWindowSize?.();
  } catch {
    // getWindowSize may throw while an embedded pane is detached. Fall back to
    // cached WriteStream fields; zero/unknown hidden-state geometry is ignored.
  }
  // Some embedded terminals briefly report a zero for only one dimension
  // while a pane is being attached. Treat zero as unavailable per dimension,
  // not as an authoritative size, and fall back to the refreshed stream cache.
  const width = positiveDimension(direct?.[0]) || positiveDimension(output?.columns);
  const height = positiveDimension(direct?.[1]) || positiveDimension(output?.rows);
  return width && height ? { width, height } : null;
}

export function reconcileTerminalViewport(
  renderer,
  output = process.stdout,
  { forceRepaint = false } = {},
) {
  const viewport = terminalViewportSize(output);
  if (!viewport) {
    if (forceRepaint) {
      requestFullRepaint(renderer);
      return "repainted";
    }
    return "unavailable";
  }

  const currentWidth = positiveDimension(renderer?.terminalWidth ?? renderer?.width);
  const currentHeight = positiveDimension(renderer?.terminalHeight ?? renderer?.height);
  const changed = viewport.width !== currentWidth || viewport.height !== currentHeight;
  if (changed && typeof renderer?.resize === "function") {
    renderer.resize(viewport.width, viewport.height);
  }
  if (changed || forceRepaint) requestFullRepaint(renderer);
  if (changed) return "resized";
  return forceRepaint ? "repainted" : "unchanged";
}

export function installTerminalViewportRecovery({
  renderer,
  output = process.stdout,
  signalSource = process,
  settleMs = VIEWPORT_RECOVERY_SETTLE_MS,
  watchdogMs = viewportRecoveryWatchdogMs(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  setIntervalFn = setInterval,
  clearIntervalFn = clearInterval,
  onRecovered = null,
} = {}) {
  let settleTimer = null;
  let watchdogTimer = null;
  let disposed = false;
  // Startup has already established the alternate screen and mouse modes.
  // Re-entering DECSET 1049 on an ordinary wheel event is not a harmless
  // no-op in every terminal: some hosts visibly clear/swap the screen. Only a
  // blur marks the surface as needing recovery before the next received wheel.
  let wheelRecoveryPending = false;

  const recover = () => {
    if (disposed) return "disposed";
    try {
      reassertTerminalSurface(output);
      const result = reconcileTerminalViewport(renderer, output, { forceRepaint: true });
      onRecovered?.(result);
      return result;
    } catch {
      // A transient detached PTY must not stop the renderer's stream loop.
      return "unavailable";
    }
  };

  const scheduleFinalRecovery = () => {
    if (disposed) return;
    if (settleTimer !== null) clearTimer(settleTimer);
    settleTimer = setTimer(() => {
      settleTimer = null;
      recover();
    }, settleMs);
    settleTimer?.unref?.();
  };

  const handleViewportEvent = () => {
    wheelRecoveryPending = false;
    recover();
    scheduleFinalRecovery();
  };
  const handleBlur = () => {
    wheelRecoveryPending = true;
  };
  const recoverBeforeWheel = () => {
    // Receiving an SGR wheel event already proves mouse tracking is active.
    // Never write DECSET 1049 or force a framebuffer repaint on the routine
    // scroll hot path; recover exactly once after a known blur instead.
    if (!wheelRecoveryPending) return "unchanged";
    wheelRecoveryPending = false;
    return recover();
  };

  const removeListener = (source, event, listener) => {
    if (typeof source?.off === "function") source.off(event, listener);
    else source?.removeListener?.(event, listener);
  };
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    if (settleTimer !== null) {
      clearTimer(settleTimer);
      settleTimer = null;
    }
    if (watchdogTimer !== null) {
      clearIntervalFn(watchdogTimer);
      watchdogTimer = null;
    }
    removeListener(output, "resize", handleViewportEvent);
    removeListener(signalSource, "SIGWINCH", handleViewportEvent);
    removeListener(renderer, "focus", handleViewportEvent);
    removeListener(renderer, "blur", handleBlur);
    removeListener(renderer, "destroy", dispose);
  };

  // OpenTUI's documented lifecycle events remain the primary contract. The
  // WriteStream event repairs stale cached geometry; SIGWINCH covers native
  // terminal resizing; focus covers a same-size surface remount.
  output?.on?.("resize", handleViewportEvent);
  signalSource?.on?.("SIGWINCH", handleViewportEvent);
  renderer?.on?.("focus", handleViewportEvent);
  renderer?.on?.("blur", handleBlur);
  renderer?.once?.("destroy", dispose);

  const watchdogDelay = positiveDimension(watchdogMs);
  if (watchdogDelay > 0) {
    watchdogTimer = setIntervalFn(recover, watchdogDelay);
    watchdogTimer?.unref?.();
  }

  return { dispose, recover, recoverBeforeWheel, scheduleFinalRecovery };
}
