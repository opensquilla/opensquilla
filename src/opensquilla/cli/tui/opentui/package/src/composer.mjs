import { THEME, STATUS_PULSE_FRAMES } from "./theme.mjs";
import { cellWidth, clipToCells } from "./primitives.mjs";

const COMPLETION_MENU_LEFT = 1;
const COMPLETION_MENU_RIGHT = 34;
const COMPLETION_MENU_CHROME_CELLS = 4; // left/right border plus left/right padding
const MIN_COMPLETION_ROW_CELLS = 16;

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

function clamp(value, min, max) {
  if (max < min) return min;
  return Math.max(min, Math.min(max, value));
}

export function tokenUnderCaret(text, cursorPos) {
  const chars = Array.from(String(text ?? ""));
  const pos = clamp(Number(cursorPos) || 0, 0, chars.length);
  let start = pos;
  while (start > 0 && !/\s/u.test(chars[start - 1])) start -= 1;
  return { token: chars.slice(start, pos).join(""), start };
}

function lineStartForToken(text, start) {
  const chars = Array.from(String(text ?? ""));
  const pos = clamp(Number(start) || 0, 0, chars.length);
  return pos === 0 || chars[pos - 1] === "\n";
}

export function shouldTriggerMenu(token, start, lineStart) {
  const value = String(token ?? "");
  if (value.startsWith("/") && lineStart) {
    return { active: true, kind: "slash", query: value.slice(1) };
  }
  if (value.startsWith("@")) {
    return { active: true, kind: "file", query: value.slice(1) };
  }
  return { active: false, kind: null, query: "" };
}

function subsequencePositions(query, text) {
  const positions = [];
  let from = 0;
  for (const char of Array.from(query)) {
    const index = text.indexOf(char, from);
    if (index < 0) return null;
    positions.push(index);
    from = index + 1;
  }
  return positions;
}

function pathSegments(text) {
  return String(text ?? "")
    .replaceAll("\\", "/")
    .split(/[\/._\-\s]+/u)
    .filter(Boolean);
}

function isSegmentStart(text, position) {
  return position === 0 || "/\\._- ".includes(text[position - 1]);
}

function fuzzyScore(query, candidate) {
  const q = String(query ?? "").toLocaleLowerCase();
  const text = String(candidate ?? "").toLocaleLowerCase();
  if (!q) return 0;
  const positions = subsequencePositions(q, text);
  if (!positions) return null;

  let score = q.length * 100;
  if (text.startsWith(q)) score += 80;
  const segments = pathSegments(text);
  const commandSegment = text.startsWith("/") ? segments[0] : null;
  if (commandSegment?.startsWith(q)) score += 90;
  const prefixSegment = segments.find((segment) => segment.startsWith(q));
  if (prefixSegment) {
    score += 60;
    score += Math.max(0, 24 - prefixSegment.length * 2);
  }

  let runLength = 1;
  let longestRun = 1;
  for (let i = 1; i < positions.length; i += 1) {
    if (positions[i] === positions[i - 1] + 1) {
      runLength += 1;
      longestRun = Math.max(longestRun, runLength);
    } else {
      runLength = 1;
    }
  }
  score += longestRun * longestRun * 8;

  for (const position of positions) {
    if (isSegmentStart(text, position)) score += 18;
  }
  score += Math.max(0, 30 - positions[0] * 0.75);
  score += Math.max(0, 18 - String(candidate ?? "").length * 0.35);
  return score;
}

export function filterCatalog(catalog, query) {
  const items = Array.isArray(catalog) ? catalog : [];
  const q = String(query ?? "");
  if (!q) return [...items];
  return items
    .map((item, index) => ({
      item,
      index,
      score: fuzzyScore(q, String(item?.label ?? "")),
    }))
    .filter((entry) => entry.score !== null)
    .sort((a, b) => (b.score - a.score) || (a.index - b.index))
    .map((entry) => entry.item);
}

export function acceptCompletionText(text, tokenStart, cursorPos, insertText) {
  const chars = Array.from(String(text ?? ""));
  const start = clamp(Number(tokenStart) || 0, 0, chars.length);
  const cursor = clamp(Number(cursorPos) || 0, start, chars.length);
  const insertChars = Array.from(String(insertText ?? ""));
  const nextText = [
    ...chars.slice(0, start),
    ...insertChars,
    ...chars.slice(cursor),
  ].join("");
  return { text: nextText, cursor: start + insertChars.length };
}

export function shouldDropResponse(responseReqId, currentSeq) {
  return Number(responseReqId) !== Number(currentSeq);
}

