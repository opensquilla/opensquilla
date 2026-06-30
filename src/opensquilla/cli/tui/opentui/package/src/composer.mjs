import { THEME, THEME_NAMES, STATUS_PULSE_FRAMES, applyTheme, activeThemeName } from "./theme.mjs";
import { cellWidth, clipToCells, stripTerminalControls, textWidth } from "./primitives.mjs";

const COMPLETION_MENU_LEFT = 1;
const COMPLETION_MENU_RIGHT = 34;
const COMPLETION_MENU_CHROME_CELLS = 4; // left/right border plus left/right padding
const MIN_COMPLETION_ROW_CELLS = 16;
const COMPOSER_LEFT = 1;
const COMPOSER_CONTENT_LEFT = COMPOSER_LEFT + 2; // border plus left padding
// The composer box sits one row below the top of the footer (the router status
// strip occupies that first row), so its first content row is 2 below footerTop:
// the strip row (0) + the composer box's own top border (1).
const COMPOSER_CONTENT_TOP_OFFSET = 2;

// Pure key handling for the theme picker overlay (modeled on menuKeyAction):
// up/down preview the highlighted theme live, enter keeps it, escape reverts.
export function themePickerKeyAction(picker, keyName) {
  if (!picker?.active) return { handled: false, action: "pass", selected: 0 };
  const max = Math.max(0, (picker.names?.length ?? 0) - 1);
  const sel = clamp(Number(picker.selected) || 0, 0, max);
  if (keyName === "up") return { handled: true, action: "preview", selected: clamp(sel - 1, 0, max) };
  if (keyName === "down") return { handled: true, action: "preview", selected: clamp(sel + 1, 0, max) };
  if (keyName === "return" || keyName === "tab") return { handled: true, action: "confirm", selected: sel };
  if (keyName === "escape") return { handled: true, action: "cancel", selected: sel };
  // Modal: swallow every other key so it never leaks into the input while open.
  return { handled: true, action: "none", selected: sel };
}

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

// Index of the start of the line the caret is on (just after the previous "\n",
// or 0). Powers Ctrl+A and the start of the Ctrl+U cut.
export function lineStartIndex(text, pos) {
  const chars = Array.from(String(text ?? ""));
  let i = clamp(Number(pos) || 0, 0, chars.length);
  while (i > 0 && chars[i - 1] !== "\n") i -= 1;
  return i;
}

// Index of the end of the line the caret is on (the next "\n", or end of text).
// Powers Ctrl+E and the end of the Ctrl+K cut.
export function lineEndIndex(text, pos) {
  const chars = Array.from(String(text ?? ""));
  let i = clamp(Number(pos) || 0, 0, chars.length);
  while (i < chars.length && chars[i] !== "\n") i += 1;
  return i;
}

// Start of the whitespace-delimited word before the caret (skip trailing
// whitespace, then the word). Powers Ctrl+W / Alt+Backspace and Ctrl+Left.
export function wordStartIndex(text, pos) {
  const chars = Array.from(String(text ?? ""));
  let i = clamp(Number(pos) || 0, 0, chars.length);
  while (i > 0 && /\s/u.test(chars[i - 1])) i -= 1;
  while (i > 0 && !/\s/u.test(chars[i - 1])) i -= 1;
  return i;
}

// End of the whitespace-delimited word after the caret (skip leading whitespace,
// then the word). Powers Ctrl+Right / Alt+F.
export function wordEndIndex(text, pos) {
  const chars = Array.from(String(text ?? ""));
  let i = clamp(Number(pos) || 0, 0, chars.length);
  while (i < chars.length && /\s/u.test(chars[i])) i += 1;
  while (i < chars.length && !/\s/u.test(chars[i])) i += 1;
  return i;
}

