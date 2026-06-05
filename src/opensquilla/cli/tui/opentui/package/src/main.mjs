#!/usr/bin/env node
import process from "node:process";
import { THEME } from "./theme.mjs";
import { stripTerminalControls } from "./primitives.mjs";
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

async function main() {
  const { BoxRenderable, TextRenderable, ScrollBoxRenderable, MarkdownRenderable, SyntaxStyle, createCliRenderer } = await import("@opentui/core");

  const renderer = await createCliRenderer({
    screenMode: "alternate-screen",
    exitOnCtrlC: false,
    // OpenTUI routes wheel events to ScrollBox without touching input history.
    useMouse: true,
  });
  const syntaxStyle = SyntaxStyle.create();

  const conversationBox = new ScrollBoxRenderable(renderer, {
    id: "conversation",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height: Math.max(1, (renderer.terminalHeight ?? 24) - FOOTER_HEIGHT),
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
    height: FOOTER_HEIGHT,
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
  let scrollbackSeq = 0;
  let statusActive = false;
  let pulseFrame = 0;
  const turnDeps = { renderer, BoxRenderable, TextRenderable, MarkdownRenderable, syntaxStyle, conversationBox };
  const ensureTurn = (id) => {
    if (!activeTurn || activeTurn.ended) {
      activeTurn = createTurnView(turnDeps, id ?? scrollbackSeq++);
    }
    return activeTurn;
  };

  const dispatch = createDispatcher({
    turnBegin: (m) => { ensureTurn(m.id); },
    turnEnd: () => { if (activeTurn) activeTurn.ended = true; },
    turnStatus: (m) => {
      statusActive = Boolean(m.active ?? statusActive);
      composer.setTurnStatus(m);
    },
    composerSet: (m) => composer.setComposerState(m),
    completionContext: (m) => composer.setCompletionContext(m),
    completionResponse: (m) => composer.applyCompletionResponse(m),
    routerUpdate: (m) => composer.setRouterState(m),
    blockBegin: (m) => ensureTurn().begin(m.id, m.kind, m.meta),
    blockAppend: (m) => activeTurn?.append(m.id, m.delta),
    blockUpdate: (m) => activeTurn?.update(m.id, m.patch),
    blockEnd: (m) => activeTurn?.end(m.id),
    // prompt.echo arrives BEFORE turn.begin (it is emitted by the input-echo
    // hook). ensureTurn here starts the turn view; the following turn.begin
    // reuses it because activeTurn is set and not ended. Render the user's
    // submitted text as a prompt block.
    promptEcho: (m) => {
      const turn = ensureTurn(m.id);
      turn.begin(`prompt-${scrollbackSeq++}`, "prompt", { text: String(m.text ?? "") });
    },
    // model.text is a minor queue marker. Render it as a thinking line (purple
    // ✱) by seeding a thinking block and flushing it immediately on end.
    modelText: (m) => {
      const turn = ensureTurn();
      const id = `note-${scrollbackSeq++}`;
      turn.begin(id, "thinking", {});
      turn.append(id, String(m.text ?? ""));
      turn.end(id);
    },
    // scrollback is a lifecycle-less raw line dump (no begin/end); rendered inline
    // here rather than as a block — the only orchestration-layer rendering exception.
    scrollback: (m) => {
      const node = new TextRenderable(renderer, {
        id: `sb-${scrollbackSeq++}`,
        content: stripTerminalControls(String(m.text ?? "")),
        fg: THEME.muted,
      });
      conversationBox.add(node);
      renderer.requestRender?.();
    },
    shutdown: () => { renderer.destroy(); process.exit(0); },
    unknown: (m) => ipc.send({ type: "error", message: `Unknown Python message type: ${m.type}` }),
  });

  renderer.on?.("resize", () => {
    const h = renderer.terminalHeight ?? 24;
    conversationBox.height = Math.max(1, h - FOOTER_HEIGHT);
    composer.onResize();
    const w = renderer.terminalWidth ?? 0;
    if (w && h) ipc.send({ type: "resize", width: w, height: h });
  });

  // Single always-on pulse interval. The body is gated on statusActive so an
  // idle TUI does not rerender (and flicker) every 180ms; while a turn runs,
  // both the running-tool glyphs and the composer status pill animate.
  setInterval(() => {
    if (!statusActive) return;
    pulseFrame += 1;
    activeTurn?.refreshPulse(pulseFrame);
    composer.tickPulse(pulseFrame);
    renderer.requestRender?.();
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
