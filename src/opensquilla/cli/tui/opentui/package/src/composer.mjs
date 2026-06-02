import { THEME, STATUS_PULSE_FRAMES } from "./theme.mjs";
import { cellWidth } from "./primitives.mjs";

// Last path segment of a model id ("vendor/big-model" -> "big-model").
export function shortModel(m) {
  return m ? m.split("/").pop() : m;
}

// Router model row value. On downgrade, keep the resolved target model visible;
// the source/baseline model is already represented by the down marker.
export function formatRouterModelValue(model, baselineModel) {
  const modelShort = shortModel(model);
  const baselineShort = shortModel(baselineModel);
  if (baselineShort && modelShort && baselineShort !== modelShort) {
    return `↓ ${modelShort}`;
  }
  return modelShort || model;
}

export function fixedRouterRow(label, value) {
  const safeValue = String(value).replace(/\s+/gu, " ").trim() || "-";
  const maxValueCells = 20;
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

// Factory for the composer / input-region. All state that main.mjs previously
// held as module-level globals lives here as closure state; the rendering deps
// (renderer, renderable classes, boxes, footer height, host writer) are injected
// via `deps`.
export function createComposer(deps) {
  const { renderer, BoxRenderable, TextRenderable, conversationBox, inputBox, footerHeight, sendHostMessage } = deps;

  let inputText = "";
  // Caret position as a grapheme index into Array.from(inputText), range [0, len].
  let cursorPos = 0;
  // Pulse FRAME COUNTER is owned by main.mjs; tickPulse(frame) updates this copy
  // so the status pill glyph advances.
  let pulseFrame = 0;
  // Input history (newest last). historyIndex === history.length means "current
  // draft" (not browsing history); 0..length-1 selects a recalled entry.
  const inputHistory = [];
  // Initialize to the sentinel (== length) meaning "on the current draft, not
  // browsing history". With empty history this is 0, but the semantics are correct.
  let historyIndex = inputHistory.length;
  let draftBeforeHistory = "";
  // Cursor blink state for the composer.
  let cursorVisible = true;
  let cursorTimer;
  // Guard against install() binding the keypress/paste listeners more than once.
  let installed = false;

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
    baselineModel: "",
    source: "",
    routingApplied: true,
    rolloutPhase: "full",
  };

  const turnStatus = {
    phase: "idle",
    label: "ready",
    active: false,
  };

  function colorForStyle(style) {
    if (style === "warning") return THEME.routerWarning;
    if (style === "error") return THEME.routerError;
    if (style === "dim") return THEME.muted;
    return THEME.routerNormal;
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

  function routerModelValue() {
    return formatRouterModelValue(routerState.model, routerState.baselineModel);
  }

  // Router route row: tag the route when it is not a normal applied decision so
  // forced/observe/fallback states are distinguishable. A normal route adds no
  // marker to keep the panel quiet.
  function routerRouteValue() {
    const route = routerState.route;
    const source = routerState.source;
    if (routerState.rolloutPhase === "observe" || routerState.routingApplied === false) {
      return `${route} observe`;
    }
    if (source === "forced" || source === "observe" || source === "fallback") {
      return `${route} ·${source}`;
    }
    return route;
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
      height: footerHeight,
      borderStyle: "rounded",
      borderColor: composer.disabled ? THEME.composerDisabledBorder : THEME.composerBorder,
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
        fg: line.muted ? THEME.muted : THEME.text,
      }));
    });
    inputBox.add(composerNode);

    const routerNode = new BoxRenderable(renderer, {
      id: "router-plugin",
      position: "absolute",
      right: 1,
      bottom: 0,
      width: 31,
      height: footerHeight,
      borderStyle: "rounded",
      borderColor: colorForStyle(routerState.style),
      title: " router ",
      titleAlignment: "left",
      paddingLeft: 1,
      paddingRight: 1,
      flexDirection: "column",
    });
    routerNode.add(new TextRenderable(renderer, { id: "router-model", content: fixedRouterRow("model", routerModelValue()), fg: THEME.text }));
    routerNode.add(new TextRenderable(renderer, { id: "router-route", content: fixedRouterRow("route", routerRouteValue()), fg: THEME.routeText }));
    routerNode.add(new TextRenderable(renderer, { id: "router-saving", content: fixedRouterRow("save", routerState.saving), fg: THEME.savingText }));
    routerNode.add(new TextRenderable(renderer, { id: "router-context", content: fixedRouterRow("ctx", routerState.context), fg: THEME.routerWarning }));
    inputBox.add(routerNode);
    renderer.requestRender?.();
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

  // Bundle keyboard-install + blink-start + initial render. (In the old main.mjs
  // buildLayout() did the initial render, and main() called the install + blink.)
  function install() {
    if (installed) return;
    installed = true;
    installKeyboardHandlers();
    startCursorBlink();
    rerenderInputRegion();
  }

  function setComposerState(message) {
    Object.assign(composer, {
      placeholder: String(message.placeholder ?? composer.placeholder),
      text: String(message.text ?? composer.text),
      disabled: Boolean(message.disabled ?? composer.disabled),
    });
    // Route text through setInput so inputText/composer.text/cursorPos stay in
    // sync (caret lands at the end of any prefilled text instead of drifting).
    setInput(composer.text);
    rerenderInputRegion();
  }

  function setRouterState(message) {
    Object.assign(routerState, {
      model: String(message.model ?? routerState.model),
      route: String(message.route ?? routerState.route),
      saving: String(message.saving ?? routerState.saving),
      context: String(message.context ?? routerState.context),
      style: String(message.style ?? routerState.style),
      baselineModel: String(message.baseline_model ?? routerState.baselineModel),
      source: String(message.source ?? routerState.source),
      routingApplied: message.routing_applied ?? routerState.routingApplied,
      rolloutPhase: String(message.rollout_phase ?? routerState.rolloutPhase),
    });
    rerenderInputRegion();
  }

  function setTurnStatus(message) {
    Object.assign(turnStatus, {
      phase: String(message.phase ?? turnStatus.phase),
      label: String(message.label ?? turnStatus.label),
      active: Boolean(message.active ?? turnStatus.active),
    });
    rerenderInputRegion();
  }

  // main.mjs owns the pulse timer; it calls tickPulse(frame) each tick so the
  // status pill glyph advances. This replaces the old syncPulseTimer's per-tick
  // rerenderInputRegion().
  function tickPulse(frame) {
    pulseFrame = frame;
    rerenderInputRegion();
  }

  // Composer-relevant resize work: re-render the footer. (conversationBox height
  // resize stays in main.mjs.)
  function onResize() {
    rerenderInputRegion();
  }

  return {
    install,
    rerender: rerenderInputRegion,
    setComposerState,
    setRouterState,
    setTurnStatus,
    onResize,
    tickPulse,
  };
}
