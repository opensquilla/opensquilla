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

test("start() survives a malformed inbound line, reports it, and keeps dispatching", async () => {
  const base = path.join(os.tmpdir(), `ipc-start-test-${process.pid}-${Math.random().toString(36).slice(2)}`);
  const inPath = `${base}.in`;
  const outPath = `${base}.out`;
  fs.writeFileSync(inPath, 'not json\n{"type":"ready"}\n');
  const rfd = fs.openSync(inPath, "r");
  const wfd = fs.openSync(outPath, "w");
  const ipc = createIpc({ fromFd: rfd, toFd: wfd });
  const seen = [];
  await new Promise((resolve) => ipc.start((m) => seen.push(m), resolve));
  fs.closeSync(wfd);
  // The valid line after the garbage still dispatched — the host survived.
  assert.deepEqual(seen, [{ type: "ready" }]);
  // The parse failure was reported back to Python instead of crashing.
  const written = fs.readFileSync(outPath, "utf8").trim().split("\n").map((line) => JSON.parse(line));
  assert.equal(written.length, 1);
  assert.equal(written[0].type, "error");
  try { fs.closeSync(rfd); } catch { /* already closed */ }
  try { fs.unlinkSync(inPath); fs.unlinkSync(outPath); } catch { /* best effort */ }
});

test("start() routes a read-stream error to onClose so the host can tear down", async () => {
  // A dead read fd (e.g. a parent-less launch) emits 'error', never 'close';
  // it must take the same clean shutdown path as EOF instead of wedging the
  // full-screen UI alive. Grab-and-close an fd so the number is known-invalid.
  const probe = fs.openSync("/dev/null", "r");
  fs.closeSync(probe);
  const { start } = createIpc({ fromFd: probe, toFd: probe });
  const closed = new Promise((resolve) => start(() => {}, () => resolve(true)));
  const timeout = new Promise((resolve) => setTimeout(resolve, 2000, false));
  assert.equal(await Promise.race([closed, timeout]), true);
});
