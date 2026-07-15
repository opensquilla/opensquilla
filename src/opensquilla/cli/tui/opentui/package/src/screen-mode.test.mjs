import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ALTERNATE_SCREEN,
  assertRendererScreenMode,
  rendererLayoutHeight,
  rendererOptions,
} from "./screenMode.mjs";

test("the host has one fixed alternate-screen renderer contract", () => {
  assert.deepEqual(rendererOptions(), {
    screenMode: ALTERNATE_SCREEN,
    useMouse: true,
  });
  assertRendererScreenMode({ screenMode: ALTERNATE_SCREEN });
  assert.throws(
    () => assertRendererScreenMode({ screenMode: "main-screen" }),
    /screen mode mismatch/,
  );
});

test("renderer layout height follows the owned alternate-screen viewport", () => {
  assert.equal(rendererLayoutHeight({ height: 30, terminalHeight: 30 }), 30);
  assert.equal(rendererLayoutHeight({ terminalHeight: 24 }), 24);
  assert.equal(rendererLayoutHeight({}), 1);
});
