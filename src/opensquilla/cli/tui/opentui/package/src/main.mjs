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
let root;
let Box;
let Text;
let TextRenderable;
let createCliRenderer;
let inputText = "";
let pulseFrame = 0;
let pulseTimer;
let scrollbackSeq = 0;
const currentTurn = { id: null, sawAnswer: false };

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

function syncPulseTimer() {
  if (turnStatus.active && !pulseTimer) {
    pulseTimer = setInterval(() => {
      pulseFrame += 1;
      rerenderFooter();
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

function renderFooterTree() {
  const composerLine = inputText || composer.text;
  const visibleComposer = composerLine || composer.placeholder;
  const composerColor = composerLine ? OPENTUI_DAILY_THEME.text : OPENTUI_DAILY_THEME.muted;

  return Box(
    {
      id: "opentui-footer-root",
      width: "100%",
      height: "100%",
      position: "relative",
      shouldFill: false,
    },
    Box(
      {
        id: "composer-box",
        position: "absolute",
        left: 1,
        right: 34,
        bottom: 1,
        height: 4,
        borderStyle: "rounded",
        borderColor: composer.disabled
          ? OPENTUI_DAILY_THEME.composerDisabledBorder
          : OPENTUI_DAILY_THEME.composerBorder,
        bottomTitle: `${statusIcon()} ${turnStatus.label}`,
        bottomTitleAlignment: "left",
        paddingLeft: 1,
        paddingRight: 1,
        flexDirection: "column",
        justifyContent: "center",
        shouldFill: false,
      },
      Text({
        id: "composer-text",
        content: visibleComposer,
        fg: composerColor,
      }),
    ),
    Box(
      {
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
        shouldFill: true,
      },
      Text({ id: "router-model", content: fixedRouterRow("model", routerState.model), fg: OPENTUI_DAILY_THEME.text }),
      Text({ id: "router-route", content: fixedRouterRow("route", routerState.route), fg: OPENTUI_DAILY_THEME.routeText }),
      Text({ id: "router-saving", content: fixedRouterRow("save", routerState.saving), fg: OPENTUI_DAILY_THEME.savingText }),
      Text({ id: "router-context", content: fixedRouterRow("ctx", routerState.context), fg: OPENTUI_DAILY_THEME.routerWarning }),
    ),
  );
}

function rerenderFooter() {
  if (!renderer) return;
  if (root) {
    renderer.root.remove("opentui-footer-root");
  }
  root = renderFooterTree();
  renderer.root.add(root);
  renderer.requestRender?.();
}

function writeScrollbackBlock(lines, fg, { startOnNewLine = true } = {}) {
  if (!renderer) return;
  renderer.writeToScrollback((ctx) => {
    const width = Math.max(1, ctx.width - 1);
    const plain = lines.map((line) => stripTerminalControls(line)).join("\n");
    const wrapped = padLinesForScrollback(wrapText(plain, Math.max(1, width - 1)));
    const height = Math.max(1, wrapped.split("\n").length);
    const node = new TextRenderable(ctx.renderContext, {
      id: `scrollback-${scrollbackSeq++}`,
      position: "absolute",
      left: 0,
      top: 0,
      width,
      height,
      content: wrapped,
      fg,
    });
    return { root: node, width, height, startOnNewLine, trailingNewline: true };
  });
}

function renderPromptBlock(text) {
  const lines = ["╭─ prompt"];
  for (const line of String(text).split("\n")) lines.push(`│ ${line}`);
  lines.push("╰");
  writeScrollbackBlock(lines, OPENTUI_DAILY_THEME.promptAccent);
}

function renderModelText(text) {
  writeScrollbackBlock([String(text)], OPENTUI_DAILY_THEME.answerAccent);
}

function renderToolCall(name, summary, status) {
  const glyph = status === "error" ? "✗" : status === "ok" ? "✓" : "•";
  const fg = status === "error" ? OPENTUI_DAILY_THEME.routerError : OPENTUI_DAILY_THEME.toolAccent;
  const tail = summary ? ` ${summary}` : "";
  writeScrollbackBlock([`  ${glyph} ${name}${tail}`], fg);
}

function renderToolDetail(text) {
  const lines = String(text).split("\n").map((line) => `    │ ${line}`);
  writeScrollbackBlock(lines, OPENTUI_DAILY_THEME.detailText);
}

function renderAnswerText(text) {
  const lines = [];
  if (!currentTurn.sawAnswer) {
    lines.push("╭─ answer ─ squilla");
    currentTurn.sawAnswer = true;
  }
  for (const line of String(text).split("\n")) lines.push(`│ ${line}`);
  writeScrollbackBlock(lines, OPENTUI_DAILY_THEME.text);
}

function renderAnswerClose(cancelled) {
  if (cancelled) {
    writeScrollbackBlock(["╰─ turn cancelled"], OPENTUI_DAILY_THEME.muted);
    return;
  }
  if (currentTurn.sawAnswer) {
    writeScrollbackBlock(["╰"], OPENTUI_DAILY_THEME.text);
  }
}

function renderUsage(text) {
  writeScrollbackBlock([`  · ${text}`], OPENTUI_DAILY_THEME.muted);
}

function stripTerminalControls(text) {
  return text
    .replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|P[^\x1b]*\x1b\\|[@-Z\\-_])/g, "")
    .replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
}

function padLinesForScrollback(text) {
  return text
    .split("\n")
    .map((line) => ` ${line}`)
    .join("\n");
}

function wrapText(text, width) {
  const rows = [];
  for (const line of text.split("\n")) {
    let current = "";
    let cells = 0;
    for (const token of line.split(/(\s+)/u)) {
      if (!token) continue;
      const tokenCells = textWidth(token);
      if (/^\s+$/u.test(token)) {
        if (current && cells + tokenCells <= width) {
          current += token;
          cells += tokenCells;
        }
        continue;
      }
      if (tokenCells > width) {
        const result = appendHardWrappedToken(
          rows,
          current,
          cells,
          token,
          width,
        );
        current = result.current;
        cells = result.cells;
        continue;
      }
      if (current && cells + tokenCells > width) {
        rows.push(current.trimEnd());
        current = token;
        cells = tokenCells;
        continue;
      }
      current += token;
      cells += tokenCells;
    }
    rows.push(current);
  }
  return rows.join("\n");
}

function appendHardWrappedToken(rows, current, cells, token, width, continuationPrefix = "") {
  const continuationCells = textWidth(continuationPrefix);
  for (const char of Array.from(token)) {
    const charCells = cellWidth(char);
    if (current && cells + charCells > width) {
      rows.push(current.trimEnd());
      current = `${continuationPrefix}${char}`;
      cells = continuationCells + charCells;
    } else {
      current += char;
      cells += charCells;
    }
  }
  return { current, cells };
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
      rerenderFooter();
      return;
    case "composer.set":
      Object.assign(composer, {
        placeholder: String(message.placeholder ?? composer.placeholder),
        text: String(message.text ?? composer.text),
        disabled: Boolean(message.disabled ?? composer.disabled),
      });
      inputText = composer.text;
      rerenderFooter();
      return;
    case "turn.status":
      Object.assign(turnStatus, {
        phase: String(message.phase ?? turnStatus.phase),
        label: String(message.label ?? turnStatus.label),
        active: Boolean(message.active ?? turnStatus.active),
      });
      syncPulseTimer();
      rerenderFooter();
      return;
    case "turn.begin":
      currentTurn.id = String(message.id ?? "");
      currentTurn.sawAnswer = false;
      return;
    case "prompt.echo":
      renderPromptBlock(String(message.text ?? ""));
      return;
    case "model.text":
      renderModelText(String(message.text ?? ""));
      return;
    case "tool.call":
      renderToolCall(
        String(message.name ?? ""),
        String(message.summary ?? ""),
        String(message.status ?? "running"),
      );
      return;
    case "tool.detail":
      renderToolDetail(String(message.text ?? ""));
      return;
    case "answer.text":
      renderAnswerText(String(message.text ?? ""));
      return;
    case "turn.end":
      renderAnswerClose(Boolean(message.cancelled ?? false));
      currentTurn.id = null;
      currentTurn.sawAnswer = false;
      return;
    case "usage":
      renderUsage(String(message.text ?? ""));
      return;
    case "scrollback.write":
      writeScrollbackBlock([String(message.text ?? "")], OPENTUI_DAILY_THEME.text, {
        startOnNewLine: false,
      });
      return;
    case "shutdown":
      if (pulseTimer) clearInterval(pulseTimer);
      renderer.destroy();
      process.exit(0);
      return;
    default:
      writeError(new Error(`Unknown Python message type: ${message.type}`));
  }
}

function submitInput() {
  const text = inputText;
  inputText = "";
  composer.text = "";
  sendHostMessage({ type: "input.submit", text });
  rerenderFooter();
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
    if (key.name === "backspace") {
      inputText = inputText.slice(0, -1);
      rerenderFooter();
      return;
    }
    const printable = key.sequence ?? key.name ?? "";
    if (printable.length > 0 && !key.ctrl && !key.meta && key.name !== "space") {
      inputText += printable;
      rerenderFooter();
    } else if (key.name === "space") {
      inputText += " ";
      rerenderFooter();
    }
  });

  const decoder = new TextDecoder();
  renderer.keyInput.on("paste", (event) => {
    inputText += decoder.decode(event.bytes);
    rerenderFooter();
  });
}

async function main() {
  ({ Box, Text, TextRenderable, createCliRenderer } = await import("@opentui/core"));

  renderer = await createCliRenderer({
    screenMode: "split-footer",
    footerHeight: FOOTER_HEIGHT,
    externalOutputMode: "capture-stdout",
    exitOnCtrlC: false,
  });

  rerenderFooter();
  installKeyboardHandlers();
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
