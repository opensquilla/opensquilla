#!/usr/bin/env node

import fs from "node:fs";
import process from "node:process";
import readline from "node:readline";

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
const OPENTUI_DAILY_THEME = Object.freeze({
  preset: "daily",
  frameStyle: "card",
  detailMode: "inline",
  answerMode: "panel",
  motion: "pulse",
  text: "#F4F7FB",
  muted: "#667385",
  faint: "#3E4A57",
  frame: "#5a6b7a",
  composerBorder: "#77B7FF",
  composerDisabledBorder: "#354453",
  routerNormal: "#73D0A7",
  routerWarning: "#F6C177",
  routerError: "#FF7B8A",
  toolAccent: "#69D2E7",
  detailText: "#8A96A6",
  answerAccent: "#9AD18B",
  promptAccent: "#FFB86C",
  routeText: "#C4B5FD",
  savingText: "#8BD5CA",
});
const STATUS_PULSE_FRAMES = Object.freeze({
  thinking: ["∙", "•", "●", "•"],
  tool: ["◌", "◔", "◑", "◕"],
  output: ["◇", "◆", "◇", "◆"],
});

let renderer;
let BoxRenderable;
let TextRenderable;
let ScrollBoxRenderable;
let MarkdownRenderable;
let SyntaxStyle;
let syntaxStyle;
let createCliRenderer;
let conversationBox;
let inputBox;
let inputText = "";
let pulseFrame = 0;
let pulseTimer;
let scrollbackSeq = 0;
let activeTurn = null;
const toolPulseNodes = new Set();
// Input history (newest last). historyIndex === history.length means "current
// draft" (not browsing history); 0..length-1 selects a recalled entry.
const inputHistory = [];
let historyIndex = 0;
let draftBeforeHistory = "";
// Cursor blink state for the composer.
let cursorVisible = true;
let cursorTimer;

const composer = {
  placeholder: "send a message",
  text: "",
  disabled: false,
};

const routerState = {
  model: "pending",
  route: "pending",
  saving: "pending",
  context: "pending",
  style: "dim",
};

const turnStatus = {
  phase: "idle",
  label: "ready",
  active: false,
};

function sendHostMessage(message) {
  fs.writeSync(TO_PYTHON_FD, `${JSON.stringify(message)}\n`, "utf8");
}

function writeError(error) {
  const message = error instanceof Error ? error.message : String(error);
  try {
    sendHostMessage({ type: "error", message });
  } catch {
    process.stderr.write(`${message}\n`);
  }
}

function colorForStyle(style) {
  if (style === "warning") return OPENTUI_DAILY_THEME.routerWarning;
  if (style === "error") return OPENTUI_DAILY_THEME.routerError;
  if (style === "dim") return OPENTUI_DAILY_THEME.muted;
  return OPENTUI_DAILY_THEME.routerNormal;
}

function statusIcon() {
  if (!turnStatus.active) return "✓";
  const frames = STATUS_PULSE_FRAMES[turnStatus.phase] ?? STATUS_PULSE_FRAMES.thinking;
  return frames[pulseFrame % frames.length];
}

function startCursorBlink() {
  if (cursorTimer) return;
  cursorTimer = setInterval(() => {
    cursorVisible = !cursorVisible;
    rerenderInputRegion();
  }, 530);
  cursorTimer.unref?.();
}

// Reset the cursor to solid-on after a keystroke so typing feels responsive
// instead of landing on a blink-off frame.
function wakeCursor() {
  cursorVisible = true;
}

function syncPulseTimer() {
  if (turnStatus.active && !pulseTimer) {
    pulseTimer = setInterval(() => {
      pulseFrame += 1;
      activeTurn?.refreshToolPulse();
      rerenderInputRegion();
      renderer.requestRender?.();
    }, 180);
    pulseTimer.unref?.();
    return;
  }
  if (!turnStatus.active && pulseTimer) {
    clearInterval(pulseTimer);
    pulseTimer = undefined;
    pulseFrame = 0;
  }
}

function fixedRouterRow(label, value) {
  const safeValue = String(value).replace(/\s+/gu, " ").trim() || "-";
  const maxValueCells = 18;
  let clipped = "";
  let cells = 0;
  for (const char of Array.from(safeValue)) {
    const next = cells + cellWidth(char);
    if (next > maxValueCells) break;
    clipped += char;
    cells = next;
  }
  const padding = " ".repeat(Math.max(0, maxValueCells - cells));
  return `${label.padEnd(5)} ${clipped}${padding}`;
}

