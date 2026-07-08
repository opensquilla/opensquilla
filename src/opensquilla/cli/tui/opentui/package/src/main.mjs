#!/usr/bin/env node
import process from "node:process";
import { THEME, applyTheme, onThemeApplied } from "./theme.mjs";
import { registerThemeStyles } from "./syntaxTheme.mjs";
import { noticeContent, recolorNoticeNodes } from "./ansiNotice.mjs";
import { clampFooterHeight, copySelectionToClipboard, isPinnedToBottom, stripTerminalControls } from "./primitives.mjs";
import { createComposer } from "./composer.mjs";
import { createTurnFlow, createTurnView } from "./turnView.mjs";
import { createIpc, createDispatcher } from "./ipc.mjs";

const HELP = `OpenSquilla OpenTUI footer host

Usage:
  bun src/main.mjs

IPC:
  reads Python JSON lines from fd 3 and writes host JSON lines to fd 4.
`;

if (import.meta.main && (process.argv.includes("--help") || process.argv.includes("-h"))) {
  process.stdout.write(HELP);
  process.exit(0);
}

const FROM_PYTHON_FD = Number(process.env.OPENSQUILLA_OPENTUI_FROM_PYTHON_FD ?? "3");
const TO_PYTHON_FD = Number(process.env.OPENSQUILLA_OPENTUI_TO_PYTHON_FD ?? "4");
const FOOTER_HEIGHT = 6;
// Footer height clamped to the terminal so a very short pane never overflows it.
const footerRows = (h) => clampFooterHeight(FOOTER_HEIGHT, h);

// Decide, BEFORE a transcript mutation, whether the view should snap back to
// the bottom after it. Being verifiably at the bottom always re-engages
// following: the ScrollBox flags EVERY wheel event in _hasManualScroll — even
// the wheel-down that lands exactly on the bottom row — and its own reengage
// check only clears the flag when a layout pass grows content by at most one
// row, so trusting a stale flag would leave the rest of a streaming turn
// below the fold after the user wheels back down. Clearing it here treats a
// verified return to the bottom as re-consent to follow, while a wheel-up
// hold (not at bottom) leaves the flag untouched. Exported for the bun
// contract tests.
export function shouldFollowBottom(scrollBox) {
  const atBottom = isPinnedToBottom(scrollBox.scrollTop, scrollBox.scrollHeight, scrollBox.height, 0);
  if (atBottom) scrollBox._hasManualScroll = false;
  return atBottom;
}

// Host-local escape hatch. Every quit key normally routes over IPC (Ctrl+C ->
// input.cancel, Ctrl+D -> input.eof) and Python drives shutdown — but a
// wedged or absent parent would otherwise trap the user in the alternate
// screen with raw mode on. Two Ctrl+C presses in quick succession tear the
// host down locally and exit 130 — but ONLY presses the composer routed to
// the interrupt path (empty input, no modal overlay) count toward the chord:
// a press consumed to clear a draft, or swallowed by the theme picker, must
// disarm it, or the routine clear-then-cancel double-press would hard-kill a
// healthy session. Construct BEFORE composer.install() so the per-press reset
// listener runs ahead of the composer's handler, and call install() after it
// so the chord check observes what the composer did with the press.
export const DOUBLE_CTRL_C_MS = 1200;
export function createCtrlCExitHatch({ keyInput, isOverlayOpen, onExit, windowMs = DOUBLE_CTRL_C_MS, now = Date.now }) {
  let sentCancel = false; // did the composer forward THIS press as input.cancel?
  let lastCtrlCAt = 0;
  keyInput?.on?.("keypress", (key) => {
    if (key?.ctrl && key?.name === "c") sentCancel = false;
  });
  return {
    // Route the composer's outbound frames through here so the hatch can see
    // which Ctrl+C presses actually reached the interrupt path.
    noteHostMessage(m) {
      if (m?.type === "input.cancel") sentCancel = true;
    },
    install() {
      keyInput?.on?.("keypress", (key) => {
        if (!key?.ctrl || key?.name !== "c") return;
        if (!sentCancel || isOverlayOpen()) {
          lastCtrlCAt = 0; // a consumed press disarms the chord entirely
          return;
        }
        const at = now();
        if (at - lastCtrlCAt <= windowMs) {
          onExit();
          return;
        }
        lastCtrlCAt = at;
      });
    },
  };
}

// The live renderer, exposed to main().catch: a failure after the renderer
// enters the alternate screen must still restore the terminal on exit.
let bootRenderer = null;

