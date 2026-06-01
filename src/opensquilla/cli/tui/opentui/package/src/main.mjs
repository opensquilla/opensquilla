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
  modelText: "#C4B5FD",
  promptAccent: "#FFB86C",
  routeText: "#C4B5FD",
  savingText: "#8BD5CA",
});
// Card rules: the top edge runs long, the bottom edge stays short, keeping the
// "top longer than bottom" look while extending further to the right than before.
const CARD_RULE_LONG = "─".repeat(48);
const CARD_RULE_SHORT = "─".repeat(8);
const TOOL_INDENT = " ";
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
// Caret position as a grapheme index into Array.from(inputText), range [0, len].
let cursorPos = 0;
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

// Render the caret as a thin bar when visible, a blank (same width) when the
// blink is off so the line layout never jumps. Cursor blinks regardless of the
// composer being disabled, so a running turn still shows a live caret.
function caretGlyph() {
  return cursorVisible ? "▏" : " ";
}

// Split the input into display lines and splice the caret into the line/column
// that cursorPos lands on. Returns an array of line strings to render.
function composerLines() {
  const chars = Array.from(inputText);
  const pos = Math.max(0, Math.min(cursorPos, chars.length));
  const caret = caretGlyph();
  if (chars.length === 0) {
    // Empty: caret sits before the muted placeholder.
    return [{ text: `${caret}${composer.placeholder}`, muted: true }];
  }
  const before = chars.slice(0, pos).join("");
  const after = chars.slice(pos).join("");
  const withCaret = `${before}${caret}${after}`;
  return withCaret.split("\n").map((line) => ({ text: line, muted: false }));
}

