// Render representative conversation frames through the REAL UI modules and
// print them as plain text — a fast visual feedback loop for aesthetic work
// without a terminal session or a model. Not a test: run it directly.
//
//   bun scripts/gallery.mjs            # default 100x34
//   bun scripts/gallery.mjs 80 30      # custom size
import { createTestRenderer } from "@opentui/core/testing";
import {
  BoxRenderable,
  MarkdownRenderable,
  ScrollBoxRenderable,
  SyntaxStyle,
  TextRenderable,
} from "@opentui/core";

import { createComposer } from "../src/composer.mjs";
import { createTurnFlow, createTurnView } from "../src/turnView.mjs";
import { clampFooterHeight } from "../src/primitives.mjs";
import { registerThemeStyles } from "../src/syntaxTheme.mjs";
import { applyTheme, THEME } from "../src/theme.mjs";

const width = Number(process.argv[2] ?? 100);
const height = Number(process.argv[3] ?? 34);
const themeName = process.env.OPENSQUILLA_TUI_THEME ?? "opensquilla-dark";

applyTheme(themeName);

const FOOTER_HEIGHT = 6;
const footerRows = clampFooterHeight(FOOTER_HEIGHT, height);

const setup = await createTestRenderer({ width, height });
const { renderer, renderOnce, captureCharFrame } = setup;

const syntaxStyle = SyntaxStyle.create();
registerThemeStyles(syntaxStyle, THEME);

const conversationBox = new ScrollBoxRenderable(renderer, {
  id: "conversation",
  position: "absolute",
  left: 0,
  top: 0,
  right: 0,
  height: Math.max(1, height - footerRows),
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
  height: footerRows,
  backgroundColor: THEME.footerBg,
});
renderer.root.add(inputBox);

const overlayLayer = new BoxRenderable(renderer, {
  id: "overlay-layer",
  position: "absolute",
  left: 0,
  top: 0,
  right: 0,
  bottom: 0,
  zIndex: 1000,
  shouldFill: false,
  visible: false,
});
renderer.root.add(overlayLayer);

const sent = [];
const composer = createComposer({
  renderer,
  BoxRenderable,
  TextRenderable,
  conversationBox,
  inputBox,
  overlayLayer,
  footerHeight: FOOTER_HEIGHT,
  sendHostMessage: (m) => sent.push(m),
});
composer.install();

const turnDeps = {
  renderer,
  BoxRenderable,
  TextRenderable,
  MarkdownRenderable,
  syntaxStyle,
  conversationBox,
};
let seq = 0;
const flow = createTurnFlow((id) => createTurnView(turnDeps, id ?? seq++));

// ---- drive a representative session ----------------------------------------
const scenario = process.argv[4] ?? "full";

function promptEcho(text) {
  const turn = flow.ensure();
  turn.begin(`prompt-${seq++}`, "prompt", { text });
}

if (scenario === "full") {
  // Turn 1: prompt -> narration -> tools -> markdown answer -> usage.
  promptEcho("hello");
  const t1 = flow.ensure();
  t1.begin("r1", "reasoning", {});
  t1.end("r1");
  t1.begin("n1", "thinking", {});
  t1.append("n1", "Taking a quick look at the workspace before answering.");
  t1.end("n1");
  t1.begin("tool1", "tool", { name: "list_dir", args_summary: "/workspace/opensquilla" });
  t1.append("tool1", "src\ntests\npyproject.toml");
  t1.update("tool1", { status: "ok", duration: "0.2s" });
  t1.end("tool1");
  t1.begin("tool2", "tool", { name: "read_file", args_summary: "pyproject.toml" });
  t1.update("tool2", { status: "ok", duration: "0.1s" });
  t1.end("tool2");
  t1.begin("a1", "answer", {});
  t1.append(
    "a1",
    "Hello! 👋 Here is what I found:\n\n" +
      "## Project layout\n\n" +
      "- `src/` — the runtime package\n" +
      "- `tests/` — the offline suite\n\n" +
      "Use `uv run pytest -q` to run everything locally.",
  );
  t1.end("a1");
  t1.begin("u1", "usage", { text: "in 9.4k / out 62 · 3.3s" });
  t1.end("u1");
  flow.endTurn(false);

  // Turn 2: a queued prompt waiting behind a running turn + a live tool.
  promptEcho("and what changed recently?");
  const t2 = flow.ensure();
  t2.begin("r2", "reasoning", {});
  t2.begin("tool3", "tool", { name: "exec_command", args_summary: "git log --oneline -5" });
  composer.setTurnStatus({ phase: "tool", label: "exec_command", active: true });
  composer.setRouterState({
    model: "openai/big-model",
    route: "c2 91%",
    saving: "62%",
    context: "12%",
    io: "34.6k/548",
  });
} else if (scenario === "reasoning") {
  promptEcho("prove the Collatz conjecture");
  const t = flow.ensure();
  t.begin("r1", "reasoning", {});
  t.append("r1", "The user asks for a proof of an open problem.\n");
  t.append("r1", "I should explain why no proof is known rather than invent one.\n");
  t.append("r1", "Let me survey what IS known: verified up to 2^68, Terras density results…\n");
  t.append("r1", "I will structure the answer around partial results and heuristics.\n");
  composer.setTurnStatus({ phase: "thinking", label: "thinking", active: true });
} else if (scenario === "idle") {
  composer.setTurnStatus({ phase: "idle", label: "ready", active: false });
}

// Markdown blocks parse asynchronously (tree-sitter); settle before capture.
for (let i = 0; i < 40; i += 1) {
  await renderOnce();
  await new Promise((resolve) => setTimeout(resolve, 5));
}
const frame = captureCharFrame();
console.log(`── ${themeName} · ${width}x${height} · ${scenario} ` + "─".repeat(Math.max(0, width - themeName.length - String(width).length - String(height).length - scenario.length - 12)));
console.log(frame);
console.log("─".repeat(width));
renderer.destroy?.();
process.exit(0);