async function main() {
  // Resolve the active theme before anything reads THEME (unknown names fall
  // back to the default). Set with OPENSQUILLA_TUI_THEME=<name>; switch live with
  // the /theme slash command, which sends a theme.set message handled below.
  applyTheme(process.env.OPENSQUILLA_TUI_THEME);

  const { BoxRenderable, TextRenderable, ScrollBoxRenderable, MarkdownRenderable, SyntaxStyle, createCliRenderer } = await import("@opentui/core");

  const renderer = await createCliRenderer({
    screenMode: "alternate-screen",
    exitOnCtrlC: false,
    // OpenTUI routes wheel events to ScrollBox without touching input history.
    useMouse: true,
    // The UI owns an opaque dark background on every surface so it renders the
    // same on any terminal theme (a transparent base made near-white text
    // invisible on light terminals) and the terminal diff always clears cells.
    backgroundColor: THEME.appBg,
  });
  bootRenderer = renderer;
  // Color the markdown answer body from the active theme. A bare SyntaxStyle has
  // no "default" style, so unstyled paragraph text would fall back to an
  // invisible light foreground on light themes. Register the theme's tokens now
  // and refresh them in place on every live /theme switch.
  const syntaxStyle = SyntaxStyle.create();
  registerThemeStyles(syntaxStyle, THEME);
  onThemeApplied((t) => {
    registerThemeStyles(syntaxStyle, t);
    renderer.requestRender?.();
  });

  const conversationBox = new ScrollBoxRenderable(renderer, {
    id: "conversation",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height: Math.max(1, (renderer.terminalHeight ?? 24) - footerRows(renderer.terminalHeight ?? 24)),
    backgroundColor: THEME.appBg,
    stickyScroll: true,
    stickyStart: "bottom",
    scrollY: true,
    scrollX: false,
    viewportCulling: true,
  });
  renderer.root.add(conversationBox);
  // Keyboard input belongs to the composer alone. A click or drag-select on
  // the transcript must not focus the ScrollBox: a focused ScrollBox registers
  // its own keypress handler, and every arrow/PageUp/j/k/h/l press would then
  // drive the transcript scroller AND the composer at once. Wheel scrolling
  // dispatches by mouse hit-test, so it keeps working without focus.
  conversationBox.focusable = false;

  const inputBox = new BoxRenderable(renderer, {
    id: "input-region",
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: footerRows(renderer.terminalHeight ?? 24),
    // Opaque so the footer fully repaints every frame; without it, cells vacated
    // when the composer/router boxes move on resize/reflow keep stale glyphs.
    backgroundColor: THEME.footerBg,
  });
  renderer.root.add(inputBox);

  // Full-screen, top-of-stack host for transient floating UI (completion menu,
  // and any future confirm/hint popups). Lives as a root sibling of the
  // conversation and footer so overlays never bleed into the scrollback buffer
  // or get clipped by the fixed-height footer; its high zIndex keeps it painted
  // above both. shouldFill:false is critical — a BoxRenderable fills its whole
  // rectangle with the background color by default, and a full-screen filled
  // box would paint over the conversation the moment a menu opens. The layer
  // must stay transparent so only the mounted overlay nodes actually draw.
  const overlayLayer = new BoxRenderable(renderer, {
    id: "overlay-layer",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    zIndex: 1000,
    shouldFill: false,
    // Start hidden. A full-screen, top-zIndex layer participates in mouse
    // hit-testing even with shouldFill:false, so a permanently-present overlay
    // swallows wheel events and the conversation ScrollBox can never scroll.
    // visible:false makes hit-testing pass through to the ScrollBox underneath;
    // the composer flips it visible only while a completion menu is mounted.
    visible: false,
  });
  renderer.root.add(overlayLayer);

  const ipc = createIpc({ fromFd: FROM_PYTHON_FD, toFd: TO_PYTHON_FD });
  // Escape hatch (see createCtrlCExitHatch): created before the composer so
  // its per-press reset runs first, armed only by presses the composer routed
  // to the interrupt path, and installed after the composer's own handler.
  const exitHatch = createCtrlCExitHatch({
    keyInput: renderer.keyInput,
    isOverlayOpen: () => Boolean(overlayLayer.visible),
    onExit: () => {
      try { renderer.destroy(); } catch { /* exiting regardless */ }
      process.exit(130);
    },
  });
  const composer = createComposer({
    renderer,
    BoxRenderable,
    TextRenderable,
    conversationBox,
    inputBox,
    overlayLayer,
    footerHeight: FOOTER_HEIGHT,
    sendHostMessage: (m) => {
      exitHatch.noteHostMessage(m);
      ipc.send(m);
    },
  });
  composer.install();
  exitHatch.install();

  let scrollbackSeq = 0;
  let statusActive = false;
  let pulseFrame = 0;

  const turnDeps = { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, conversationBox };
  // flow owns which turn view receives each protocol event (queued-prompt
  // routing, late-block tolerance) and retains every turn ever created so a
  // resize can reflow ALL of them (their baked full-width header rules don't
  // re-rule themselves). The conversation already retains every turn box, so
  // this only adds a reference, not a copy.
  const flow = createTurnFlow((id) => createTurnView(turnDeps, id ?? scrollbackSeq++));
  // Scrollback + notice lines live outside any turn view; register each with
  // the semantic token its color came from so a live /theme switch can
  // re-point it (renderables capture the color VALUE at creation).
  const looseNodes = [];

  // A live /theme switch mutates THEME/STATUS in place and fires this event.
  // Already-rendered turn nodes captured their fg at creation, so recolor every
  // turn's chrome + blocks here — plus the loose scrollback/notice lines; the
  // syntaxStyle listener above handles markdown spans. Force a full repaint so
  // the new background lands cleanly under old cells. (No turns exist at the
  // initial applyTheme, so this is a no-op then.)
  onThemeApplied(() => {
    for (const t of flow.turns) t.recolor?.();
    recolorNoticeNodes(looseNodes, THEME);
    renderer.forceFullRepaintRequested = true;
    renderer.requestRender?.();
  });

  // Keep the conversation pinned to the newest content as it grows. stickyScroll
  // does not re-follow while a child (e.g. a streaming answer) grows in place, so
  // we explicitly snap to the bottom after a mutation — but never while the user
  // has scrolled away: shouldFollowBottom holds while they read history and
  // re-consents the engine's manual-scroll flag once they wheel back down to
  // the bottom, so following always resumes there.
  function scrollConversationToBottom() {
    conversationBox.scrollTop = conversationBox.scrollHeight;
  }
  function withBottomFollow(mutate) {
    const pinned = shouldFollowBottom(conversationBox);
    mutate();
    if (pinned) scrollConversationToBottom();
  }

  const dispatch = createDispatcher({
    turnBegin: (m) => { flow.ensure(m.id); },
    turnEnd: (m) => flow.endTurn(Boolean(m?.cancelled)),
    turnStatus: (m) => {
      statusActive = Boolean(m.active ?? statusActive);
      composer.setTurnStatus(m);
    },
    composerSet: (m) => composer.setComposerState(m),
    completionContext: (m) => composer.setCompletionContext(m),
    completionResponse: (m) => composer.applyCompletionResponse(m),
    routerUpdate: (m) => composer.setRouterState(m),
    blockBegin: (m) => withBottomFollow(() => flow.turnForBlock().begin(m.id, m.kind, m.meta)),
    blockAppend: (m) => withBottomFollow(() => flow.active()?.append(m.id, m.delta)),
    blockUpdate: (m) => withBottomFollow(() => flow.active()?.update(m.id, m.patch)),
    blockEnd: (m) => flow.active()?.end(m.id),
    // prompt.echo arrives BEFORE turn.begin (it is emitted by the input-echo
    // hook) — and it also fires immediately for a submission QUEUED behind a
    // still-streaming turn. The flow gives a queued echo its own view (reusing
    // the live turn would close its card mid-stream and glue its usage line to
    // the new prompt) and adopts that view when its turn.begin arrives.
    promptEcho: (m) => {
      const turn = flow.turnForPrompt();
      turn.begin(`prompt-${scrollbackSeq++}`, "prompt", { text: String(m.text ?? "") });
      // The user just submitted — always snap to the bottom so they see their
      // message and the incoming response, even if they had scrolled up.
      scrollConversationToBottom();
    },
    // model.text is a minor queue marker. Render it as a thinking line (purple
    // ✻) by seeding a thinking block and flushing it immediately on end.
    modelText: (m) => {
      withBottomFollow(() => {
        const turn = flow.ensure();
        const id = `note-${scrollbackSeq++}`;
        turn.begin(id, "thinking", {});
        turn.append(id, String(m.text ?? ""));
        turn.end(id);
      });
    },
    // Theme control from the /theme slash command: set a named theme directly, or
    // open the interactive picker (arrow-key live preview). Both repaint every
    // owned surface; new content picks up THEME automatically.
    themeSet: (m) => composer.applyHostTheme(m.name),
    themePick: () => composer.openThemePicker(),
    // Tool-approval prompt from the Python side: the composer mounts a modal
    // overlay and answers with one approval.response frame when the user
    // decides (Python treats no answer as a deny after its own timeout).
    approvalRequest: (m) => composer.openApprovalOverlay(m),
    // Python stopped waiting on a request (timeout / turn cancel): close the
    // matching overlay so a stale modal cannot swallow the next keypress.
    approvalDismiss: (m) => composer.dismissApprovalOverlay(m.id),
    // scrollback is a lifecycle-less raw line dump (no begin/end); rendered inline
    // here rather than as a block — the only orchestration-layer rendering exception.
    scrollback: (m) => {
      const node = new TextRenderable(renderer, {
        id: `sb-${scrollbackSeq++}`,
        content: stripTerminalControls(String(m.text ?? "")),
        fg: THEME.muted,
      });
      looseNodes.push({ node, token: "muted" });
      withBottomFollow(() => conversationBox.add(node));
      renderer.requestRender?.();
    },
    // Command notices captured from the Python side's stdout (slash-command and
    // runtime messages). They arrive one Rich-rendered line at a time; render
    // them INSIDE the conversation in the active theme's semantic color (never on
    // the terminal, so they can no longer bleed over or clip against the host).
    notice: (m) => {
      const spec = noticeContent(m.text);
      if (!spec) return; // drop blank spacer lines
      const node = new TextRenderable(renderer, {
        id: `notice-${scrollbackSeq++}`,
        content: spec.content,
        fg: THEME[spec.token] ?? THEME.detailText,
      });
      looseNodes.push({ node, token: spec.token });
      withBottomFollow(() => conversationBox.add(node));
      renderer.requestRender?.();
    },
    shutdown: () => { renderer.destroy(); process.exit(0); },
    // An unknown inbound type is a protocol gap (a newer Python against an
    // older host), not a host failure: reply with a dedicated frame instead of
    // an error, which the Python side treats as fatal. Older Python skips
    // unknown host frames tolerantly, so this degrades gracefully everywhere.
    unknown: (m) => ipc.send({ type: "protocol.unknown", messageType: m.type }),
  });

  // Select-to-copy. A mouse-capturing TUI never receives the terminal's
  // Cmd/Ctrl+C (the terminal intercepts the shortcut), so mirror the OpenTUI
  // selection into the system clipboard via OSC 52 as the user drags. Drag-select
  // any conversation text and it is copied; paste anywhere as usual. Requires a
  // terminal with OSC 52 write support (iTerm2, kitty, WezTerm, Alacritty, or tmux
  // with `set-clipboard on`); macOS Terminal.app users can Option-drag to use the
  // terminal's own selection instead.
  renderer.on?.("selection", (selection) => copySelectionToClipboard(renderer, selection));

  renderer.on?.("resize", () => {
    const h = renderer.terminalHeight ?? 24;
    const fh = footerRows(h);
    inputBox.height = fh; // clamp so a short terminal never overflows the footer
    conversationBox.height = Math.max(1, h - fh);
    composer.onResize();
    // Reflow every existing turn's full-width header rule to the new width, so a
    // resize re-rules the cards instead of leaving baked rules to wrap or strand.
    // (Each turn skips itself when its ruled width is already current.)
    for (const t of flow.turns) t.relayout?.();
    // Force a FULL repaint after a resize. OpenTUI's standard (alternate-screen)
    // resize path renders a DIFF, so cells the old — wider/taller — layout
    // occupied are left uncleared: e.g. the router box's previous position and
    // the composer's old right border bleed through as stale glyphs when the
    // window shrinks. Forcing a full repaint clears the vacated cells.
    renderer.forceFullRepaintRequested = true;
    renderer.requestRender?.();
    const w = renderer.terminalWidth ?? 0;
    if (w && h) ipc.send({ type: "resize", width: w, height: h });
  });

  // Single always-on pulse interval. The body is gated on statusActive so an
  // idle TUI does not rerender (and flicker) every 180ms; while a turn runs,
  // both the running-tool glyphs and the composer status pill animate.
  setInterval(() => {
    if (!statusActive) return;
    pulseFrame += 1;
    try {
      flow.active()?.refreshPulse(pulseFrame);
      composer.tickPulse(pulseFrame);
      renderer.requestRender?.();
    } catch {
      // A single frame's render error must never throw out of the always-on
      // pulse interval — an uncaught throw here would stop the timer and freeze
      // the TUI. Skip this tick; the next one re-renders from current state.
    }
  }, 180).unref?.();

  ipc.send({ type: "ready" });
  ipc.start(
    (m) => {
      try {
        dispatch(m);
      } catch (e) {
        ipc.send({ type: "error", message: e instanceof Error ? e.message : String(e) });
      }
    },
    () => { renderer.destroy(); process.exit(0); },
  );
}

// Boot only when run as the entry script (`bun src/main.mjs`, how the Python
// bridge always spawns the host): the exported helpers above are imported by
// the bun contract tests, and importing this module must never start a
// renderer or enter the alternate screen.
if (import.meta.main) {
  main().catch((error) => {
    // A failure after the renderer entered the alternate screen must restore the
    // terminal (leave alt screen, raw mode + mouse tracking off) before exiting:
    // process.exit never emits beforeExit, so the engine's own restore hook does
    // not run, and the error itself goes to a pipe the user cannot see.
    try { bootRenderer?.destroy(); } catch { /* best-effort restore */ }
    process.stderr.write(`${error?.message ?? error}\n`);
    process.exit(1);
  });
}