function rerenderInputRegion() {
  if (!inputBox) return;
  for (const child of inputBox.getChildren?.() ?? []) inputBox.remove?.(child.id);
  const lines = composerLines();
  const composerNode = new BoxRenderable(renderer, {
    id: "composer-box",
    position: "absolute",
    left: 1,
    right: 34,
    bottom: 0,
    height: FOOTER_HEIGHT,
    borderStyle: "rounded",
    borderColor: composer.disabled ? OPENTUI_DAILY_THEME.composerDisabledBorder : OPENTUI_DAILY_THEME.composerBorder,
    bottomTitle: `${statusIcon()} ${turnStatus.label}`,
    bottomTitleAlignment: "left",
    paddingLeft: 1,
    paddingRight: 1,
    flexDirection: "column",
    justifyContent: "flex-start",
  });
  lines.forEach((line, index) => {
    composerNode.add(new TextRenderable(renderer, {
      id: `composer-text-${index}`,
      content: line.text,
      fg: line.muted ? OPENTUI_DAILY_THEME.muted : OPENTUI_DAILY_THEME.text,
    }));
  });
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
    this.detailCountByTool = new Map();  // toolId -> detail rows already inserted under it
    this.runningNodes = new Set();   // this turn's nodes still in toolPulseNodes
    this.sawAnswer = false;
    this._answerText = "";
    this.answerDraft = null;
    this.answerBody = null;
    this.answerMd = null;
    this.answerTop = null;
    this.answerGap = null;
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
    this._line("p-top", `╭─ prompt ${CARD_RULE_LONG}`, OPENTUI_DAILY_THEME.promptAccent);
    stripTerminalControls(String(text)).split("\n").forEach((line, index) => {
      this._line(`p-${index}`, `│ ${line}`, OPENTUI_DAILY_THEME.promptAccent);
    });
    this._line("p-bot", `╰${CARD_RULE_SHORT}`, OPENTUI_DAILY_THEME.promptAccent);
    renderer.requestRender?.();
  }

  addTool(toolId, name, summary) {
    this.demoteAnswerToTimeline();
    const cleanName = stripTerminalControls(String(name));
    const cleanSummary = stripTerminalControls(String(summary));
    const tail = cleanSummary ? ` ${cleanSummary}` : "";
    this._line(`rail-tool-${toolId}`, `${TOOL_INDENT}│`, OPENTUI_DAILY_THEME.faint);
    const node = this._line(`tool-${toolId}`, `${TOOL_INDENT}${STATUS_PULSE_FRAMES.tool[0]} ${cleanName}${tail}`, OPENTUI_DAILY_THEME.toolAccent);
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
      node.content = `${TOOL_INDENT}${glyph} ${finalName}${tail}`;
      node.fg = fg;
      toolPulseNodes.delete(node);
      this.runningNodes.delete(node);
    } else {
      this._line(`rail-tool-${toolId}`, `${TOOL_INDENT}│`, OPENTUI_DAILY_THEME.faint);
      this._line(`tool-${toolId}`, `${TOOL_INDENT}${glyph} ${finalName}${tail}`, fg);
    }
    renderer.requestRender?.();
  }

  addToolDetail(text, toolId = null) {
    const lines = stripTerminalControls(String(text)).split("\n");
    const max = 3;
    const rows = lines.slice(0, max).map((line) => `${TOOL_INDENT}│   ${line}`);
    if (lines.length > max) rows.push(`${TOOL_INDENT}│   … ${lines.length - max} more lines`);

    const toolNode = toolId != null ? this.toolNodes.get(toolId) : null;
    rows.forEach((content, index) => {
      const node = new TextRenderable(renderer, {
        id: `turn-${this.id}-detail-${this._seq}-${index}`,
        content,
        fg: OPENTUI_DAILY_THEME.detailText,
      });
      if (toolNode) {
        // Insert directly under the owning tool node so each tool + its detail
        // stay grouped. Re-read the index every time: inserting detail under an
        // earlier tool shifts later tools' positions, so a cached index is stale.
        const base = this.box.getChildren().indexOf(toolNode);
        const offset = (this.detailCountByTool.get(toolId) ?? 0) + 1;
        if (base >= 0) this.box.add(node, base + offset);
        else this.box.add(node);
        this.detailCountByTool.set(toolId, offset);
      } else {
        // turn-level detail (e.g. aerror) with no owning tool: append at the end.
        this.box.add(node);
      }
    });
    this._seq += 1;
    renderer.requestRender?.();
  }

  appendModelText(text) {
    // Intermediate model output (between tool calls). Render in a distinct
    // colour from tool/answer lines, and drop blank leading/trailing lines so it
    // does not introduce stray gaps in the timeline.
    const clean = stripTerminalControls(String(text)).replace(/^\n+|\n+$/g, "");
    if (!clean) return;
    this._line(`model-${this._seq++}`, clean, OPENTUI_DAILY_THEME.modelText);
    renderer.requestRender?.();
  }

  appendAnswer(delta) {
    if (!this.sawAnswer) {
      this.sawAnswer = true;
      this._answerText = "";
      this.answerDraft = this._line(`answer-draft-${this._seq++}`, "", OPENTUI_DAILY_THEME.modelText);
    }
    this._answerText += String(delta);
    if (this.answerDraft) this.answerDraft.content = stripTerminalControls(this._answerText);
    renderer.requestRender?.();
  }

  demoteAnswerToTimeline() {
    if (!this.sawAnswer) return;
    const text = stripTerminalControls(this._answerText);
    // The streaming draft was a single bare node; replace it with a proper
    // timeline block: a rail gap above/below, a ✱ glyph on the first line, and
    // continuation lines indented to align under it — so intermediate model
    // output reads as a node on the timeline like the tool rows do.
    if (this.answerDraft && typeof this.box.remove === "function") {
      this.box.remove(this.answerDraft.id);
    }
    if (text) {
      const lines = text.split("\n");
      this._line(`mid-gap-top-${this._seq}`, `${TOOL_INDENT}│`, OPENTUI_DAILY_THEME.faint);
      lines.forEach((line, index) => {
        const content = index === 0 ? `${TOOL_INDENT}✱ ${line}` : `${TOOL_INDENT}  ${line}`;
        this._line(`mid-${this._seq}-${index}`, content, OPENTUI_DAILY_THEME.modelText);
      });
      this._line(`mid-gap-bot-${this._seq}`, `${TOOL_INDENT}│`, OPENTUI_DAILY_THEME.faint);
      this._seq += 1;
    }
    this.sawAnswer = false;
    this._answerText = "";
    this.answerDraft = null;
    this.answerBody = null;
    this.answerGap = null;
    this.answerTop = null;
    this.answerMd = null;
  }

  promoteAnswerToCard() {
    if (!this.sawAnswer) return false;
    const content = this._answerText;
    if (this.answerDraft && typeof this.box.remove === "function") this.box.remove(this.answerDraft.id);
    // The answer only becomes the blue Markdown card once turn.end proves it is final.
    this.answerGap = this._line("a-gap", "│", OPENTUI_DAILY_THEME.faint);
    this.answerTop = this._line("a-top", `╭─ answer ─ squilla ${CARD_RULE_LONG}`, OPENTUI_DAILY_THEME.toolAccent);
    this.answerBody = new BoxRenderable(renderer, {
      id: `turn-${this.id}-answer-body`,
      width: "100%",
      flexDirection: "column",
      border: ["left"],
      borderColor: OPENTUI_DAILY_THEME.toolAccent,
      paddingLeft: 1,
      flexShrink: 0,
    });
    this.answerMd = new MarkdownRenderable(renderer, {
      id: `turn-${this.id}-md`,
      content,
      streaming: false,
      conceal: true,
      syntaxStyle,
      fg: OPENTUI_DAILY_THEME.text,
      tableOptions: { style: "columns" },
      internalBlockMode: "top-level",
      width: "100%",
    });
    this.answerBody.add(this.answerMd);
    this.box.add(this.answerBody);
    this.sawAnswer = false;
    this._answerText = "";
    this.answerDraft = null;
    return true;
  }

  finishAnswer(cancelled) {
    // Purge any tools that never reported a finish (e.g. cancellation mid-tool)
    // from the global pulse set so refreshToolPulse stops mutating dead nodes.
    for (const node of this.runningNodes) toolPulseNodes.delete(node);
    this.runningNodes.clear();
    this.ended = true;
    if (cancelled) {
      this.demoteAnswerToTimeline();
      this._line("a-cancel", "│ turn cancelled", OPENTUI_DAILY_THEME.muted);
      renderer.requestRender?.();
      return;
    }
    const renderedAnswer = this.promoteAnswerToCard();
    if (renderedAnswer) this._line("a-bot", `╰${CARD_RULE_SHORT}`, OPENTUI_DAILY_THEME.toolAccent);
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
      node.content = `${TOOL_INDENT}${glyph} ${node._toolName}${node._toolTail}`;
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
      activeTurn?.addToolDetail(String(message.text ?? ""), message.tool_id ?? null);
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
  cursorPos = 0;
  composer.text = "";
  sendHostMessage({ type: "input.submit", text });
  rerenderInputRegion();
}

