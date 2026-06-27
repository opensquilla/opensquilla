import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptCompletionText,
  filterCatalog,
  menuKeyAction,
  shouldDropResponse,
  shouldTriggerMenu,
  tokenUnderCaret,
} from "./composer.mjs";
import { createDispatcher } from "./ipc.mjs";

test("tokenUnderCaret returns the token before the caret and its start index", () => {
  assert.deepEqual(tokenUnderCaret("/cmp", 4), { token: "/cmp", start: 0 });
  assert.deepEqual(tokenUnderCaret("ask @src/foo", 12), {
    token: "@src/foo",
    start: 4,
  });
  assert.deepEqual(tokenUnderCaret("one\n/resume", 11), {
    token: "/resume",
    start: 4,
  });
  assert.deepEqual(tokenUnderCaret("trail space ", 12), { token: "", start: 12 });
});

test("shouldTriggerMenu allows slash only at line start and files anywhere", () => {
  assert.deepEqual(shouldTriggerMenu("/cmp", 0, true), {
    active: true,
    kind: "slash",
    query: "cmp",
  });
  assert.deepEqual(shouldTriggerMenu("/cmp", 6, false), {
    active: false,
    kind: null,
    query: "",
  });
  assert.deepEqual(shouldTriggerMenu("@src/fo", 4, false), {
    active: true,
    kind: "file",
    query: "src/fo",
  });
  assert.deepEqual(shouldTriggerMenu("plain", 0, true), {
    active: false,
    kind: null,
    query: "",
  });
});

test("filterCatalog ranks subsequence matches predictably", () => {
  const catalog = [
    { label: "/compress", description: "compress", insert_text: "/compress " },
    { label: "/compact", description: "compact", insert_text: "/compact " },
    { label: "/resume", description: "resume", insert_text: "/resume " },
    { label: "/reset", description: "reset", insert_text: "/reset " },
  ];

  assert.equal(filterCatalog(catalog, "cmp")[0].label, "/compact");
  assert.deepEqual(
    filterCatalog(catalog, "re").map((item) => item.label).slice(0, 2),
    ["/reset", "/resume"],
  );
  assert.deepEqual(filterCatalog(catalog, "").map((item) => item.label), [
    "/compress",
    "/compact",
    "/resume",
    "/reset",
  ]);
});

test("filterCatalog prefers command-name prefixes over later path segments", () => {
  const catalog = [
    { label: "/audio-cog", description: "skill", insert_text: "/audio-cog " },
    { label: "/html-coder", description: "skill", insert_text: "/html-coder " },
    { label: "/compact", description: "command", insert_text: "/compact " },
    { label: "/cost", description: "command", insert_text: "/cost " },
  ];

  assert.deepEqual(
    filterCatalog(catalog, "co").map((item) => item.label).slice(0, 2),
    ["/cost", "/compact"],
  );
});

test("acceptCompletionText replaces the active token with insert text", () => {
  assert.deepEqual(acceptCompletionText("/cmp", 0, 4, "/compact "), {
    text: "/compact ",
    cursor: 9,
  });
  assert.deepEqual(acceptCompletionText("查看 @文", 3, 5, "@文档.md "), {
    text: "查看 @文档.md ",
    cursor: 10,
  });
});

test("shouldDropResponse rejects stale completion responses", () => {
  assert.equal(shouldDropResponse(2, 3), true);
  assert.equal(shouldDropResponse(3, 3), false);
});

test("menuKeyAction handles menu navigation before submit and cancel keys", () => {
  const menu = {
    active: true,
    selected: 1,
    filtered: [{ label: "a" }, { label: "b" }],
  };

  assert.deepEqual(menuKeyAction(menu, "up"), {
    handled: true,
    action: "navigate",
    menu: { ...menu, selected: 0 },
  });
  assert.deepEqual(menuKeyAction(menu, "down"), {
    handled: true,
    action: "navigate",
    menu: { ...menu, selected: 1 },
  });
  assert.deepEqual(menuKeyAction(menu, "escape"), {
    handled: true,
    action: "close",
    menu: { ...menu, active: false },
  });
  assert.deepEqual(menuKeyAction(menu, "return").action, "accept");
  assert.deepEqual(menuKeyAction(menu, "tab").action, "accept");
  assert.equal(menuKeyAction(menu, "backspace").handled, false);
});

test("ipc dispatcher routes completion responses", () => {
  let seen = null;
  const dispatch = createDispatcher({
    completionResponse: (message) => {
      seen = message;
    },
    unknown: () => {},
  });

  dispatch({ type: "completion.response", request_id: 7, kind: "file", items: [] });

  assert.deepEqual(seen, {
    type: "completion.response",
    request_id: 7,
    kind: "file",
    items: [],
  });
});