function buildLayout() {
  const height = renderer.terminalHeight ?? 24;
  conversationBox = new ScrollBoxRenderable(renderer, {
    id: "conversation",
    position: "absolute",
    left: 0,
    top: 0,
    right: 0,
    height: Math.max(1, height - FOOTER_HEIGHT),
    stickyScroll: true,
    stickyStart: "bottom",
    scrollY: true,
    scrollX: false,
    viewportCulling: true,
  });
  renderer.root.add(conversationBox);

  inputBox = new BoxRenderable(renderer, {
    id: "input-region",
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: FOOTER_HEIGHT,
  });
  renderer.root.add(inputBox);

  rerenderInputRegion();
}

function rerenderInputRegion() {
  if (!inputBox) return;
  for (const child of inputBox.getChildren?.() ?? []) inputBox.remove?.(child.id);
  const cursor = !composer.disabled && cursorVisible ? "▏" : " ";
  const composerLine = inputText || composer.text;
  const text = composerLine ? `${composerLine}${cursor}` : `${cursor}${composer.placeholder}`;
  const composerNode = new BoxRenderable(renderer, {
    id: "composer-box",
    position: "absolute",
    left: 1,
    right: 34,
    bottom: 1,
    height: 4,
    borderStyle: "rounded",
    borderColor: composer.disabled ? OPENTUI_DAILY_THEME.composerDisabledBorder : OPENTUI_DAILY_THEME.composerBorder,
    bottomTitle: `${statusIcon()} ${turnStatus.label}`,
    bottomTitleAlignment: "left",
    paddingLeft: 1,
    paddingRight: 1,
    flexDirection: "column",
    justifyContent: "center",
  });
  composerNode.add(new TextRenderable(renderer, {
    id: "composer-text",
    content: text,
    fg: composerLine ? OPENTUI_DAILY_THEME.text : OPENTUI_DAILY_THEME.muted,
  }));
  inputBox.add(composerNode);

  const routerNode = new BoxRenderable(renderer, {
    id: "router-plugin",
    position: "absolute",
    right: 1,
    bottom: 0,
    width: 31,
    height: FOOTER_HEIGHT,
    borderStyle: "rounded",
    borderColor: colorForStyle(routerState.style),
    title: " router ",
    titleAlignment: "left",
    paddingLeft: 1,
    paddingRight: 1,
    flexDirection: "column",
  });
  routerNode.add(new TextRenderable(renderer, { id: "router-model", content: fixedRouterRow("model", routerState.model), fg: OPENTUI_DAILY_THEME.text }));
  routerNode.add(new TextRenderable(renderer, { id: "router-route", content: fixedRouterRow("route", routerState.route), fg: OPENTUI_DAILY_THEME.routeText }));
  routerNode.add(new TextRenderable(renderer, { id: "router-saving", content: fixedRouterRow("save", routerState.saving), fg: OPENTUI_DAILY_THEME.savingText }));
  routerNode.add(new TextRenderable(renderer, { id: "router-context", content: fixedRouterRow("ctx", routerState.context), fg: OPENTUI_DAILY_THEME.routerWarning }));
  inputBox.add(routerNode);
  renderer.requestRender?.();
}

function stripTerminalControls(text) {
  return text
    .replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|P[^\x1b]*\x1b\\|[@-Z\\-_])/g, "")
    .replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
}

function textWidth(text) {
  let width = 0;
  for (const char of Array.from(text)) width += cellWidth(char);
  return width;
}

function cellWidth(char) {
  return /[\u1100-\u115f\u2329\u232a\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe19\ufe30-\ufe6f\uff00-\uff60\uffe0-\uffe6]/u.test(char)
    ? 2
    : 1;
}

class TurnView {
  constructor(id) {
    this.id = id;
    this.toolNodes = new Map();
    this.runningNodes = new Set();   // this turn's nodes still in toolPulseNodes
    this.sawAnswer = false;
    this._answerText = "";
    this.answerMd = null;
    this.answerTextNode = null;
    this.answerTop = null;
    this.ended = false;
    this._seq = 0;
    this.box = new BoxRenderable(renderer, {
      id: `turn-${id}`,
      flexDirection: "column",
      paddingLeft: 1,
      paddingRight: 1,
    });
    conversationBox.add(this.box);
  }