function setInput(text) {
  inputText = text;
  composer.text = text;
  cursorPos = Array.from(text).length;
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
  setInput(next === inputHistory.length ? draftBeforeHistory : inputHistory[next]);
  wakeCursor();
  rerenderInputRegion();
}

// Caret line/column from cursorPos. Lines split on "\n"; column is the grapheme
// offset within the line the caret sits on.
function caretLineCol() {
  const chars = Array.from(inputText);
  const pos = Math.max(0, Math.min(cursorPos, chars.length));
  let line = 0;
  let col = 0;
  for (let i = 0; i < pos; i += 1) {
    if (chars[i] === "\n") {
      line += 1;
      col = 0;
    } else {
      col += 1;
    }
  }
  return { line, col, chars, pos };
}

// Convert a (line, col) back to a grapheme index into the char array.
function lineColToPos(chars, targetLine, targetCol) {
  let line = 0;
  let col = 0;
  for (let i = 0; i < chars.length; i += 1) {
    if (line === targetLine && col === targetCol) return i;
    if (chars[i] === "\n") {
      if (line === targetLine) return i; // target col past end of this line
      line += 1;
      col = 0;
    } else {
      col += 1;
    }
  }
  return chars.length;
}

// Move caret up/down a line. Returns true if it moved within the text; false if
// already at the very first/last line (caller may then switch history).
function moveCaretVertical(direction) {
  const { line, col, chars } = caretLineCol();
  const lineCount = inputText.split("\n").length;
  const target = line + direction;
  if (target < 0 || target >= lineCount) return false;
  cursorPos = lineColToPos(chars, target, col);
  return true;
}

