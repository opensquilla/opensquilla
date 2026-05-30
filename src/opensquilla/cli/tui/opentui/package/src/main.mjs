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
  frame: "card",
  detailMode: "inline",
  answerMode: "panel",
  motion: "pulse",
  text: "#F4F7FB",
  muted: "#667385",
  faint: "#3E4A57",
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
let createCliRenderer;
let conversationBox;
let inputBox;
let inputText = "";
let pulseFrame = 0;
let pulseTimer;
let scrollbackSeq = 0;
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
      rerenderInputRegion();
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
      return;
    case "prompt.echo":
      conversationBox.add(new TextRenderable(renderer, {
        id: `tmp-${scrollbackSeq++}`,
        content: `prompt: ${stripTerminalControls(String(message.text ?? ""))}`,
        fg: OPENTUI_DAILY_THEME.text,
      }));
      renderer.requestRender?.();
      return;
    case "model.text":
      conversationBox.add(new TextRenderable(renderer, {
        id: `tmp-${scrollbackSeq++}`,
        content: stripTerminalControls(String(message.text ?? "")),
        fg: OPENTUI_DAILY_THEME.text,
      }));
      renderer.requestRender?.();
      return;
    case "tool.call":
      conversationBox.add(new TextRenderable(renderer, {
        id: `tmp-${scrollbackSeq++}`,
        content: `tool: ${stripTerminalControls(String(message.name ?? ""))} ${stripTerminalControls(String(message.summary ?? ""))}`,
        fg: OPENTUI_DAILY_THEME.text,
      }));
      renderer.requestRender?.();
      return;
    case "tool.detail":
      conversationBox.add(new TextRenderable(renderer, {
        id: `tmp-${scrollbackSeq++}`,
        content: `detail: ${stripTerminalControls(String(message.text ?? ""))}`,
        fg: OPENTUI_DAILY_THEME.text,
      }));
      renderer.requestRender?.();
      return;
    case "answer.text":
      conversationBox.add(new TextRenderable(renderer, {
        id: `tmp-${scrollbackSeq++}`,
        content: stripTerminalControls(String(message.text ?? "")),
        fg: OPENTUI_DAILY_THEME.text,
      }));
      renderer.requestRender?.();
      return;
    case "turn.end":
      return;
    case "usage":
      conversationBox.add(new TextRenderable(renderer, {
        id: `tmp-${scrollbackSeq++}`,
        content: `usage: ${stripTerminalControls(String(message.text ?? ""))}`,
        fg: OPENTUI_DAILY_THEME.text,
      }));
      renderer.requestRender?.();
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
  ({ BoxRenderable, TextRenderable, ScrollBoxRenderable, createCliRenderer } = await import("@opentui/core"));

  renderer = await createCliRenderer({
    screenMode: "alternate-screen",
    exitOnCtrlC: false,
  });

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