  _line(suffix, content, fg) {
    const node = new TextRenderable(renderer, { id: `turn-${this.id}-${suffix}`, content, fg });
    this.box.add(node);
    return node;
  }

  setPrompt(text) {
    this._line("p-top", "╭─ prompt ─────", OPENTUI_DAILY_THEME.promptAccent);
    stripTerminalControls(String(text)).split("\n").forEach((line, index) => {
      this._line(`p-${index}`, `│ ${line}`, OPENTUI_DAILY_THEME.promptAccent);
    });
    this._line("p-bot", "╰─────", OPENTUI_DAILY_THEME.promptAccent);
    this._line("rail-top", "│", OPENTUI_DAILY_THEME.faint);
    renderer.requestRender?.();
  }

  addTool(toolId, name, summary) {
    this.demoteAnswerToTimeline();
    const cleanName = stripTerminalControls(String(name));
    const cleanSummary = stripTerminalControls(String(summary));
    const tail = cleanSummary ? ` ${cleanSummary}` : "";
    const node = this._line(`tool-${toolId}`, `${STATUS_PULSE_FRAMES.tool[0]} ${cleanName}${tail}`, OPENTUI_DAILY_THEME.toolAccent);
    node._toolName = cleanName;
    node._toolTail = tail;
    this.toolNodes.set(toolId, node);
    toolPulseNodes.add(node);
    this.runningNodes.add(node);
    renderer.requestRender?.();
  }

  finishTool(toolId, status, name, summary) {
    const node = this.toolNodes.get(toolId);
    const glyph = status === "error" ? "✗" : "✓";
    const fg = status === "error" ? OPENTUI_DAILY_THEME.routerError : OPENTUI_DAILY_THEME.answerAccent;
    const cleanName = stripTerminalControls(String(name));
    const cleanSummary = stripTerminalControls(String(summary));
    const finalName = cleanName || node?._toolName || "";
    const tail = cleanSummary ? ` ${cleanSummary}` : (node?._toolTail ?? "");
    if (node) {
      node.content = `${glyph} ${finalName}${tail}`;
      node.fg = fg;
      toolPulseNodes.delete(node);
      this.runningNodes.delete(node);
    } else {
      this._line(`tool-${toolId}`, `${glyph} ${finalName}${tail}`, fg);
    }
    renderer.requestRender?.();
  }

  addToolDetail(text) {
    const lines = stripTerminalControls(String(text)).split("\n");
    const max = 3;
    lines.slice(0, max).forEach((line, index) => {
      this._line(`detail-${this._seq}-${index}`, `│   ${line}`, OPENTUI_DAILY_THEME.detailText);
    });
    if (lines.length > max) this._line(`detail-more-${this._seq}`, `│   … ${lines.length - max} more lines`, OPENTUI_DAILY_THEME.detailText);
    this._seq += 1;
    renderer.requestRender?.();
  }

  appendModelText(text) {
    this._line(`model-${this._seq++}`, stripTerminalControls(String(text)), OPENTUI_DAILY_THEME.answerAccent);
    renderer.requestRender?.();
  }

  appendAnswer(delta) {
    if (!this.sawAnswer) {
      this.sawAnswer = true;
      this._answerText = "";
      this.answerTop = this._line("a-top", "╭─ answer ─ squilla ─────", OPENTUI_DAILY_THEME.frame);
      this.answerMd = new MarkdownRenderable(renderer, {
        id: `turn-${this.id}-md`,
        content: "",
        streaming: true,
        conceal: true,
        syntaxStyle,
        fg: OPENTUI_DAILY_THEME.text,
        tableOptions: { style: "columns" },
        internalBlockMode: "top-level",
        height: 0,
        paddingLeft: 1,
      });
      this.box.add(this.answerMd);
      this.answerTextNode = this._line(`answer-fallback-${this._seq++}`, "", OPENTUI_DAILY_THEME.text);
    }
    this._answerText += String(delta);
    if (this.answerMd) this.answerMd.content = this._answerText;
    if (this.answerTextNode) this.answerTextNode.content = stripTerminalControls(this._answerText);
    renderer.requestRender?.();
  }

