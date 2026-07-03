// Composer input hygiene: a single keystroke must only insert real text, never
// control bytes. Pressing Tab with no completion menu used to inject a literal
// "\t" that got submitted in the message; unhandled special keys (home/end/
// F-keys) likewise must not leak their ESC sequences into the input. Paste keeps
// its own handler, so multi-line / tab-containing pastes are unaffected.
//
// Run with: bun test src/composer-input.bun.test.mjs
import { test, expect } from "bun:test";
import { createTestRenderer } from "@opentui/core/testing";
import { BoxRenderable, TextRenderable } from "@opentui/core";

import { createComposer } from "./composer.mjs";
import { applyTheme } from "./theme.mjs";

async function setupComposer() {
  applyTheme("opensquilla-dark");
  const sent = [];
  const { renderer } = await createTestRenderer({ width: 50, height: 10 });
  const mk = (id, height) => {
    const box = new BoxRenderable(renderer, {
      id, position: "absolute", left: 0, right: 0, bottom: 0, height,
    });
    renderer.root.add(box);
    return box;
  };
  const conversationBox = mk("conversation", 4);
  const inputBox = mk("input-region", 6);
  const overlayLayer = new BoxRenderable(renderer, {
    id: "overlay-layer", position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    zIndex: 1000, shouldFill: false, visible: false,
  });
  renderer.root.add(overlayLayer);
  const composer = createComposer({
    renderer, BoxRenderable, TextRenderable, conversationBox, inputBox, overlayLayer,
    footerHeight: 6, sendHostMessage: (m) => sent.push(m),
  });
  try {
    composer.install();
  } catch {
    composer.rerender();
  }
  return { renderer, sent };
}

async function submittedAfter(keys) {
  const { renderer, sent } = await setupComposer();
  for (const key of keys) renderer.keyInput.emit("keypress", key);
  renderer.keyInput.emit("keypress", { name: "return" });
  const text = sent.find((m) => m.type === "input.submit")?.text;
  renderer.destroy?.();
  return text;
}

test("Tab with no completion menu does not insert a literal tab", async () => {
  const text = await submittedAfter([
    { name: "h", sequence: "h" },
    { name: "i", sequence: "i" },
    { name: "tab", sequence: "\t" },
  ]);
  expect(text).toBe("hi"); // no trailing control byte got submitted
});

test("unhandled special keys never leak control/escape bytes into the input", async () => {
  const text = await submittedAfter([
    { name: "a", sequence: "a" },
    { name: "home", sequence: "\u001b[H" }, // ESC sequence from an unhandled key
    { name: "b", sequence: "b" },
  ]);
  expect(text).toBe("ab");
});

test("normal printable typing (incl. space) is unaffected", async () => {
  const text = await submittedAfter(
    [..."hello world"].map((c) => ({ name: c === " " ? "space" : c, sequence: c })),
  );
  expect(text).toBe("hello world");
});

async function pastedThenSubmitted(text) {
  const { renderer, sent } = await setupComposer();
  renderer.keyInput.emit("paste", { bytes: new TextEncoder().encode(text) });
  renderer.keyInput.emit("keypress", { name: "return" });
  const submitted = sent.find((m) => m.type === "input.submit")?.text;
  renderer.destroy?.();
  return submitted;
}

test("pasted ANSI/terminal output is stripped of escape and control bytes", async () => {
  const submitted = await pastedThenSubmitted("a\u001b[31mred\u001b[0m b");
  expect(submitted).toBe("ared b"); // colors removed
  expect(submitted.includes("\u001b")).toBe(false); // no raw control bytes submitted
});

test("paste preserves newlines and tabs (multi-line / indented paste)", async () => {
  const submitted = await pastedThenSubmitted("line1\nline2\tindented");
  expect(submitted).toBe("line1\nline2\tindented");
});

const ctrl = (name) => ({ name, ctrl: true });
const typed = (s) => [...s].map((c) => ({ name: c === " " ? "space" : c, sequence: c }));

test("Ctrl+A/Ctrl+E jump to the start/end of the line", async () => {
  // Ctrl+A moves to line start (the inserted X lands first)...
  expect(await submittedAfter([...typed("hello"), ctrl("a"), { name: "X", sequence: "X" }])).toBe("Xhello");
  // ...and Ctrl+E moves back to the end.
  expect(
    await submittedAfter([...typed("hello"), ctrl("a"), ctrl("e"), { name: "!", sequence: "!" }]),
  ).toBe("hello!");
});

test("Ctrl+W and Alt+Backspace delete the previous word", async () => {
  expect(await submittedAfter([...typed("hello world"), ctrl("w")])).toBe("hello ");
  expect(await submittedAfter([...typed("foo bar"), { name: "backspace", meta: true }])).toBe("foo ");
});

test("Ctrl+U cuts to line start and Ctrl+K cuts to line end", async () => {
  expect(await submittedAfter([...typed("hello world"), ctrl("u")])).toBe("");
  expect(await submittedAfter([...typed("hello world"), ctrl("a"), ctrl("k")])).toBe("");
});