export function menuKeyAction(menu, keyName) {
  if (!menu?.active) return { handled: false, action: "pass", menu };
  const selected = Number(menu.selected) || 0;
  const maxSelected = Math.max(0, (menu.filtered?.length ?? 0) - 1);
  if (keyName === "up") {
    return {
      handled: true,
      action: "navigate",
      menu: { ...menu, selected: clamp(selected - 1, 0, maxSelected) },
    };
  }
  if (keyName === "down") {
    return {
      handled: true,
      action: "navigate",
      menu: { ...menu, selected: clamp(selected + 1, 0, maxSelected) },
    };
  }
  if (keyName === "escape") {
    return { handled: true, action: "close", menu: { ...menu, active: false } };
  }
  if (keyName === "return" || keyName === "tab") {
    return { handled: true, action: "accept", menu };
  }
  return { handled: false, action: "pass", menu };
}

function fileCompletionItems(paths) {
  return (Array.isArray(paths) ? paths : []).map((path) => ({
    label: String(path),
    description: String(path),
    insert_text: `@${path} `,
    category: "file",
  }));
}

// Factory for the composer / input-region. All state that main.mjs previously
// held as module-level globals lives here as closure state; the rendering deps
// (renderer, renderable classes, boxes, footer height, host writer) are injected
// via `deps`.
export function createComposer(deps) {
  const { renderer, BoxRenderable, TextRenderable, conversationBox, inputBox, overlayLayer, footerHeight, sendHostMessage } = deps;

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

  const completionContext = {
    catalog: [],
    files: [],
    filtersSensitivePaths: true,
  };
  const menu = {
    active: false,
    kind: null,
    query: "",
    tokenStart: 0,
    filtered: [],
    selected: 0,
    requestSeq: 0,
  };
  let fileDebounce = null;

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

  function resetMenu() {
    menu.active = false;
    menu.kind = null;
    menu.query = "";
    menu.tokenStart = 0;
    menu.filtered = [];
    menu.selected = 0;
    if (fileDebounce) {
      clearTimeout(fileDebounce);
      fileDebounce = null;
    }
    clearOverlay();
  }

  function clampMenuSelection() {
    menu.selected = clamp(menu.selected, 0, Math.max(0, menu.filtered.length - 1));
  }

  function scheduleFileCompletionRequest(query) {
    if (fileDebounce) clearTimeout(fileDebounce);
    const requestId = menu.requestSeq + 1;
    menu.requestSeq = requestId;
    fileDebounce = setTimeout(() => {
      fileDebounce = null;
      if (!menu.active || menu.kind !== "file" || menu.requestSeq !== requestId) return;
      sendHostMessage({
        type: "completion.request",
        kind: "file",
        query,
        request_id: requestId,
      });
    }, 120);
    fileDebounce.unref?.();
  }

  function updateMenuFromInput() {
    const { token, start } = tokenUnderCaret(inputText, cursorPos);
    const trigger = shouldTriggerMenu(token, start, lineStartForToken(inputText, start));
    if (!trigger.active) {
      resetMenu();
      return;
    }

    menu.active = true;
    menu.kind = trigger.kind;
    menu.query = trigger.query;
    menu.tokenStart = start;
    if (menu.kind === "slash") {
      if (fileDebounce) {
        clearTimeout(fileDebounce);
        fileDebounce = null;
      }
      menu.filtered = filterCatalog(completionContext.catalog, menu.query);
    } else {
      menu.filtered = filterCatalog(fileCompletionItems(completionContext.files), menu.query);
      scheduleFileCompletionRequest(menu.query);
    }
    clampMenuSelection();
  }

  function completionMenuRows() {
    if (menu.filtered.length === 0) {
      return [{ content: "no matches", fg: THEME.muted }];
    }
    const visible = Math.min(6, menu.filtered.length);
    const selected = clamp(menu.selected, 0, menu.filtered.length - 1);
    let start = Math.max(0, selected - Math.floor(visible / 2));
    start = Math.min(start, Math.max(0, menu.filtered.length - visible));
    return menu.filtered.slice(start, start + visible).map((item, offset) => {
      const index = start + offset;
      const marker = index === selected ? "› " : "  ";
      const label = String(item.label ?? "");
      const description = String(item.description ?? "");
      const content = `${marker}${label}${description ? `  ${description}` : ""}`;
      return {
        content: clipToCells(content, completionMenuRowCells()),
        fg: index === selected ? THEME.toolAccent : THEME.text,
      };
    });
  }

  function completionMenuRowCells() {
    const terminalWidth = Number(renderer?.terminalWidth) || 100;
    return Math.max(
      MIN_COMPLETION_ROW_CELLS,
      terminalWidth - COMPLETION_MENU_LEFT - COMPLETION_MENU_RIGHT - COMPLETION_MENU_CHROME_CELLS,
    );
  }

  // Remove any previously mounted completion menu from the overlay layer so a
  // shrinking menu never leaves a stale node behind and re-renders don't stack.
  function clearOverlay() {
    overlayLayer?.remove?.("completion-menu");
    // Hide the layer again so it stops intercepting wheel events — otherwise a
    // permanently-visible full-screen overlay blocks conversation scrolling.
    if (overlayLayer) overlayLayer.visible = false;
  }

  function renderCompletionMenu() {
    // Always clear first: a closed menu must vanish, and an open one is rebuilt
    // fresh so its height tracks the current candidate count exactly.
    clearOverlay();
    if (!menu.active) return;
    const rows = completionMenuRows();
    // Mounted on the full-screen overlay layer (a root sibling), so `bottom` is
    // screen-relative: footerHeight rows up puts the menu directly above the
    // footer. It can never bleed into the scrollback buffer the way an
    // inputBox-child overflowing upward did, and the overlay's high zIndex keeps
    // it painted above the conversation.
    const menuNode = new BoxRenderable(renderer, {
      id: "completion-menu",
      position: "absolute",
      left: COMPLETION_MENU_LEFT,
      right: COMPLETION_MENU_RIGHT,
      bottom: footerHeight,
      height: Math.min(8, rows.length + 2),
      borderStyle: "rounded",
      borderColor: THEME.composerBorder,
      // Opaque fill so the conversation behind the menu cannot show through and
      // collide with the menu rows (a transparent box leaks the backdrop).
      backgroundColor: THEME.overlayBg,
      title: menu.kind === "file" ? " files " : " commands ",
      titleAlignment: "left",
      flexDirection: "column",
      paddingLeft: 1,
      paddingRight: 1,
    });
    rows.forEach((row, index) => {
      menuNode.add(new TextRenderable(renderer, {
        id: `completion-menu-row-${index}`,
        content: row.content,
        fg: row.fg,
      }));
    });
    overlayLayer.add(menuNode);
    // Reveal the layer only now that it carries a menu, so it intercepts mouse
    // events solely while the menu is open (clearOverlay hides it again).
    overlayLayer.visible = true;
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
    renderCompletionMenu();
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
    resetMenu();
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
    updateMenuFromInput();
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

  function acceptCompletion() {
    const item = menu.filtered[clamp(menu.selected, 0, menu.filtered.length - 1)];
    if (!item) {
      resetMenu();
      rerenderInputRegion();
      return;
    }
    const insertText = String(item.insert_text ?? item.label ?? "");
    const accepted = acceptCompletionText(inputText, menu.tokenStart, cursorPos, insertText);
    inputText = accepted.text;
    composer.text = inputText;
    cursorPos = accepted.cursor;
    resetMenu();
    wakeCursor();
    rerenderInputRegion();
  }

  function applyMenuKeyResult(result) {
    if (!result.handled) return false;
    if (result.action === "accept") {
      acceptCompletion();
      return true;
    }
    Object.assign(menu, result.menu);
    rerenderInputRegion();
    return true;
  }

  function installKeyboardHandlers() {
    renderer.keyInput.on("keypress", (key) => {
      if (menu.active) {
        const menuResult = menuKeyAction(menu, key.name);
        if (applyMenuKeyResult(menuResult)) return;
      }
      if (key.ctrl && key.name === "c") {
        // With text: clear the input. Empty: interrupt the in-flight turn.
        // Ctrl-D owns EOF/exit.
        if (inputText.length > 0) {
          setInput("");
          historyIndex = inputHistory.length;
          resetMenu();
          wakeCursor();
          rerenderInputRegion();
        } else {
          sendHostMessage({ type: "input.cancel" });
          wakeCursor();
          rerenderInputRegion();
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
          updateMenuFromInput();
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
        updateMenuFromInput();
        wakeCursor();
        rerenderInputRegion();
        return;
      }
      const printable = key.sequence ?? key.name ?? "";
      if (printable.length > 0 && !key.ctrl && !key.meta && key.name !== "space") {
        insertAtCursor(printable);
        historyIndex = inputHistory.length;
        updateMenuFromInput();
        wakeCursor();
        rerenderInputRegion();
      } else if (key.name === "space") {
        insertAtCursor(" ");
        historyIndex = inputHistory.length;
        updateMenuFromInput();
        wakeCursor();
        rerenderInputRegion();
      }
    });

    const decoder = new TextDecoder();
    renderer.keyInput.on("paste", (event) => {
      const pasted = decoder.decode(event.bytes);
      insertAtCursor(pasted);
      historyIndex = inputHistory.length;
      if (pasted.includes("\n")) resetMenu();
      else updateMenuFromInput();
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
    updateMenuFromInput();
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

  function setCompletionContext(message) {
    completionContext.catalog = Array.isArray(message.catalog) ? message.catalog : [];
    completionContext.files = Array.isArray(message.files) ? message.files : [];
    completionContext.filtersSensitivePaths = Boolean(
      message.filters_sensitive_paths ?? completionContext.filtersSensitivePaths,
    );
    if (menu.active) {
      updateMenuFromInput();
      rerenderInputRegion();
    }
  }

  function applyCompletionResponse(message) {
    if (
      !menu.active
      || menu.kind !== String(message.kind ?? "")
      || shouldDropResponse(message.request_id, menu.requestSeq)
    ) {
      return;
    }
    menu.filtered = Array.isArray(message.items) ? message.items : [];
    clampMenuSelection();
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
    setCompletionContext,
    applyCompletionResponse,
    onResize,
    tickPulse,
  };
}