  demoteAnswerToTimeline() {
    if (!this.sawAnswer) return;
    if (this.answerTop && typeof this.box.remove === "function") this.box.remove(this.answerTop.id);
    if (this.answerMd && typeof this.box.remove === "function") this.box.remove(this.answerMd.id);
    if (this.answerTextNode && typeof this.box.remove === "function") this.box.remove(this.answerTextNode.id);
    const text = stripTerminalControls(this._answerText);
    if (text) this._line(`answer-${this._seq++}`, text, OPENTUI_DAILY_THEME.answerAccent);
    this.sawAnswer = false;
    this._answerText = "";
    this.answerTop = null;
    this.answerMd = null;
    this.answerTextNode = null;
  }

  promoteAnswerToCard() {
    if (!this.sawAnswer || !this.answerMd) return false;
    return true;
  }

  finishAnswer(cancelled) {
    // Purge any tools that never reported a finish (e.g. cancellation mid-tool)
    // from the global pulse set so refreshToolPulse stops mutating dead nodes.
    for (const node of this.runningNodes) toolPulseNodes.delete(node);
    this.runningNodes.clear();
    this.ended = true;
    const renderedAnswer = this.promoteAnswerToCard();
    if (cancelled) this._line("a-cancel", "│ turn cancelled", OPENTUI_DAILY_THEME.muted);
    if (renderedAnswer) this._line("a-bot", "╰─────", OPENTUI_DAILY_THEME.frame);
    renderer.requestRender?.();
  }

  setUsage(text) {
    this._line("usage", `  · ${stripTerminalControls(String(text))}`, OPENTUI_DAILY_THEME.muted);
    renderer.requestRender?.();
  }

  refreshToolPulse() {
    const frames = STATUS_PULSE_FRAMES.tool;
    const glyph = frames[pulseFrame % frames.length];
    for (const node of toolPulseNodes) {
      node.content = `${glyph} ${node._toolName}${node._toolTail}`;
    }
  }
}

function handlePythonMessage(message) {
  switch (message.type) {
    case "router.update":
      Object.assign(routerState, {
        model: String(message.model ?? routerState.model),
        route: String(message.route ?? routerState.route),
        saving: String(message.saving ?? routerState.saving),
        context: String(message.context ?? routerState.context),
        style: String(message.style ?? routerState.style),
      });
      rerenderInputRegion();
      return;
    case "composer.set":
      Object.assign(composer, {
        placeholder: String(message.placeholder ?? composer.placeholder),
        text: String(message.text ?? composer.text),
        disabled: Boolean(message.disabled ?? composer.disabled),
      });
      inputText = composer.text;
      rerenderInputRegion();
      return;
    case "turn.status":
      Object.assign(turnStatus, {
        phase: String(message.phase ?? turnStatus.phase),
        label: String(message.label ?? turnStatus.label),
        active: Boolean(message.active ?? turnStatus.active),
      });
      syncPulseTimer();
      rerenderInputRegion();
      return;
    case "turn.begin":
      // prompt.echo arrives BEFORE turn.begin (it is emitted by the input-echo
      // hook, before the renderer's _ensure_begin). If prompt.echo already
      // started this turn's view, reuse it; otherwise start a fresh one.
      if (!activeTurn || activeTurn.ended) {
        activeTurn = new TurnView(String(message.id ?? scrollbackSeq++));
      }
      return;
    case "prompt.echo":
      if (!activeTurn || activeTurn.ended) {
        activeTurn = new TurnView(String(message.id ?? scrollbackSeq++));
      }
      activeTurn.setPrompt(String(message.text ?? ""));
      return;
    case "model.text":
      activeTurn?.appendModelText(String(message.text ?? ""));
      return;
    case "tool.call":
      {
        const toolId = String(message.id ?? "");
        const status = String(message.status ?? "running");
        if (status === "running") activeTurn?.addTool(toolId, String(message.name ?? ""), String(message.summary ?? ""));
        else activeTurn?.finishTool(toolId, status, String(message.name ?? ""), String(message.summary ?? ""));
      }
      return;
    case "tool.detail":
      activeTurn?.addToolDetail(String(message.text ?? ""));
      return;
    case "answer.text":
      activeTurn?.appendAnswer(String(message.text ?? ""));
      return;
    case "turn.end":
      activeTurn?.finishAnswer(Boolean(message.cancelled ?? false));
      return;
    case "usage":
      activeTurn?.setUsage(String(message.text ?? ""));
      return;
    case "scrollback.write":
      {
        const node = new TextRenderable(renderer, {
          id: `sb-${scrollbackSeq++}`,
          content: stripTerminalControls(String(message.text ?? "")),
          fg: OPENTUI_DAILY_THEME.muted,
        });
        conversationBox.add(node);
        renderer.requestRender?.();
      }
      return;
    case "shutdown":
      if (pulseTimer) clearInterval(pulseTimer);
      if (cursorTimer) clearInterval(cursorTimer);
      renderer.destroy();
      process.exit(0);
      return;
    default:
      writeError(new Error(`Unknown Python message type: ${message.type}`));
  }
}

