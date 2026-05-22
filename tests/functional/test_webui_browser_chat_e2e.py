"""Opt-in real-browser chat surface e2e without provider spend."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.webui_browser


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _npm() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _node() -> str:
    return "node.exe" if os.name == "nt" else "node"


def _install_playwright(work_dir: Path) -> None:
    result = subprocess.run(
        [_npm(), "--prefix", str(work_dir), "install", "playwright"],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _wait_for_health(port: int, server: subprocess.Popen[str]) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + 20.0
    last_error = ""
    while time.monotonic() < deadline:
        if server.poll() is not None:
            stdout = server.stdout.read() if server.stdout else ""
            stderr = server.stderr.read() if server.stderr else ""
            raise AssertionError(
                f"gateway exited early code={server.returncode}\nstdout={stdout}\nstderr={stderr}"
            )
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200 and response.json().get("ok") is True:
                return
        except Exception as exc:  # noqa: BLE001 - surfaced on timeout.
            last_error = str(exc)
        time.sleep(0.1)
    raise AssertionError(f"gateway did not become healthy: {last_error}")


def _stop_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def test_per_turn_bubble_chip_differs_across_turns_in_real_browser(tmp_path: Path) -> None:
    """P4-AC6: per-turn .msg-meta__tokens chip reflects per-turn token counts.

    Two synthetic turns are injected via the RPC event bus (no LLM spend).
    Turn 1 uses input_tokens=11; turn 2 uses input_tokens=19.  The test
    asserts that:
    - chip[0].input != chip[1].input  (per-turn semantics, values differ)
    - chip[1].input >= chip[0].input  (monotonic across a session with growing
      context, satisfied trivially because 19 > 11)
    """
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_bubble_server.py"
    browser_script = tmp_path / "webui_bubble_browser.js"
    server_script.write_text(
        textwrap.dedent(
            f"""
            import uvicorn

            from opensquilla.gateway.app import create_gateway_app
            from opensquilla.gateway.config import AuthConfig, GatewayConfig

            config = GatewayConfig(
                host="127.0.0.1",
                port={port},
                auth=AuthConfig(mode="none"),
            )
            app = create_gateway_app(config)

            if __name__ == "__main__":
                uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
            """
        ),
        encoding="utf-8",
    )
    browser_script.write_text(
        textwrap.dedent(
            r"""
            const { chromium } = require("playwright");

            // Inject a synthetic streaming turn into the chat JS event bus.
            // text_delta fires through the named listener; done fires through the
            // wildcard (*) listener which is how chat.js processes terminal events.
            async function injectTurn(page, inputTokens, outputTokens) {
              await page.evaluate(
                ({ inputTokens, outputTokens }) => {
                  const rpc = App.getRpc();
                  const ls = rpc._listeners;

                  // 1. text_delta — named listener — creates the stream bubble
                  const deltaHandlers = ls.get("session.event.text_delta");
                  if (deltaHandlers) {
                    deltaHandlers.forEach(h => h({ text: "hi" }));
                  }

                  // 2. session.event.done — wildcard (*) listener — attaches
                  //    the .msg-meta__tokens chip to the finished bubble
                  const wildHandlers = ls.get("*");
                  if (wildHandlers) {
                    wildHandlers.forEach(h =>
                      h("session.event.done", {
                        input_tokens: inputTokens,
                        output_tokens: outputTokens,
                        text: "hi",
                      })
                    );
                  }
                },
                { inputTokens, outputTokens }
              );
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });

              // Wait for WebSocket RPC connection (chat.js needs it to register listeners)
              await page.waitForFunction(
                () =>
                  typeof App !== "undefined" &&
                  App.getRpc &&
                  App.getRpc()?.state === "connected",
                { timeout: 15000 }
              );

              // Turn 1: input=11, output=5
              await injectTurn(page, 11, 5);
              await page.waitForSelector(".msg-meta__tokens", { timeout: 5000 });

              // Turn 2: input=19, output=7
              await injectTurn(page, 19, 7);
              // Wait for the second chip to appear
              await page.waitForFunction(
                () => document.querySelectorAll(".msg-meta__tokens").length >= 2,
                { timeout: 5000 }
              );

              const chips = await page.evaluate(() =>
                Array.from(document.querySelectorAll(".msg-meta__tokens")).map(el => el.textContent)
              );

              // Parse "↑X ↓Y" into { input: X, output: Y }
              function parseChip(text) {
                const m = text.match(/↑(\d+(?:\.\d+)?[KMk]?)\s*↓(\d+(?:\.\d+)?[KMk]?)/);
                if (!m) return null;
                function tok(s) {
                  const n = parseFloat(s);
                  if (s.endsWith("K") || s.endsWith("k")) return Math.round(n * 1000);
                  if (s.endsWith("M")) return Math.round(n * 1000000);
                  return n;
                }
                return { input: tok(m[1]), output: tok(m[2]) };
              }

              const parsed = chips.slice(0, 2).map(parseChip);
              const result = {
                chipCount: chips.length,
                chip0: parsed[0],
                chip1: parsed[1],
                pageErrors: errors,
              };
              await browser.close();
              console.log(JSON.stringify(result));
            })().catch(err => {
              console.error(err && err.stack ? err.stack : String(err));
              process.exit(1);
            });
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["OPENSQUILLA_STATE_DIR"] = str(tmp_path / "state")
    env["OPENSQUILLA_LOG_DIR"] = str(tmp_path / "logs")
    server = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_for_health(port, server)
        _install_playwright(tmp_path)
        result = subprocess.run(
            [_node(), str(browser_script)],
            cwd=tmp_path,
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/chat"),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload["pageErrors"] == [], payload["pageErrors"]
    assert payload["chipCount"] >= 2, f"expected >=2 chips, got {payload['chipCount']}"
    chip0 = payload["chip0"]
    chip1 = payload["chip1"]
    assert chip0 is not None, "chip0 did not parse"
    assert chip1 is not None, "chip1 did not parse"
    # Per-turn semantics: each bubble shows the tokens for that turn, not the
    # session accumulator, so consecutive turns with different token counts must
    # produce different chip values.
    assert chip0["input"] != chip1["input"], (
        f"chip input_tokens should differ between turns: chip0={chip0}, chip1={chip1}"
    )
    # Monotonic: second turn's per-turn input >= first turn's (19 > 11 by construction)
    assert chip1["input"] >= chip0["input"], (
        f"chip1.input ({chip1['input']}) should be >= chip0.input ({chip0['input']})"
    )


def test_chat_view_loads_and_reaches_gateway_http_status_in_real_browser(tmp_path: Path) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_chat_server.py"
    browser_script = tmp_path / "webui_chat_browser.js"
    server_script.write_text(
        textwrap.dedent(
            f"""
            import uvicorn

            from opensquilla.gateway.app import create_gateway_app
            from opensquilla.gateway.config import AuthConfig, GatewayConfig

            config = GatewayConfig(
                host="127.0.0.1",
                port={port},
                auth=AuthConfig(mode="none"),
            )
            app = create_gateway_app(config)

            if __name__ == "__main__":
                uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
            """
        ),
        encoding="utf-8",
    )
    browser_script.write_text(
        textwrap.dedent(
            """
            const { chromium } = require("playwright");

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));
              const response = await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              const status = await page.evaluate(async () => {
                const res = await fetch("/api/system/status");
                return await res.json();
              });
              const bodyText = await page.locator("body").innerText();
              const result = {
                statusCode: response ? response.status() : 0,
                title: await page.title(),
                textareaCount: await page.locator("#chat-textarea").count(),
                sendButtonCount: await page.locator("#chat-btn-send").count(),
                activeChatNav: await page.locator('.nav-item.is-active[data-path="/chat"]').count(),
                gatewayStatus: status.status,
                authMode: status.auth_mode,
                hasRemovedToolName:
                  bodyText.includes("generate_image") ||
                  bodyText.includes("spawn_subagent") ||
                  bodyText.includes("send_message"),
                pageErrors: errors,
              };
              await browser.close();
              console.log(JSON.stringify(result));
            })().catch(err => {
              console.error(err && err.stack ? err.stack : String(err));
              process.exit(1);
            });
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["OPENSQUILLA_STATE_DIR"] = str(tmp_path / "state")
    env["OPENSQUILLA_LOG_DIR"] = str(tmp_path / "logs")
    server = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_for_health(port, server)
        _install_playwright(tmp_path)
        result = subprocess.run(
            [_node(), str(browser_script)],
            cwd=tmp_path,
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/chat"),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload == {
        "statusCode": 200,
        "title": "OpenSquilla Control",
        "textareaCount": 1,
        "sendButtonCount": 1,
        "activeChatNav": 1,
        "gatewayStatus": "running",
        "authMode": "none",
        "hasRemovedToolName": False,
        "pageErrors": [],
    }


def test_chat_compaction_events_render_recoverable_toasts_in_real_browser(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_chat_compaction_server.py"
    browser_script = tmp_path / "webui_chat_compaction_browser.js"
    server_script.write_text(
        textwrap.dedent(
            f"""
            import uvicorn

            from opensquilla.gateway.app import create_gateway_app
            from opensquilla.gateway.config import AuthConfig, GatewayConfig

            config = GatewayConfig(
                host="127.0.0.1",
                port={port},
                auth=AuthConfig(mode="none"),
            )
            app = create_gateway_app(config)

            if __name__ == "__main__":
                uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
            """
        ),
        encoding="utf-8",
    )
    browser_script.write_text(
        textwrap.dedent(
            r"""
            const { chromium } = require("playwright");

            async function emitCompaction(page, payload, meta = {}) {
              await page.evaluate(
                ({ payload, meta }) => {
                  const rpc = App.getRpc();
                  const handlers = rpc._listeners.get("session.event.compaction");
                  if (handlers) {
                    handlers.forEach(h => h(payload, meta));
                  }
                },
                { payload, meta }
              );
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.waitForFunction(
                () =>
                  typeof App !== "undefined" &&
                  App.getRpc &&
                  App.getRpc()?.state === "connected",
                { timeout: 15000 }
              );

              await emitCompaction(page, { status: "started", source: "manual" });
              await emitCompaction(page, { status: "skipped", source: "manual" });
              await page.waitForTimeout(250);

              await emitCompaction(page, {
                status: "completed",
                source: "manual",
                tokens_before: 3500,
                tokens_after: 1300,
              });
              await page.waitForFunction(
                () => document.body.innerText.includes("Context compacted"),
                { timeout: 5000 }
              );

              await emitCompaction(
                page,
                { status: "failed", source: "manual", message: "old replay" },
                { replayed: true }
              );
              await page.waitForTimeout(250);

              const bodyText = await page.locator("body").innerText();
              const result = {
                hasStartedToast: bodyText.includes("Checking whether compaction is needed..."),
                hasSkippedToast: bodyText.includes("No compaction needed"),
                hasCompletedToast: bodyText.includes("Context compacted"),
                hasReplayedFailureToast: bodyText.includes("old replay"),
                pageErrors: errors,
              };
              await browser.close();
              console.log(JSON.stringify(result));
            })().catch(err => {
              console.error(err && err.stack ? err.stack : String(err));
              process.exit(1);
            });
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["OPENSQUILLA_STATE_DIR"] = str(tmp_path / "state")
    env["OPENSQUILLA_LOG_DIR"] = str(tmp_path / "logs")
    server = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_for_health(port, server)
        _install_playwright(tmp_path)
        result = subprocess.run(
            [_node(), str(browser_script)],
            cwd=tmp_path,
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/chat"),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload == {
        "hasStartedToast": False,
        "hasSkippedToast": False,
        "hasCompletedToast": True,
        "hasReplayedFailureToast": False,
        "pageErrors": [],
    }


def test_webui_hotfix_flows_in_real_browser(tmp_path: Path) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_hotfix_server.py"
    browser_script = tmp_path / "webui_hotfix_browser.js"
    server_script.write_text(
        textwrap.dedent(
            f"""
            import uvicorn

            from opensquilla.gateway.app import create_gateway_app
            from opensquilla.gateway.config import AuthConfig, GatewayConfig

            config = GatewayConfig(
                host="127.0.0.1",
                port={port},
                auth=AuthConfig(mode="none"),
            )
            app = create_gateway_app(config)

            if __name__ == "__main__":
                uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
            """
        ),
        encoding="utf-8",
    )
    browser_script.write_text(
        textwrap.dedent(
            r"""
            const { chromium } = require("playwright");

            async function waitRpc(page) {
              await page.waitForFunction(
                () =>
                  typeof App !== "undefined" &&
                  App.getRpc &&
                  App.getRpc()?.state === "connected",
                { timeout: 15000 }
              );
            }

            async function emit(page, event, payload) {
              await page.evaluate(
                ({ event, payload }) => {
                  const rpc = App.getRpc();
                  const named = rpc._listeners.get(event);
                  if (named) named.forEach(h => h(payload));
                  const wild = rpc._listeners.get("*");
                  if (wild) wild.forEach(h => h(event, payload));
                },
                { event, payload }
              );
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await waitRpc(page);

              await page.evaluate(() => {
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                window.__hotfix = {
                  chatCalls: [],
                  channelStatusCalls: 0,
                  delayNextWait: false,
                  logInFlight: 0,
                  logMaxInFlight: 0,
                  logTailCalls: 0,
                };
                const originalWait = rpc.waitForConnection.bind(rpc);
                rpc.waitForConnection = () => {
                  if (!window.__hotfix.delayNextWait) return originalWait();
                  window.__hotfix.delayNextWait = false;
                  return new Promise(resolve => setTimeout(resolve, 300));
                };
                rpc.call = (method, params = {}) => {
                  if (method === "chat.send") {
                    window.__hotfix.chatCalls.push({ method, params });
                    return Promise.resolve({ task_id: "task-" + window.__hotfix.chatCalls.length });
                  }
                  if (method === "sessions.list") {
                    return Promise.resolve({
                      sessions: [{
                        key: "fake-session",
                        title: "Fake session",
                        updated_at: new Date().toISOString(),
                        message_count: 1,
                      }],
                    });
                  }
                  if (method === "agents.list") {
                    return Promise.resolve({ agents: [] });
                  }
                  if (method === "sessions.delete") {
                    return Promise.resolve({ deleted: [], errors: ["denied"] });
                  }
                  if (method === "channels.status") {
                    window.__hotfix.channelStatusCalls += 1;
                    return Promise.resolve({ channels: [] });
                  }
                  if (method === "logs.status") {
                    return Promise.resolve({ enabled: true, path: "debug.log" });
                  }
                  if (method === "logs.tail") {
                    const callNo = ++window.__hotfix.logTailCalls;
                    window.__hotfix.logInFlight += 1;
                    window.__hotfix.logMaxInFlight = Math.max(
                      window.__hotfix.logMaxInFlight,
                      window.__hotfix.logInFlight
                    );
                    return new Promise((resolve, reject) => {
                      const delay = callNo === 1 ? 200 : 4500;
                      setTimeout(() => {
                        window.__hotfix.logInFlight -= 1;
                        if (callNo === 1) {
                          reject(new Error("tail down"));
                          return;
                        }
                        resolve({
                          cursor: callNo,
                          lines: [{ level: "INFO", message: "log line " + callNo }],
                        });
                      }, delay);
                    });
                  }
                  return originalCall(method, params);
                };
              });

              const sessionKey = await page.locator("#chat-session-chip-key").innerText();
              await emit(
                page,
                "task.queued",
                { task_id: "old-task", session_key: "other-session" }
              );
              const statusAfterOtherTask = await page.locator("#chat-run-status").innerText();
              await emit(page, "task.queued", { task_id: "current-task", session_key: sessionKey });
              const statusAfterCurrentTask = await page.locator("#chat-run-status").innerText();
              await emit(page, "sessions.changed", {
                key: sessionKey,
                run_status: "idle",
                last_task: { status: "succeeded" },
                reason: "turn_complete",
              });

              await page.fill("#chat-textarea", "first prompt");
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () => window.__hotfix.chatCalls.some(c => c.params.message === "first prompt"),
                { timeout: 5000 }
              );
              await emit(page, "session.event.done", { text: "first answer" });
              await page.waitForFunction(
                () => document.querySelectorAll(".msg.assistant").length >= 1,
                { timeout: 5000 }
              );

              await page.fill("#chat-textarea", "second prompt");
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () => window.__hotfix.chatCalls.some(c => c.params.message === "second prompt"),
                { timeout: 5000 }
              );
              await emit(page, "session.event.done", { text: "second answer" });
              await page.waitForFunction(
                () => document.querySelectorAll(".msg.assistant").length >= 2,
                { timeout: 5000 }
              );

              await page.locator(".msg.assistant").first().hover();
              await page.locator(".msg.assistant")
                .first()
                .locator('[data-action="regenerate"]')
                .click();
              await page.waitForFunction(
                () =>
                  window.__hotfix.chatCalls
                    .filter(c => c.params.message === "first prompt")
                    .length >= 2,
                { timeout: 5000 }
              );
              const regenerateMessages = await page.evaluate(
                () => window.__hotfix.chatCalls.map(c => c.params.message)
              );
              const bubblesAfterRegenerate = await page.locator(".msg").count();

              await page.fill("#chat-textarea", "queued while streaming");
              await page.click("#chat-btn-send");
              await page.fill("#chat-textarea", "draft typed during stream");
              await emit(page, "session.event.done", { text: "regenerated answer" });
              await page.waitForFunction(
                () =>
                  window.__hotfix.chatCalls
                    .some(c => c.params.message === "queued while streaming"),
                { timeout: 5000 }
              );
              const draftAfterQueueDrain = await page.locator("#chat-textarea").inputValue();

              await page.evaluate(() => Router.navigate("/config"));
              await page.waitForSelector("#cfg-yaml-area", { state: "attached", timeout: 15000 });
              await page.click('[data-cfg-mode="yaml"]');
              const yamlBefore = await page.locator("#cfg-yaml-area").inputValue();
              const yamlDraft = yamlBefore + "\n# hotfix draft";
              await page.fill("#cfg-yaml-area", yamlDraft);
              await page.click('[data-cfg-mode="form"]');
              await page.click('[data-cfg-mode="yaml"]');
              const yamlAfterToggle = await page.locator("#cfg-yaml-area").inputValue();
              await page.evaluate(() => Router.navigate("/chat"));
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.evaluate(() => Router.navigate("/config"));
              await page.waitForSelector("#cfg-yaml-area", { state: "attached", timeout: 15000 });
              const configFormDisplay = await page
                .locator("#cfg-form-view")
                .evaluate(el => getComputedStyle(el).display);
              const configYamlDisplay = await page
                .locator("#cfg-yaml-view")
                .evaluate(el => getComputedStyle(el).display);
              const formButtonActive = await page
                .locator('[data-cfg-mode="form"]')
                .evaluate(el => el.classList.contains("is-active"));

              await page.evaluate(() => {
                window.__hotfix.delayNextWait = true;
                window.__hotfix.channelGuardStartedAt = Date.now();
                Router.navigate("/channels");
                Router.navigate("/chat");
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.waitForFunction(
                () =>
                  window.__hotfix.channelStatusCalls === 0 &&
                  Date.now() - window.__hotfix.channelGuardStartedAt >= 600,
                { timeout: 2000 }
              );
              const channelStatusCallsAfterDestroyedWait = await page.evaluate(
                () => window.__hotfix.channelStatusCalls
              );

              await page.evaluate(() => Router.navigate("/sessions"));
              await page.waitForSelector('[data-del-key="fake-session"]', { timeout: 15000 });
              await page.click('[data-del-key="fake-session"]');
              await page.locator(".modal .btn-danger").click();
              await page.waitForFunction(
                () => document.body.innerText.includes("Delete failed: denied"),
                { timeout: 5000 }
              );
              const sessionDeleteBody = await page.locator("body").innerText();

              await page.evaluate(() => Router.navigate("/logs"));
              await page.waitForSelector("#logs-display", { timeout: 15000 });
              await page.waitForFunction(
                () => document.body.innerText.includes("Log refresh failed"),
                { timeout: 5000 }
              );
              await page.waitForFunction(
                () => window.__hotfix.logTailCalls >= 2 && window.__hotfix.logInFlight === 0,
                { timeout: 10000 }
              );
              const logState = await page.evaluate(() => ({
                maxInFlight: window.__hotfix.logMaxInFlight,
                tailCalls: window.__hotfix.logTailCalls,
              }));

              const result = {
                statusAfterOtherTask,
                statusAfterCurrentTask,
                regenerateMessages,
                bubblesAfterRegenerate,
                draftAfterQueueDrain,
                yamlDraftPreserved: yamlAfterToggle === yamlDraft,
                configResetToForm:
                  configFormDisplay !== "none" &&
                  configYamlDisplay === "none" &&
                  formButtonActive,
                channelStatusCallsAfterDestroyedWait,
                sessionDeleteFailed: sessionDeleteBody.includes("Delete failed: denied"),
                sessionDeleteFalseSuccess: sessionDeleteBody.includes("Session deleted"),
                logState,
                pageErrors: errors,
              };
              await browser.close();
              console.log(JSON.stringify(result));
            })().catch(err => {
              console.error(err && err.stack ? err.stack : String(err));
              process.exit(1);
            });
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["OPENSQUILLA_STATE_DIR"] = str(tmp_path / "state")
    env["OPENSQUILLA_LOG_DIR"] = str(tmp_path / "logs")
    server = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_for_health(port, server)
        _install_playwright(tmp_path)
        result = subprocess.run(
            [_node(), str(browser_script)],
            cwd=tmp_path,
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/chat"),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload["pageErrors"] == [], payload["pageErrors"]
    assert payload["statusAfterOtherTask"] == "Idle"
    assert payload["statusAfterCurrentTask"] == "Queued"
    assert payload["regenerateMessages"].count("first prompt") >= 2
    first_regenerate = payload["regenerateMessages"].index("first prompt")
    second_send = payload["regenerateMessages"].index("second prompt")
    assert first_regenerate < second_send
    assert payload["bubblesAfterRegenerate"] <= 3
    assert payload["draftAfterQueueDrain"] == "draft typed during stream"
    assert payload["yamlDraftPreserved"] is True
    assert payload["configResetToForm"] is True
    assert payload["channelStatusCallsAfterDestroyedWait"] == 0
    assert payload["sessionDeleteFailed"] is True
    assert payload["sessionDeleteFalseSuccess"] is False
    assert payload["logState"]["tailCalls"] >= 2
    assert payload["logState"]["maxInFlight"] == 1