// Remove the [from, to) grapheme range; returns the new text and the caret
// position (collapsed to the cut start).
export function spliceOut(text, from, to) {
  const chars = Array.from(String(text ?? ""));
  const a = clamp(Math.min(from, to), 0, chars.length);
  const b = clamp(Math.max(from, to), 0, chars.length);
  return { text: [...chars.slice(0, a), ...chars.slice(b)].join(""), cursor: a };
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
    // Nothing to accept (zero matches): Enter must still SUBMIT the message
    // (fall through, don't swallow it); Tab just closes the menu with no insert.
    if ((menu.filtered?.length ?? 0) === 0) {
      if (keyName === "return") return { handled: false, action: "pass", menu: { ...menu, active: false } };
      return { handled: true, action: "close", menu: { ...menu, active: false } };
    }
    // Enter on a slash command RUNS it (accept + submit) in one keystroke instead
    // of just inserting it and waiting for a second Enter. Tab completes it so you
    // can still type arguments (e.g. `/theme dark`). File completions only insert
    // the path — Enter there keeps composing the message, never submits it.
    if (keyName === "return" && menu.kind === "slash") {
      return { handled: true, action: "accept_submit", menu };
    }
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
  // Goal column for vertical (Up/Down) motion, measured in DISPLAY CELLS so the
  // caret tracks the same visual column across lines that mix narrow and wide
  // (CJK) glyphs. Preserved across consecutive vertical moves — passing through a
  // short line keeps the original column — and reset to null by any other caret
  // motion (see the keypress handler). null means "recompute from the caret".
  let desiredVisualCol = null;
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
  // Caret visibility flag, retained for the (now inert) wakeCursor() callers; the
  // visible caret is the hardware terminal cursor, blinked natively, so there is
  // no app-side blink timer (see startCursorBlink).
  let cursorVisible = true;
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

  function statusIcon() {
    if (!turnStatus.active) return "✓";
    const frames = STATUS_PULSE_FRAMES[turnStatus.phase] ?? STATUS_PULSE_FRAMES.thinking;
    return frames[pulseFrame % frames.length];
  }

  function startCursorBlink() {
    // Intentionally a no-op. The caret is the real hardware terminal cursor now
    // (caretGlyph renders a blank cell; syncTerminalCursorToCaret shows it via
    // setCursorPosition), and the terminal blinks it natively. The old 530ms
    // self-render re-asserted setCursorPosition on every tick — during macOS IME
    // composition the app gets no keystrokes, so that timer was the ONLY thing
    // re-rendering, and its repeated cursor re-assertion disrupted the terminal's
    // marked-text handling and corrupted the router panel's first row while
    // typing. Removing the timer fixes that; nothing else needs the 530ms redraw.
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

  // The caret is now the REAL hardware terminal cursor (positioned + shown via
  // syncTerminalCursorToCaret with visible:true), which is what macOS IME anchors
  // its candidate popover to. So the composer no longer paints its own caret —
  // doing both would render two carets. Keep a blank cell here so the input line
  // layout is unchanged and the hardware cursor sits on an empty cell.
  function caretGlyph() {
    return " ";
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
        fg: index === selected ? THEME.brandAccentSoft : THEME.text,
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
    overlayLayer?.remove?.("theme-picker");
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

  // ---- Theme picker overlay -------------------------------------------------
  // A modal theme list mounted on the overlay layer (like the completion menu).
  // Arrow keys preview each theme live; Enter keeps it; Esc reverts to the theme
  // that was active when the picker opened. Rendering here (not console output)
  // is why it looks like a panel instead of stray scrollback text.
  const THEME_PICKER_WIDTH = 34;
  const THEME_PICKER_INNER = THEME_PICKER_WIDTH - COMPLETION_MENU_CHROME_CELLS;
  let themePicker = null;

  function applyHostTheme(name) {
    applyTheme(name);
    renderer.setBackgroundColor?.(THEME.appBg);
    if (conversationBox) conversationBox.backgroundColor = THEME.appBg;
    if (inputBox) inputBox.backgroundColor = THEME.footerBg;
    rerenderInputRegion(); // repaints the footer (and clears the overlay)…
    renderThemePicker(); // …so remount the picker (no-op when closed) in new colors
    renderer.requestRender?.();
  }

  function renderThemePicker() {
    if (!themePicker?.active) return;
    overlayLayer?.remove?.("theme-picker");
    const names = themePicker.names;
    const maxRows = Math.max(1, (renderer.terminalHeight ?? 24) - footerHeight - 1);
    const node = new BoxRenderable(renderer, {
      id: "theme-picker",
      position: "absolute",
      left: COMPLETION_MENU_LEFT,
      width: THEME_PICKER_WIDTH,
      bottom: footerHeight,
      height: Math.min(names.length + 3, maxRows),
      borderStyle: "rounded",
      borderColor: THEME.brandAccent,
      backgroundColor: THEME.overlayBg,
      title: " theme ",
      titleAlignment: "left",
      flexDirection: "column",
      paddingLeft: 1,
      paddingRight: 1,
    });
    names.forEach((name, index) => {
      const active = index === themePicker.selected;
      node.add(new TextRenderable(renderer, {
        id: `theme-picker-row-${index}`,
        content: clipToCells(`${active ? "› " : "  "}${name}`, THEME_PICKER_INNER),
        fg: active ? THEME.brandAccentSoft : THEME.muted,
      }));
    });
    node.add(new TextRenderable(renderer, {
      id: "theme-picker-hint",
      content: clipToCells("↑↓ preview · enter keep · esc", THEME_PICKER_INNER),
      fg: THEME.detailText,
    }));
    overlayLayer.add(node);
    overlayLayer.visible = true;
  }

  function openThemePicker() {
    resetMenu(); // close the completion menu if it was open
    const names = THEME_NAMES;
    let selected = names.indexOf(activeThemeName());
    if (selected < 0) selected = 0;
    themePicker = { active: true, names, selected, original: activeThemeName() };
    renderThemePicker();
    renderer.requestRender?.();
  }

  function closeThemePicker() {
    themePicker = null;
    clearOverlay();
  }

  function handleThemePickerKey(keyName) {
    const result = themePickerKeyAction(themePicker, keyName);
    if (!result.handled) return false;
    if (result.action === "preview") {
      themePicker.selected = result.selected;
      applyHostTheme(themePicker.names[result.selected]);
    } else if (result.action === "confirm") {
      closeThemePicker();
      renderer.requestRender?.();
    } else if (result.action === "cancel") {
      const original = themePicker.original;
      closeThemePicker();
      applyHostTheme(original); // revert the live preview
    }
    return true;
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
      left: COMPOSER_LEFT,
      right: COMPOSER_LEFT, // full width: nothing shares the caret's rows
      bottom: 0,
      height: Math.max(1, footerHeight - 1), // the router strip takes the top row
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

    // Router status as a compact single-line strip ABOVE the (now full-width)
    // composer. Keeping it OFF the caret's rows is the fix for the macOS IME
    // corruption: with no box sharing the rows where the terminal composites the
    // marked-text / candidate overlay, there is no adjacent cell band for the
    // terminal's wide-char accounting to desync. (opencode, on the same
    // @opentui/core engine + alt-screen, is immune for exactly this reason — its
    // status sits below the input and its sidebar is a disjoint column.)
    const stripValue = (v) => clipToCells(String(v ?? "").replace(/\s+/gu, " ").trim() || "-", 18);
    const routerStrip = new BoxRenderable(renderer, {
      id: "router-strip",
      position: "absolute",
      top: 0,
      left: COMPOSER_LEFT,
      right: COMPOSER_LEFT,
      height: 1,
      paddingLeft: 2, // align the strip text with the composer's input text
      flexDirection: "row",
      backgroundColor: THEME.footerBg,
    });
    const chip = (suffix, content, fg) =>
      routerStrip.add(new TextRenderable(renderer, { id: `router-${suffix}`, content, fg }));
    // A quiet "router" label, dim field labels, and each VALUE in its semantic
    // color, with fields separated by a dim middot — matching the usage footnote
    // (value-forward hierarchy: data pops, labels recede).
    let sepN = 0;
    const field = (key, label, value, valueFg) => {
      chip(`sep${sepN++}`, " · ", THEME.detailText);
      chip(`${key}-label`, `${label} `, THEME.detailText);
      chip(`${key}-value`, stripValue(value), valueFg);
    };
    chip("label", "router", THEME.muted);
    field("model", "model", routerModelValue(), THEME.text);
    field("route", "route", routerRouteValue(), THEME.routeText);
    field("saving", "save", routerState.saving, THEME.metricPositive);
    field("context", "ctx", routerState.context, THEME.warning);
    inputBox.add(routerStrip);
    renderCompletionMenu();
    // The theme picker shares the overlay layer, so a footer re-render (pulse
    // tick while a turn streams, router update, keystroke) clears it via
    // renderCompletionMenu's clearOverlay. Re-mount it whenever it is open so it
    // never "flashes" away and gets stuck modally swallowing keys while invisible.
    if (themePicker?.active) renderThemePicker();
    syncTerminalCursorToCaret();
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
    desiredVisualCol = null; // history recall / programmatic set ends a vertical run
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

  function caretVisualLineCol() {
    const chars = Array.from(inputText);
    const pos = Math.max(0, Math.min(cursorPos, chars.length));
    let line = 0;
    let lineText = "";
    for (let i = 0; i < pos; i += 1) {
      if (chars[i] === "\n") {
        line += 1;
        lineText = "";
      } else {
        lineText += chars[i];
      }
    }
    return { line, col: textWidth(lineText) };
  }

  function syncTerminalCursorToCaret() {
    const setCursorPosition = renderer?.setCursorPosition;
    if (typeof setCursorPosition !== "function") return;
    const terminalWidth = Number(renderer?.terminalWidth ?? renderer?.width) || 80;
    const terminalHeight = Number(renderer?.terminalHeight ?? renderer?.height) || 24;
    const footerTop = Math.max(0, terminalHeight - footerHeight);
    const { line, col } = caretVisualLineCol();
    const maxX = Math.max(COMPOSER_CONTENT_LEFT, terminalWidth - COMPOSER_CONTENT_LEFT - 1);
    const maxY = Math.max(footerTop, footerTop + footerHeight - 2);
    const x = clamp(COMPOSER_CONTENT_LEFT + col, COMPOSER_CONTENT_LEFT, maxX);
    const y = clamp(
      footerTop + COMPOSER_CONTENT_TOP_OFFSET + line,
      footerTop + COMPOSER_CONTENT_TOP_OFFSET,
      maxY,
    );
    // visible:true is REQUIRED for IME anchoring. OpenTUI's native renderer only
    // emits a CUP move (and shows the hardware cursor) when visible is true; with
    // false it keeps the hardware cursor hidden at home, so macOS terminals
    // (Terminal.app/iTerm2) anchor the Pinyin candidate popover to that hidden
    // home position — the candidate window drifts to a corner instead of the
    // caret. Showing the real cursor here lets the IME attach candidates at the
    // caret cell. The composer no longer paints its own "▏" (see caretGlyph) so
    // there is exactly one caret.
    //
    // +1 on both axes: x/y above are 0-based screen cells, but OpenTUI's native
    // cursor path is 1-based — its own TextEditor.renderCursor passes
    // screenX/Y + visual + 1. Without the +1 the reported cell is one row too
    // high and one column too far left, so the IME (and the visible caret) land
    // off the true caret cell. Match OpenTUI's convention exactly.
    setCursorPosition.call(renderer, x + 1, y + 1, true);
  }

  // Grapheme index of the caret on `targetLine` whose DISPLAY-CELL column is
  // closest to `targetVisualCol`. Snaps to a grapheme boundary: when the goal
  // falls mid-glyph (e.g. inside a width-2 CJK char), land on whichever side is
  // nearer, and never past the line's end.
  function lineVisualColToPos(chars, targetLine, targetVisualCol) {
    let line = 0;
    let col = 0; // display cells consumed on the current line so far
    let lineStart = 0;
    for (let i = 0; i <= chars.length; i += 1) {
      const atEnd = i === chars.length || chars[i] === "\n";
      if (line === targetLine && (atEnd || col >= targetVisualCol)) {
        // Boundary before chars[i] sits at column `col`. If we stepped over the
        // goal mid-glyph, the previous boundary may be the nearer one.
        if (!atEnd && i > lineStart && col > targetVisualCol) {
          const prevCol = col - cellWidth(chars[i - 1]);
          if (targetVisualCol - prevCol < col - targetVisualCol) return i - 1;
        }
        return i;
      }
      if (atEnd) {
        if (line === targetLine) return i; // goal past the end of this line
        line += 1;
        col = 0;
        lineStart = i + 1;
      } else {
        col += cellWidth(chars[i]);
      }
    }
    return chars.length;
  }

  // Move caret up/down a line. Returns true if it moved within the text; false if
  // already at the very first/last line (caller may then switch history). Tracks a
  // desired VISUAL column (display cells) so the caret keeps its on-screen column
  // across lines with wide (CJK) glyphs, and preserves it across consecutive moves.
  function moveCaretVertical(direction) {
    const { line, col } = caretVisualLineCol();
    const chars = Array.from(inputText);
    const lineCount = inputText.split("\n").length;
    const target = line + direction;
    if (target < 0 || target >= lineCount) return false;
    if (desiredVisualCol === null) desiredVisualCol = col;
    cursorPos = lineVisualColToPos(chars, target, desiredVisualCol);
    return true;
  }

  function moveCaretHorizontal(direction) {
    const len = Array.from(inputText).length;
    cursorPos = Math.max(0, Math.min(len, cursorPos + direction));
  }

  function insertAtCursor(insertText) {
    desiredVisualCol = null; // editing (incl. paste) ends a vertical-motion run
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

  // Forward delete: remove the grapheme AT the caret (the Delete key). The caret
  // stays put, like every other terminal input.
  function deleteAtCursor() {
    const chars = Array.from(inputText);
    const pos = Math.max(0, Math.min(cursorPos, chars.length));
    if (pos >= chars.length) return;
    inputText = [...chars.slice(0, pos), ...chars.slice(pos + 1)].join("");
    composer.text = inputText;
    cursorPos = pos;
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
    if (result.action === "accept_submit") {
      // Insert the highlighted command, then submit it — one Enter runs it.
      acceptCompletion();
      submitInput();
      return true;
    }
    Object.assign(menu, result.menu);
    rerenderInputRegion();
    return true;
  }

  function installKeyboardHandlers() {
    renderer.keyInput.on("keypress", (key) => {
      // Any key other than Up/Down ends a vertical-motion run, so the next Up/Down
      // recomputes the goal column from the caret's current visual position.
      if (key.name !== "up" && key.name !== "down") desiredVisualCol = null;
      // The theme picker is modal: it consumes every key while open.
      if (themePicker?.active) {
        handleThemePickerKey(key.name);
        return;
      }
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
      // Standard readline-style line editing.
      if (key.ctrl && key.name === "a") {
        cursorPos = lineStartIndex(inputText, cursorPos); // start of line
        wakeCursor();
        rerenderInputRegion();
        return;
      }
      if (key.ctrl && key.name === "e") {
        cursorPos = lineEndIndex(inputText, cursorPos); // end of line
        wakeCursor();
        rerenderInputRegion();
        return;
      }
      if (
        (key.ctrl && (key.name === "u" || key.name === "k" || key.name === "w")) ||
        ((key.meta || key.alt || key.option) && key.name === "backspace")
      ) {
        // Ctrl+U cut to line start · Ctrl+K cut to line end · Ctrl+W /
        // Alt+Backspace delete the previous word.
        let from = cursorPos;
        let to = cursorPos;
        if (key.name === "k") to = lineEndIndex(inputText, cursorPos);
        else if (key.name === "u") from = lineStartIndex(inputText, cursorPos);
        else from = wordStartIndex(inputText, cursorPos);
        const edited = spliceOut(inputText, from, to);
        inputText = edited.text;
        composer.text = inputText;
        cursorPos = edited.cursor;
        historyIndex = inputHistory.length;
        updateMenuFromInput();
        wakeCursor();
        rerenderInputRegion();
        return;
      }
      // Word-wise cursor movement (must precede the plain left/right branches,
      // which ignore modifiers). Ctrl+Left/Alt+B back a word; Ctrl+Right/Alt+F
      // forward a word.
      const wordBack =
        (key.ctrl && key.name === "left") ||
        ((key.meta || key.alt || key.option) && key.name === "b");
      const wordForward =
        (key.ctrl && key.name === "right") ||
        ((key.meta || key.alt || key.option) && key.name === "f");
      if (wordBack || wordForward) {
        cursorPos = wordBack
          ? wordStartIndex(inputText, cursorPos)
          : wordEndIndex(inputText, cursorPos);
        wakeCursor();
        rerenderInputRegion();
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
      // Forward word delete (Alt+D / Ctrl+Delete) — must precede the plain Delete
      // branch, which ignores modifiers.
      if (
        ((key.meta || key.alt || key.option) && key.name === "d") ||
        (key.ctrl && key.name === "delete")
      ) {
        const edited = spliceOut(inputText, cursorPos, wordEndIndex(inputText, cursorPos));
        inputText = edited.text;
        composer.text = inputText;
        cursorPos = edited.cursor;
        historyIndex = inputHistory.length;
        updateMenuFromInput();
        wakeCursor();
        rerenderInputRegion();
        return;
      }
      if (key.name === "delete") {
        deleteAtCursor(); // forward-delete the character at the caret
        updateMenuFromInput();
        wakeCursor();
        rerenderInputRegion();
        return;
      }
      const printable = key.sequence ?? key.name ?? "";
      // Only single keystrokes reach here (paste has its own handler below).
      // Reject control bytes: Tab (\t) and the ESC sequences from unhandled
      // special keys (home/end/delete/F-keys) would otherwise be inserted
      // verbatim and end up submitted in the message. Real typed text is printable.
      const isControlKey = /[\u0000-\u001f\u007f]/u.test(printable);
      if (printable.length > 0 && !isControlKey && !key.ctrl && !key.meta && key.name !== "space") {
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
      // Sanitize pasted text: strip ANSI/escape sequences and C0/DEL control
      // bytes (e.g. pasting colored terminal output or a log) so they cannot
      // corrupt the input or get submitted to the model. Newlines and tabs are
      // preserved, so multi-line and indented pastes are unaffected.
      const pasted = stripTerminalControls(decoder.decode(event.bytes));
      if (!pasted) return;
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
    openThemePicker,
    applyHostTheme,
  };
}
