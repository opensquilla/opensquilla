#!/usr/bin/env node
import process from "node:process";
import { THEME, applyTheme, onThemeApplied } from "./theme.mjs";
import { registerThemeStyles } from "./syntaxTheme.mjs";
import { parseNotice, isStructuredLine, NOTICE_LEVELS } from "./ansiNotice.mjs";
import { TOOL_INDENT, clampFooterHeight, copySelectionToClipboard, isPinnedToBottom, stripTerminalControls } from "./primitives.mjs";
import { createComposer } from "./composer.mjs";
import { createTurnView } from "./turnView.mjs";
import { createIpc, createDispatcher } from "./ipc.mjs";

const HELP = `OpenSquilla OpenTUI footer host

Usage:
  bun src/main.mjs

IPC:
  reads Python JSON lines from fd 3 and writes host JSON lines to fd 4.
`;

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  process.stdout.write(HELP);
  process.exit(0);
}

const FROM_PYTHON_FD = Number(process.env.OPENSQUILLA_OPENTUI_FROM_PYTHON_FD ?? "3");
const TO_PYTHON_FD = Number(process.env.OPENSQUILLA_OPENTUI_TO_PYTHON_FD ?? "4");
const FOOTER_HEIGHT = 6;
// Footer height clamped to the terminal so a very short pane never overflows it.
const footerRows = (h) => clampFooterHeight(FOOTER_HEIGHT, h);

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
  const composer = createComposer({
    renderer,
    BoxRenderable,
    TextRenderable,
    conversationBox,
    inputBox,
    overlayLayer,
    footerHeight: FOOTER_HEIGHT,
    sendHostMessage: ipc.send,
  });
  composer.install();

  let activeTurn = null;
  // Every turn ever created, so a resize can reflow ALL of them (their baked
  // full-width header rules don't re-rule themselves). The conversation already
  // retains every turn box, so this only adds a reference, not a copy.
  const turns = [];
  let scrollbackSeq = 0;
  let statusActive = false;
  let pulseFrame = 0;
  const turnDeps = { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, conversationBox };
  const ensureTurn = (id) => {
    if (!activeTurn || activeTurn.ended) {
      activeTurn = createTurnView(turnDeps, id ?? scrollbackSeq++);
      turns.push(activeTurn);
    }
    return activeTurn;
  };

  // Keep the conversation pinned to the newest content as it grows. stickyScroll
  // does not re-follow while a child (e.g. a streaming answer) grows in place, so
  // we explicitly snap to the bottom after a mutation — but ONLY if the user was
  // already at the bottom, so scrolling up to read history is never yanked away.
  const SCROLL_PIN_SLACK = 2;
  function scrollConversationToBottom() {
    conversationBox.scrollTop = conversationBox.scrollHeight;
  }
  function withBottomFollow(mutate) {
    const pinned = isPinnedToBottom(
      conversationBox.scrollTop,
      conversationBox.scrollHeight,
      conversationBox.height,
      SCROLL_PIN_SLACK,
    );
    mutate();
    if (pinned) scrollConversationToBottom();
  }

  const dispatch = createDispatcher({
    turnBegin: (m) => { ensureTurn(m.id); },
    turnEnd: () => { if (activeTurn) { activeTurn.finish?.(); activeTurn.ended = true; } },
    turnStatus: (m) => {
      statusActive = Boolean(m.active ?? statusActive);
      composer.setTurnStatus(m);
    },
    composerSet: (m) => composer.setComposerState(m),
    completionContext: (m) => composer.setCompletionContext(m),
    completionResponse: (m) => composer.applyCompletionResponse(m),
    routerUpdate: (m) => composer.setRouterState(m),
    blockBegin: (m) => withBottomFollow(() => ensureTurn().begin(m.id, m.kind, m.meta)),
    blockAppend: (m) => withBottomFollow(() => activeTurn?.append(m.id, m.delta)),
    blockUpdate: (m) => withBottomFollow(() => activeTurn?.update(m.id, m.patch)),
    blockEnd: (m) => activeTurn?.end(m.id),
    // prompt.echo arrives BEFORE turn.begin (it is emitted by the input-echo
    // hook). ensureTurn here starts the turn view; the following turn.begin
    // reuses it because activeTurn is set and not ended. Render the user's
    // submitted text as a prompt block.
    promptEcho: (m) => {
      const turn = ensureTurn(m.id);
      turn.begin(`prompt-${scrollbackSeq++}`, "prompt", { text: String(m.text ?? "") });
      // The user just submitted — always snap to the bottom so they see their
      // message and the incoming response, even if they had scrolled up.
      scrollConversationToBottom();
    },
    // model.text is a minor queue marker. Render it as a thinking line (purple
    // ✻) by seeding a thinking block and flushing it immediately on end.
    modelText: (m) => {
      withBottomFollow(() => {
        const turn = ensureTurn();
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
    // scrollback is a lifecycle-less raw line dump (no begin/end); rendered inline
    // here rather than as a block — the only orchestration-layer rendering exception.
    scrollback: (m) => {
      const node = new TextRenderable(renderer, {
        id: `sb-${scrollbackSeq++}`,
        content: stripTerminalControls(String(m.text ?? "")),
        fg: THEME.muted,
      });
      withBottomFollow(() => conversationBox.add(node));
      renderer.requestRender?.();
    },
    // Command notices captured from the Python side's stdout (slash-command and
    // runtime messages). They arrive one Rich-rendered line at a time; render
    // them INSIDE the conversation in the active theme's semantic color (never on
    // the terminal, so they can no longer bleed over or clip against the host).
    notice: (m) => {
      const { text, level } = parseNotice(String(m.text ?? ""));
      if (!text.trim()) return; // drop blank spacer lines
      const spec = NOTICE_LEVELS[level] ?? NOTICE_LEVELS.detail;
      const fg = THEME[spec.token] ?? THEME.detailText;
      // Plain status lines get a severity glyph; table/panel borders render as-is
      // so their box-drawing stays aligned.
      const content = isStructuredLine(text)
        ? `${TOOL_INDENT}${text}`
        : `${TOOL_INDENT}${spec.glyph} ${text}`;
      const node = new TextRenderable(renderer, { id: `notice-${scrollbackSeq++}`, content, fg });
      withBottomFollow(() => conversationBox.add(node));
      renderer.requestRender?.();
    },
    shutdown: () => { renderer.destroy(); process.exit(0); },
    unknown: (m) => ipc.send({ type: "error", message: `Unknown Python message type: ${m.type}` }),
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
    for (const t of turns) t.relayout?.();
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
      activeTurn?.refreshPulse(pulseFrame);
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

main().catch((error) => {
  process.stderr.write(`${error?.message ?? error}\n`);
  process.exit(1);
});
