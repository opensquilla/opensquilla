import assert from "node:assert/strict";
import test from "node:test";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { createIpc } from "./ipc.mjs";

// Create a real OS pipe (FIFO) and return its read/write fds. The write end is
// blocking, matching how Python wires the host pipe via os.pipe()/pass_fds.
function openFifo() {
  const fifo = path.join(os.tmpdir(), `ipc-send-test-${process.pid}-${Math.random().toString(36).slice(2)}`);
  execSync(`mkfifo ${fifo}`);
  const rfd = fs.openSync(fifo, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);
  const wfd = fs.openSync(fifo, fs.constants.O_WRONLY);
  return { fifo, rfd, wfd };
}

test("send() does not throw when the read end of the pipe is closed (EPIPE)", () => {
  const { fifo, rfd, wfd } = openFifo();
  const { send } = createIpc({ fromFd: rfd, toFd: wfd });
  // Drop the reader so the kernel reports EPIPE once the pipe buffer fills.
  fs.closeSync(rfd);
  assert.doesNotThrow(() => {
    // Enough writes to exceed the pipe buffer and force a real EPIPE.
    for (let i = 0; i < 50000; i++) send({ type: "pulse", i, pad: "x".repeat(200) });
  });
  try { fs.closeSync(wfd); } catch { /* already gone */ }
  try { fs.unlinkSync(fifo); } catch { /* best effort */ }
});

test("send() does not throw when the destination fd is already closed (EBADF)", () => {
  const { fifo, rfd, wfd } = openFifo();
  const { send } = createIpc({ fromFd: rfd, toFd: wfd });
  fs.closeSync(rfd);
  fs.closeSync(wfd);
  assert.doesNotThrow(() => send({ type: "resize", width: 80, height: 24 }));
  try { fs.unlinkSync(fifo); } catch { /* best effort */ }
});

test("send() does not throw on an unserializable (circular) payload", () => {
  const { fifo, rfd, wfd } = openFifo();
  const { send } = createIpc({ fromFd: rfd, toFd: wfd });
  const circular = {};
  circular.self = circular;
  assert.doesNotThrow(() => send({ type: "error", circular }));
  try { fs.closeSync(rfd); fs.closeSync(wfd); fs.unlinkSync(fifo); } catch { /* best effort */ }
});

test("send() still writes a complete line on the normal path", async () => {
  const { fifo, rfd, wfd } = openFifo();
  fs.closeSync(rfd); // we read via `cat` in a child to keep the pipe drained
  const out = `${fifo}.out`;
  const { spawn } = await import("node:child_process");
  const reader = spawn("sh", ["-c", `cat ${fifo} > ${out}`]);
  await new Promise((r) => setTimeout(r, 50));
  const { send } = createIpc({ fromFd: 0, toFd: wfd });
  send({ type: "ready" });
  send({ type: "resize", width: 80, height: 24 });
  fs.closeSync(wfd);
  await new Promise((r) => setTimeout(r, 150));
  reader.kill();
  const got = fs.readFileSync(out, "utf8");
  assert.equal(got, '{"type":"ready"}\n{"type":"resize","width":80,"height":24}\n');
  try { fs.unlinkSync(fifo); fs.unlinkSync(out); } catch { /* best effort */ }
});