test("line editing acts on the current line in a multi-line draft", async () => {
  // Alt+Enter inserts a newline; Ctrl+A then goes to the start of the SECOND line.
  const keys = [
    ...typed("ab"),
    { name: "return", meta: true },
    ...typed("cd"),
    ctrl("a"),
    { name: "X", sequence: "X" },
  ];
  expect(await submittedAfter(keys)).toBe("ab\nXcd");
});

const alt = (name) => ({ name, meta: true });

test("Ctrl+Left / Ctrl+Right move the caret by word", async () => {
  const X = { name: "X", sequence: "X" };
  // From the end, Ctrl+Left lands at the start of "bar".
  expect(await submittedAfter([...typed("foo bar"), ctrl("left"), X])).toBe("foo Xbar");
  // Twice lands at the start of "foo".
  expect(await submittedAfter([...typed("foo bar"), ctrl("left"), ctrl("left"), X])).toBe("Xfoo bar");
  // From the start (Ctrl+A), Ctrl+Right lands at the end of "foo".
  expect(await submittedAfter([...typed("foo bar"), ctrl("a"), ctrl("right"), X])).toBe("fooX bar");
});

test("Alt+B / Alt+F also move the caret by word", async () => {
  const X = { name: "X", sequence: "X" };
  expect(await submittedAfter([...typed("foo bar"), alt("b"), X])).toBe("foo Xbar");
  expect(await submittedAfter([...typed("foo bar"), ctrl("a"), alt("f"), X])).toBe("fooX bar");
});

test("plain Left still moves a single character (word movement needs a modifier)", async () => {
  expect(await submittedAfter([...typed("abc"), { name: "left" }, { name: "X", sequence: "X" }])).toBe("abXc");
});

test("the Delete key forward-deletes the character at the caret", async () => {
  // Ctrl+A to the start, then Delete removes the first character.
  expect(await submittedAfter([...typed("abc"), ctrl("a"), { name: "delete" }])).toBe("bc");
  // Delete at the end of the input is a no-op.
  expect(await submittedAfter([...typed("abc"), { name: "delete" }])).toBe("abc");
});

test("Alt+D and Ctrl+Delete delete the next word", async () => {
  expect(await submittedAfter([...typed("foo bar"), ctrl("a"), alt("d")])).toBe(" bar");
  expect(await submittedAfter([...typed("foo bar"), ctrl("a"), { name: "delete", ctrl: true }])).toBe(" bar");
});

// Vertical (Up/Down) caret movement tracks the DISPLAY-CELL column, so the caret
// keeps its visual column across lines that mix narrow and wide (CJK) glyphs, and
// preserves a goal column through short intervening lines (finding #5). nl inserts
// a newline without submitting (Alt/Option+Return).
const nl = { name: "return", meta: true };

test("Up keeps the visual column on an all-ASCII draft (regression)", async () => {
  // "abcdef" / "ghijkl": from after "ghij" (col 4) Up lands after "abcd".
  expect(
    await submittedAfter([
      ...typed("abcdef"), nl, ...typed("ghijkl"),
      { name: "left" }, { name: "left" }, { name: "up" }, ...typed("X"),
    ]),
  ).toBe("abcdXef\nghijkl");
});

test("Up into a wide (CJK) line lands at the visual column, not the char index", async () => {
  // "你好world" / "abcdefgh": from visual col 5 on the ASCII line, Up must land
  // after "你好w" (你=2 + 好=2 + w=1 = col 5) -> "你好wXorld", NOT the char-index-5
  // result "你好worXld".
  expect(
    await submittedAfter([
      ...typed("你好world"), nl, ...typed("abcdefgh"),
      { name: "left" }, { name: "left" }, { name: "left" }, // col 8 -> col 5
      { name: "up" }, ...typed("X"),
    ]),
  ).toBe("你好wXorld\nabcdefgh");
});

test("Down into a wide (CJK) line keeps the visual column", async () => {
  // "abcdefgh" / "你好world": from col 5 on the ASCII line, Down lands after "你好w".
  expect(
    await submittedAfter([
      ...typed("abcdefgh"), nl, ...typed("你好world"),
      { name: "up" }, // -> line 0 (goal 9 clamps to end, col 8)
      { name: "left" }, { name: "left" }, { name: "left" }, // -> col 5, resets goal
      { name: "down" }, ...typed("X"),
    ]),
  ).toBe("abcdefgh\n你好wXorld");
});

test("the goal column is preserved across a short intervening line", async () => {
  // "abcdefgh" / "你好" / "ABCDEFGH": from col 7 on line 0, Down through the short
  // wide line "你好" (width 4) returns to col 7 on line 2 -> "ABCDEFGXH".
  expect(
    await submittedAfter([
      ...typed("abcdefgh"), nl, ...typed("你好"), nl, ...typed("ABCDEFGH"),
      { name: "up" }, { name: "up" }, // -> line 0 end (col 8), goal seeded 8
      { name: "left" }, // -> col 7, resets goal
      { name: "down" }, { name: "down" }, // through "你好" (clamps) back to col 7 on line 2
      ...typed("X"),
    ]),
  ).toBe("abcdefgh\n你好\nABCDEFGXH");
});