function moveCaretHorizontal(direction) {
  const len = Array.from(inputText).length;
  cursorPos = Math.max(0, Math.min(len, cursorPos + direction));
}

function insertAtCursor(insertText) {
  const chars = Array.from(inputText);
  const pos = Math.max(0, Math.min(cursorPos, chars.length));
  const insertChars = Array.from(insertText);
  inputText = [...chars.slice(0, pos), ...insertChars, ...chars.slice(pos)].join("");
  composer.text = inputText;
  cursorPos = pos + insertChars.length;
}

function deleteBeforeCursor() {
  const chars = Array.from(inputText);
  const pos = Math.max(0, Math.min(cursorPos, chars.length));
  if (pos === 0) return;
  inputText = [...chars.slice(0, pos - 1), ...chars.slice(pos)].join("");
  composer.text = inputText;
  cursorPos = pos - 1;
}

function installKeyboardHandlers() {
  renderer.keyInput.on("keypress", (key) => {
    if (key.ctrl && key.name === "c") {
      // With text: clear the input. Empty: signal EOF (exit the TUI).
      if (inputText.length > 0) {
        setInput("");
        historyIndex = inputHistory.length;
        wakeCursor();
        rerenderInputRegion();
      } else {
        sendHostMessage({ type: "input.eof" });
      }
      return;
    }
    if (key.ctrl && key.name === "d") {
      sendHostMessage({ type: "input.eof" });
      return;
    }
    if (key.name === "escape") {
      // Interrupt the in-flight turn (reuses the cancel path on the Python side).
      sendHostMessage({ type: "input.cancel" });
      return;
    }
    if (key.name === "return") {
      if (key.option || key.meta || key.alt) {
        insertAtCursor("\n");
        historyIndex = inputHistory.length;
        wakeCursor();
        rerenderInputRegion();
        return;
      }
      submitInput();
      return;
    }
    if (key.name === "left") {
      moveCaretHorizontal(-1);
      wakeCursor();
      rerenderInputRegion();
      return;
    }
    if (key.name === "right") {
      moveCaretHorizontal(1);
      wakeCursor();
      rerenderInputRegion();
      return;
    }
    if (key.name === "up") {
      // Move the caret up a line; only switch history when already on the very
      // first character (cursorPos === 0).
      if (cursorPos === 0 || !moveCaretVertical(-1)) recallHistory(-1);
      else {
        wakeCursor();
        rerenderInputRegion();
      }
      return;
    }
    if (key.name === "down") {
      // Move the caret down a line; only switch history when already at the very
      // end of the input.
      if (cursorPos === Array.from(inputText).length || !moveCaretVertical(1)) recallHistory(1);
      else {
        wakeCursor();
        rerenderInputRegion();
      }
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
      deleteBeforeCursor();
      wakeCursor();
      rerenderInputRegion();
      return;
    }
    const printable = key.sequence ?? key.name ?? "";
    if (printable.length > 0 && !key.ctrl && !key.meta && key.name !== "space") {
      insertAtCursor(printable);
      historyIndex = inputHistory.length;
      wakeCursor();
      rerenderInputRegion();
    } else if (key.name === "space") {
      insertAtCursor(" ");
      historyIndex = inputHistory.length;
      wakeCursor();
      rerenderInputRegion();
    }
  });

  const decoder = new TextDecoder();
  renderer.keyInput.on("paste", (event) => {
    insertAtCursor(decoder.decode(event.bytes));
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
    // OpenTUI routes wheel events to ScrollBox without touching input history.
    useMouse: true,
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