function submitInput() {
  const text = inputText;
  if (text.trim() && inputHistory[inputHistory.length - 1] !== text) {
    inputHistory.push(text);
  }
  historyIndex = inputHistory.length;
  draftBeforeHistory = "";
  inputText = "";
  composer.text = "";
  sendHostMessage({ type: "input.submit", text });
  rerenderInputRegion();
}

// Up/Down arrows walk the input history. The slot past the end (index ===
// length) holds the in-progress draft so Down returns to what was typed.
function recallHistory(direction) {
  if (inputHistory.length === 0) return;
  if (historyIndex === inputHistory.length) {
    draftBeforeHistory = inputText;
  }
  const next = historyIndex + direction;
  if (next < 0 || next > inputHistory.length) return;
  historyIndex = next;
  inputText = next === inputHistory.length ? draftBeforeHistory : inputHistory[next];
  composer.text = inputText;
  wakeCursor();
  rerenderInputRegion();
}

function installKeyboardHandlers() {
  renderer.keyInput.on("keypress", (key) => {
    if (key.ctrl && key.name === "c") {
      sendHostMessage({ type: "input.cancel" });
      return;
    }
    if (key.ctrl && key.name === "d") {
      sendHostMessage({ type: "input.eof" });
      return;
    }
    if (key.name === "return") {
      submitInput();
      return;
    }
    if (key.name === "up") {
      recallHistory(-1);
      return;
    }
    if (key.name === "down") {
      recallHistory(1);
      return;
    }
    if (key.name === "pageup") {
      conversationBox?.scrollBy({ x: 0, y: -10 });
      renderer.requestRender?.();
      return;
    }
    if (key.name === "pagedown") {
      conversationBox?.scrollBy({ x: 0, y: 10 });
      renderer.requestRender?.();
      return;
    }
    if (key.name === "backspace") {
      inputText = Array.from(inputText).slice(0, -1).join("");
      wakeCursor();
      rerenderInputRegion();
      return;
    }
    const printable = key.sequence ?? key.name ?? "";
    if (printable.length > 0 && !key.ctrl && !key.meta && key.name !== "space") {
      inputText += printable;
      historyIndex = inputHistory.length;
      wakeCursor();
      rerenderInputRegion();
    } else if (key.name === "space") {
      inputText += " ";
      historyIndex = inputHistory.length;
      wakeCursor();
      rerenderInputRegion();
    }
  });

  const decoder = new TextDecoder();
  renderer.keyInput.on("paste", (event) => {
    inputText += decoder.decode(event.bytes);
    historyIndex = inputHistory.length;
    wakeCursor();
    rerenderInputRegion();
  });
}

async function main() {
  ({ BoxRenderable, TextRenderable, ScrollBoxRenderable, MarkdownRenderable, SyntaxStyle, createCliRenderer } = await import("@opentui/core"));

  renderer = await createCliRenderer({
    screenMode: "alternate-screen",
    exitOnCtrlC: false,
  });

  syntaxStyle = SyntaxStyle.create();

  buildLayout();
  installKeyboardHandlers();
  startCursorBlink();

  renderer.on?.("resize", () => {
    const h = renderer.terminalHeight ?? 24;
    if (conversationBox) conversationBox.height = Math.max(1, h - FOOTER_HEIGHT);
    rerenderInputRegion();
    const width = renderer.terminalWidth ?? 0;
    if (width && h) sendHostMessage({ type: "resize", width, height: h });
  });

  sendHostMessage({ type: "ready" });

  const input = fs.createReadStream(null, {
    fd: FROM_PYTHON_FD,
    encoding: "utf8",
    autoClose: false,
  });
  const lines = readline.createInterface({ input, crlfDelay: Infinity });
  lines.on("line", (line) => {
    if (!line.trim()) return;
    try {
      handlePythonMessage(JSON.parse(line));
    } catch (error) {
      writeError(error);
    }
  });
  lines.on("close", () => {
    renderer.destroy();
    process.exit(0);
  });
}

main().catch((error) => {
  writeError(error);
  process.exit(1);
});
