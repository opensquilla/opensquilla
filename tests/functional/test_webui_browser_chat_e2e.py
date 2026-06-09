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
                null, { timeout: 5000 }
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


def test_replay_gap_history_refresh_preserves_scroll_in_real_browser(tmp_path: Path) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_gap_scroll_server.py"
    browser_script = tmp_path / "webui_gap_scroll_browser.js"
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

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage({ viewport: { width: 1365, height: 768 } });
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));
              page.on("console", msg => {
                if (msg.type() === "error") errors.push(msg.text());
              });

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForFunction(
                () =>
                  typeof App !== "undefined" &&
                  App.getRpc &&
                  App.getRpc()?.state === "connected",
                { timeout: 15000 }
              );

              await page.evaluate(() => {
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                const messages = [];
                for (let i = 1; i <= 70; i += 1) {
                  const label = i % 2 ? "User" : "Assistant";
                  messages.push({
                    role: i % 2 ? "user" : "assistant",
                    text: `${label} history row ${String(i).padStart(2, "0")} `.repeat(8),
                    timestamp: `2026-06-03T00:${String(i % 60).padStart(2, "0")}:00.000Z`,
                    message_id: `gap-probe-${i}`,
                  });
                }
                window.__gapProbe = { subscribeCount: 0, historyCount: 0, gapInjected: false };
                rpc.call = async (method, params) => {
                  if (method === "chat.history") {
                    window.__gapProbe.historyCount += 1;
                    return {
                      messages,
                      has_more: false,
                      history_scope: "complete",
                      oldest_cursor: null,
                      newest_cursor: null,
                      compaction_summaries: [],
                    };
                  }
                  if (method === "sessions.messages.subscribe") {
                    window.__gapProbe.subscribeCount += 1;
                    if (window.__gapProbe.subscribeCount <= 1) {
                      return {
                        subscribed: true,
                        key: params && params.key,
                        current_stream_seq: 12,
                        replay_complete: true,
                        replayed_count: 0,
                        run_status: "idle",
                      };
                    }
                    window.__gapProbe.gapInjected = true;
                    return {
                      subscribed: true,
                      key: params && params.key,
                      current_stream_seq: 18,
                      replay_complete: false,
                      replay_gap_reason: "stream_buffer_empty",
                      replayed_count: 0,
                      run_status: "idle",
                    };
                  }
                  return originalCall(method, params);
                };
              });

              await page.evaluate(() =>
                Router.navigate(
                  "/chat?session=" +
                    encodeURIComponent("agent:main:webchat:gap-playwright-regression")
                )
              );
              await page.waitForSelector("#chat-thread .msg", { timeout: 15000 });
              await page.waitForFunction(
                () => document.querySelectorAll("#chat-thread .msg").length >= 60,
                { timeout: 15000 }
              );

              const before = await page.evaluate(() => {
                const thread = document.querySelector("#chat-thread");
                thread.scrollTop = 120;
                return {
                  scrollTop: thread.scrollTop,
                  scrollHeight: thread.scrollHeight,
                  clientHeight: thread.clientHeight,
                  bottomDistance: thread.scrollHeight - thread.clientHeight - thread.scrollTop,
                  messageCount: document.querySelectorAll("#chat-thread .msg").length,
                };
              });

              await page.evaluate(() => {
                const handlers = App.getRpc()._listeners.get("_state");
                if (handlers) handlers.forEach(h => h("connected"));
              });
              await page.waitForFunction(
                () => window.__gapProbe && window.__gapProbe.gapInjected === true,
                { timeout: 15000 }
              );
              await page.waitForFunction(
                () => window.__gapProbe && window.__gapProbe.historyCount >= 3,
                { timeout: 15000 }
              );

              const after = await page.evaluate(() => {
                const thread = document.querySelector("#chat-thread");
                return {
                  scrollTop: thread.scrollTop,
                  scrollHeight: thread.scrollHeight,
                  clientHeight: thread.clientHeight,
                  bottomDistance: thread.scrollHeight - thread.clientHeight - thread.scrollTop,
                  messageCount: document.querySelectorAll("#chat-thread .msg").length,
                  toasts: Array.from(document.querySelectorAll(".toast")).map(el =>
                    el.textContent.trim()
                  ),
                  probe: window.__gapProbe,
                };
              });

              await browser.close();
              console.log(JSON.stringify({ before, after, errors }));
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
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/overview"),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload["errors"] == [], payload["errors"]
    assert payload["before"]["messageCount"] >= 60
    assert payload["after"]["messageCount"] == payload["before"]["messageCount"]
    assert payload["after"]["probe"]["gapInjected"] is True
    assert payload["after"]["bottomDistance"] > 1000, payload
    assert payload["after"]["scrollTop"] <= payload["before"]["scrollTop"] + 80, payload
    assert "Session stream gap detected; reloading transcript." not in payload["after"]["toasts"]


def test_chat_topbar_one_row_layout_in_real_browser(tmp_path: Path) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_chat_topbar_server.py"
    browser_script = tmp_path / "webui_chat_topbar_browser.js"
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

            async function emit(page, event, payload, meta = {}) {
              await page.evaluate(
                ({ event, payload, meta }) => {
                  const rpc = App.getRpc();
                  const handlers = rpc._listeners.get(event);
                  if (handlers) handlers.forEach(h => h(payload, meta));
                  const wild = rpc._listeners.get("*");
                  if (wild) wild.forEach(h => h(event, payload, meta));
                },
                { event, payload, meta }
              );
            }

            async function measure(page, viewport) {
              await page.setViewportSize({ width: viewport.width, height: viewport.height });
              const session =
                "agent:main:webchat:very-long-session-key-with-extra-segments-1234567890";
              await page.goto(process.env.TARGET_URL + "?session=" + encodeURIComponent(session), {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.waitForSelector("#topbar-center:not(.hidden)", { timeout: 5000 });

              await emit(page, "session.event.done", {
                text: "",
                contextStatus: {
                  contextTokens: 90000,
                  contextWindowTokens: 100000,
                  pressure: 0.9,
                },
              });
              await emit(page, "task.running", { task_id: "topbar-task", session_key: session });
              await page.waitForFunction(() => {
                const el = document.querySelector("#chat-run-status");
                return el && el.textContent.trim() === "Running";
              });
              if (viewport.showApproval) {
                await page.evaluate(() => {
                  const inline = document.querySelector("#approval-inline");
                  inline.textContent = "Approval required";
                  inline.setAttribute("aria-label", "Approval required");
                  inline.title = "Approval required";
                  inline.classList.remove("hidden");
                });
              }
              await page.waitForTimeout(80);

              const snapshot = await page.evaluate(() => {
                const box = (selector) => {
                  const el = document.querySelector(selector);
                  if (!el) return null;
                  const r = el.getBoundingClientRect();
                  return {
                    left: r.left,
                    right: r.right,
                    top: r.top,
                    bottom: r.bottom,
                    width: r.width,
                    height: r.height,
                    visible:
                      r.width > 0 &&
                      r.height > 0 &&
                      getComputedStyle(el).display !== "none" &&
                      getComputedStyle(el).visibility !== "hidden",
                  };
                };
                const center = document.querySelector("#topbar-center");
                const label = document.querySelector(".topbar-center .chat-label");
                const warning = document.querySelector("#chat-ctx-warn");
                const chipKey = document.querySelector("#chat-session-chip-key");
                const centerBox = box("#topbar-center");
                const topbarBox = box(".topbar");
                const topbarRightBox = box(".topbar-right");
                const childBoxes = Array.from(center ? center.children : []).map((el) => {
                  const r = el.getBoundingClientRect();
                  return {
                    id: el.id || el.className || el.tagName,
                    left: r.left,
                    right: r.right,
                    width: r.width,
                    display: getComputedStyle(el).display,
                  };
                });
                return {
                  width: window.innerWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  topbarCount: document.querySelectorAll(".topbar").length,
                  chatHeaderCount: document.querySelectorAll(".chat-header").length,
                  centerHidden: center ? center.classList.contains("hidden") : true,
                  centerBox,
                  topbarBox,
                  topbarRightBox,
                  chip: box("#chat-session-chip"),
                  chipKeyText: chipKey ? chipKey.textContent : "",
                  copy: box("#chat-session-copy"),
                  runStatus: box("#chat-run-status"),
                  runStatusText: document.querySelector("#chat-run-status")?.textContent || "",
                  warning: box("#chat-ctx-warn"),
                  warningText: warning ? warning.textContent : "",
                  labelDisplay: label ? getComputedStyle(label).display : "",
                  theme: box("#theme-toggle"),
                  approval: box("#approval-inline"),
                  approvalText: document.querySelector("#approval-inline")?.textContent || "",
                  approvalLabel:
                    document.querySelector("#approval-inline")?.getAttribute("aria-label") || "",
                  approvalCount: document.querySelectorAll("#approval-inline").length,
                  topbarChildren: childBoxes,
                };
              });

              await page.locator("#theme-toggle").click();
              const themeAfterClick = await page.evaluate(
                () => document.documentElement.getAttribute("data-theme")
              );
              return { name: viewport.name, snapshot, themeAfterClick };
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              const viewports = [
                { name: "desktop", width: 1365, height: 768 },
                { name: "wide", width: 1600, height: 900 },
                { name: "tablet", width: 768, height: 900 },
                { name: "mobile", width: 390, height: 844, showApproval: true },
              ];
              const layouts = [];
              for (const viewport of viewports) layouts.push(await measure(page, viewport));

              await page.setViewportSize({ width: 1365, height: 768 });
              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.evaluate(() => Router.navigate("/overview"));
              await page.waitForSelector(".ov-stage__title", { timeout: 5000 });
              const cleanup = await page.evaluate(() => ({
                centerHidden:
                  document.querySelector("#topbar-center")?.classList.contains("hidden"),
                centerText: document.querySelector("#topbar-center")?.textContent.trim(),
                chatIds:
                  document.querySelectorAll(
                    "#chat-session-chip, #chat-session-chip-key, " +
                    "#chat-session-copy, #chat-run-status, #chat-ctx-warn"
                  ).length,
              }));

              await browser.close();
              console.log(JSON.stringify({ layouts, cleanup, pageErrors: errors }));
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

    assert payload["pageErrors"] == []
    assert payload["cleanup"] == {"centerHidden": True, "centerText": "", "chatIds": 0}

    layouts = {item["name"]: item["snapshot"] for item in payload["layouts"]}
    for name, snap in layouts.items():
        assert snap["scrollWidth"] <= snap["width"], (name, snap)
        assert snap["topbarCount"] == 1, (name, snap)
        assert snap["chatHeaderCount"] == 0, (name, snap)
        assert snap["centerHidden"] is False, (name, snap)
        assert snap["chip"]["visible"], (name, snap)
        assert snap["copy"]["visible"], (name, snap)
        assert snap["runStatus"]["visible"], (name, snap)
        assert snap["runStatusText"] == "Running", (name, snap)
        assert snap["theme"]["visible"], (name, snap)
        assert snap["approvalCount"] == 1, (name, snap)
        assert snap["chipKeyText"].startswith("agent:main:webchat:very-long-session-key")
        assert snap["centerBox"]["right"] <= snap["topbarRightBox"]["left"] + 1, (name, snap)
        center = snap["centerBox"]
        for child in snap["topbarChildren"]:
            if child["display"] == "none":
                continue
            assert child["left"] >= center["left"] - 1, (name, child, center)
            assert child["right"] <= center["right"] + 1, (name, child, center)

    for name in ("desktop", "wide"):
        snap = layouts[name]
        assert snap["labelDisplay"] != "none"
        assert snap["warning"]["visible"], (name, snap)
        assert snap["warningText"].startswith("Request ctx 90%"), (name, snap)

    assert layouts["tablet"]["labelDisplay"] == "none"
    assert layouts["mobile"]["labelDisplay"] == "none"
    assert layouts["mobile"]["approval"]["visible"], layouts["mobile"]
    assert layouts["mobile"]["approval"]["width"] <= 40, layouts["mobile"]
    assert layouts["mobile"]["approvalText"] == "Approval required"
    assert layouts["mobile"]["approvalLabel"] == "Approval required"
    assert layouts["mobile"]["warning"]["visible"] is False
    assert all(item["themeAfterClick"] in {"dark", "light"} for item in payload["layouts"])


def test_chat_slash_menu_aligns_with_composer_in_real_browser(tmp_path: Path) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_chat_slash_server.py"
    browser_script = tmp_path / "webui_chat_slash_browser.js"
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

            async function installMocks(page) {
              await page.evaluate(() => {
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: { enabled: true, rollout_phase: "full", tiers: {} },
                    });
                  }
                  if (method === "chat.history") {
                    return Promise.resolve({
                      messages: [],
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 0,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  if (method === "commands.list_for_surface") {
                    return Promise.resolve({
                      commands: [
                        {
                          name: "/compact",
                          description: [
                            "Compact older context in the current session with an intentionally",
                            "long command description that must truncate instead of stretching",
                            "the composer tray.",
                          ].join(" "),
                          execution: { action: "sessions.contextCompact" },
                        },
                      ],
                    });
                  }
                  if (method === "sessions.contextCompact") {
                    return Promise.resolve({ compacted: false, reason: "no_entries" });
                  }
                  return originalCall(method, params);
                };
              });
            }

            async function openChat(page, viewport) {
              await page.setViewportSize({ width: viewport.width, height: viewport.height });
              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await waitRpc(page);
              await installMocks(page);
              await page.evaluate(() =>
                Router.navigate("/chat?session=agent:main:webchat:slash-layout")
              );
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.locator("#chat-textarea").fill("/compact");
              await page.waitForSelector(".chat-slash:not(.hidden)", { timeout: 5000 });
              await page.waitForTimeout(80);
            }

            async function measure(page, viewport) {
              await openChat(page, viewport);
              const layout = await page.evaluate(() => {
                const box = (selector) => {
                  const el = document.querySelector(selector);
                  const r = el.getBoundingClientRect();
                  return {
                    left: r.left,
                    right: r.right,
                    width: r.width,
                    height: r.height,
                    visible:
                      r.width > 0 &&
                      r.height > 0 &&
                      getComputedStyle(el).display !== "none" &&
                      getComputedStyle(el).visibility !== "hidden",
                  };
                };
                const desc = document.querySelector(".chat-slash-desc");
                const slash = document.querySelector(".chat-slash");
                const input = document.querySelector(".chat-input-bar");
                return {
                  width: window.innerWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  slash: box(".chat-slash"),
                  input: box(".chat-input-bar"),
                  composer: box("#chat-composer"),
                  attach: box("#chat-btn-attach"),
                  newChat: box("#chat-btn-new"),
                  exportButton: box("#chat-btn-export"),
                  send: box("#chat-btn-send"),
                  slashParentId: slash?.parentElement?.id || "",
                  slashBeforeInput: !!(
                    slash &&
                    input &&
                    slash.compareDocumentPosition(input) &
                      Node.DOCUMENT_POSITION_FOLLOWING
                  ),
                  descClientWidth: desc ? desc.clientWidth : 0,
                  descScrollWidth: desc ? desc.scrollWidth : 0,
                };
              });

              await page.locator("#chat-textarea").press("ArrowDown");
              const afterArrow = await page.locator(".chat-slash:not(.hidden)").count();
              await page.locator("#chat-textarea").press("Escape");
              const afterEscape = await page.locator(".chat-slash:not(.hidden)").count();
              await page.locator("#chat-textarea").fill("/compact");
              await page.waitForSelector(".chat-slash:not(.hidden)", { timeout: 5000 });
              await page.locator("#chat-textarea").press("Enter");
              await page.waitForFunction(
                () => document.querySelector("#chat-textarea").value === ""
              );
              const afterEnterValue = await page.locator("#chat-textarea").inputValue();

              return {
                name: viewport.name,
                layout,
                afterArrow,
                afterEscape,
                afterEnterValue,
              };
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));
              const viewports = [
                { name: "desktop", width: 1365, height: 768 },
                { name: "wide", width: 2048, height: 900 },
                { name: "mobile", width: 390, height: 844 },
              ];
              const layouts = [];
              for (const viewport of viewports) layouts.push(await measure(page, viewport));
              await browser.close();
              console.log(JSON.stringify({ layouts, pageErrors: errors }));
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
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/"),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload["pageErrors"] == []
    layouts = {item["name"]: item for item in payload["layouts"]}
    for name, item in layouts.items():
        layout = item["layout"]
        assert layout["scrollWidth"] <= layout["width"], (name, layout)
        assert layout["slash"]["visible"], (name, layout)
        assert layout["slashParentId"] == "chat-composer", (name, layout)
        assert layout["slashBeforeInput"] is True, (name, layout)
        if name == "mobile":
            assert layout["slash"]["left"] >= layout["composer"]["left"], (name, layout)
            assert layout["slash"]["right"] <= layout["composer"]["right"], (name, layout)
        else:
            assert abs(layout["slash"]["left"] - layout["input"]["left"]) <= 1, (name, layout)
            assert abs(layout["slash"]["right"] - layout["input"]["right"]) <= 1, (name, layout)
        assert layout["descScrollWidth"] > layout["descClientWidth"], (name, layout)
        assert item["afterArrow"] == 1, item
        assert item["afterEscape"] == 0, item
        assert item["afterEnterValue"] == "", item
        assert layout["attach"]["visible"], (name, layout)
        assert layout["newChat"]["visible"], (name, layout)
        assert layout["send"]["visible"], (name, layout)

    assert layouts["desktop"]["layout"]["slash"]["width"] < 1000
    assert layouts["wide"]["layout"]["slash"]["width"] < 1000
    assert layouts["mobile"]["layout"]["exportButton"]["visible"] is False


def test_chat_escape_in_composer_aborts_streaming_turn_in_real_browser(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_escape_abort_server.py"
    browser_script = tmp_path / "webui_escape_abort_browser.js"
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
                window.__escapeAbort = { sendCalls: [], abortCalls: [] };
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: { enabled: true, rollout_phase: "full", tiers: {} },
                    });
                  }
                  if (method === "chat.history") {
                    return Promise.resolve({
                      messages: [],
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 0,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  if (method === "chat.send") {
                    window.__escapeAbort.sendCalls.push(params);
                    return Promise.resolve({ task_id: "escape-abort-task" });
                  }
                  if (method === "chat.abort") {
                    window.__escapeAbort.abortCalls.push(params);
                    return Promise.resolve({ aborted: true, key: params.sessionKey });
                  }
                  return originalCall(method, params);
                };
              });

              await page.evaluate(() =>
                Router.navigate("/chat?session=agent:main:webchat:escape-abort")
              );
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.fill("#chat-textarea", "turn to abort from textarea");
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () =>
                  window.__escapeAbort.sendCalls.length === 1 &&
                  OpenSquillaChatDiag.snapshot().isStreaming === true,
                null, { timeout: 5000 }
              );

              await page.focus("#chat-textarea");
              const before = await page.evaluate(() => ({
                focusId: document.activeElement?.id || "",
                isStreaming: OpenSquillaChatDiag.snapshot().isStreaming,
                stopVisible:
                  !document.querySelector("#chat-btn-stop")?.classList.contains("hidden"),
              }));
              await page.locator("#chat-textarea").press("Escape");
              await page.waitForFunction(
                () => window.__escapeAbort.abortCalls.length === 1,
                null, { timeout: 5000 }
              );
              await page.waitForFunction(
                () => OpenSquillaChatDiag.snapshot().isStreaming === false,
                null, { timeout: 5000 }
              );
              const afterState = await page.evaluate(() => ({
                isStreaming: OpenSquillaChatDiag.snapshot().isStreaming,
                streamingCount: document.querySelectorAll(".msg.streaming").length,
                thinkingCount: document.querySelectorAll(".msg.thinking").length,
                stopVisible:
                  !document.querySelector("#chat-btn-stop")?.classList.contains("hidden"),
                abortCalls: window.__escapeAbort.abortCalls,
              }));
              const after = { ...afterState, pageErrors: errors };

              await browser.close();
              console.log(JSON.stringify({ before, after }));
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

    before = payload["before"]
    after = payload["after"]
    assert before["focusId"] == "chat-textarea", before
    assert before["isStreaming"] is True, before
    assert before["stopVisible"] is True, before
    assert after["abortCalls"] == [
        {
            "sessionKey": "agent:main:webchat:escape-abort",
            "source": "webui_escape",
        }
    ], after
    assert after["isStreaming"] is False, after
    assert after["streamingCount"] == 0, after
    assert after["thinkingCount"] == 0, after
    assert after["stopVisible"] is False, after
    assert after["pageErrors"] == [], after


def test_chat_tool_result_full_view_handles_large_payloads_in_real_browser(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_chat_tool_result_server.py"
    browser_script = tmp_path / "webui_chat_tool_result_browser.js"
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

            async function installMocks(page) {
              await page.evaluate(() => {
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: { enabled: true, rollout_phase: "full", tiers: {} },
                    });
                  }
                  if (method === "chat.history") {
                    const longOutput = [
                      "labubu-1.jpg -> 1788872 chars base64",
                      "labubu-2.jpg -> 836304 chars base64",
                      "labubu-3.jpg -> 2109592 chars base64",
                      "single-unbroken-token-" + "x".repeat(1800),
                    ].join("\\n");
                    return Promise.resolve({
                      messages: [
                        {
                          role: "assistant",
                          text: "",
                          timestamp: "2026-05-31T00:00:00Z",
                          tool_calls: [
                            {
                              type: "tool_use",
                              name: "execute_code",
                              tool_use_id: "tool-large-result",
                              input: { code: "print_large_payload()" },
                            },
                            {
                              type: "tool_result",
                              tool_use_id: "tool-large-result",
                              result: {
                                exit_code: 0,
                                stdout: longOutput,
                                stderr: "",
                                timed_out: false,
                                elapsed_ms: 213,
                              },
                            },
                          ],
                        },
                      ],
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 0,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  return originalCall(method, params);
                };
              });
            }

            async function measure(page, viewport) {
              await page.setViewportSize({ width: viewport.width, height: viewport.height });
              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await waitRpc(page);
              await installMocks(page);
              await page.evaluate(() =>
                Router.navigate("/chat?session=agent:main:webchat:tool-result-full")
              );
              await page.waitForSelector(".chat-tools-summary", { timeout: 15000 });
              await page.locator(".chat-tools-summary").first().click();
              await page.waitForSelector(".chat-tool-view-btn", {
                state: "visible",
                timeout: 5000,
              });
              await page.locator(".chat-tool-view-btn").first().click();
              await page.waitForSelector(".modal .chat-tool-result-full", { timeout: 5000 });
              const layout = await page.evaluate(() => {
                const rect = (selector) => {
                  const el = document.querySelector(selector);
                  const r = el.getBoundingClientRect();
                  return {
                    left: r.left,
                    right: r.right,
                    top: r.top,
                    bottom: r.bottom,
                    width: r.width,
                    height: r.height,
                  };
                };
                const pre = document.querySelector(".chat-tool-result-full");
                const button = document.querySelector(".chat-tool-view-btn");
                return {
                  width: window.innerWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  modal: rect(".modal"),
                  pre: rect(".chat-tool-result-full"),
                  preScrollWidth: pre.scrollWidth,
                  preClientWidth: pre.clientWidth,
                  buttonType: button ? button.getAttribute("type") : "",
                  text: pre ? pre.textContent.slice(0, 80) : "",
                };
              });
              await page.locator(".modal-foot button", { hasText: "Close" }).click();
              await page.waitForSelector(".modal-backdrop", { state: "detached", timeout: 5000 });
              const afterClose = await page.locator(".modal-backdrop").count();
              return { name: viewport.name, layout, afterClose };
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));
              const viewports = [
                { name: "desktop", width: 1365, height: 768 },
                { name: "mobile", width: 390, height: 844 },
              ];
              const layouts = [];
              for (const viewport of viewports) layouts.push(await measure(page, viewport));
              await browser.close();
              console.log(JSON.stringify({ layouts, pageErrors: errors }));
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
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/"),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload["pageErrors"] == []
    layouts = {item["name"]: item for item in payload["layouts"]}
    for name, item in layouts.items():
        layout = item["layout"]
        assert item["afterClose"] == 0, item
        assert layout["scrollWidth"] <= layout["width"], (name, layout)
        assert layout["buttonType"] == "button", (name, layout)
        assert "labubu-1.jpg" in layout["text"], (name, layout)
        assert layout["modal"]["left"] >= 0, (name, layout)
        assert layout["modal"]["right"] <= layout["width"], (name, layout)
        assert layout["pre"]["right"] <= layout["modal"]["right"], (name, layout)
        assert layout["preScrollWidth"] <= layout["preClientWidth"] + 2, (name, layout)


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

            async function emitEvent(page, event, payload, meta = {}) {
              await page.evaluate(
                ({ event, payload, meta }) => {
                  const rpc = App.getRpc();
                  const handlers = rpc._listeners.get(event);
                  if (handlers) {
                    handlers.forEach(h => h(payload, meta));
                  }
                  const wild = rpc._listeners.get("*");
                  if (wild) wild.forEach(h => h(event, payload, meta));
                },
                { event, payload, meta }
              );
            }

            async function emitCompaction(page, payload, meta = {}) {
              return emitEvent(page, "session.event.compaction", payload, meta);
            }

            async function lastSeparatorText(page) {
              return await page.evaluate(() => {
                const separators = document.querySelectorAll(".chat-context-separator");
                return separators.length
                  ? separators[separators.length - 1].textContent
                  : "";
              });
            }

            async function lastSeparatorPlacement(page) {
              return await page.evaluate(() => {
                const thread = document.querySelector("#chat-thread");
                const separators = document.querySelectorAll(".chat-context-separator");
                const separator = separators[separators.length - 1];
                if (!thread || !separator) return null;
                const threadBox = thread.getBoundingClientRect();
                const separatorBox = separator.getBoundingClientRect();
                return {
                  bottomGap: Math.round(threadBox.bottom - separatorBox.bottom),
                  topGap: Math.round(separatorBox.top - threadBox.top),
                  className: separator.className,
                  scrollTop: Math.round(thread.scrollTop),
                  scrollHeight: Math.round(thread.scrollHeight),
                  clientHeight: Math.round(thread.clientHeight),
                };
              });
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
              await page.evaluate(() => {
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                const originalToast = UI.toast.bind(UI);
                window.__compactUx = { chatCalls: [], toastCalls: [] };
                UI.toast = (message, type = "info", duration = 3000) => {
                  window.__compactUx.toastCalls.push({ message, type, duration });
                  return originalToast(message, type, duration);
                };
                rpc.call = (method, params = {}) => {
                  if (method === "chat.send") {
                    window.__compactUx.chatCalls.push({ method, params });
                    return Promise.resolve({
                      task_id: "compact-ux-" + window.__compactUx.chatCalls.length,
                    });
                  }
                  return originalCall(method, params);
                };
              });

              await emitCompaction(page, { status: "started", source: "manual" });
              await page.waitForSelector(".chat-context-separator", { timeout: 5000 });
              await page.waitForTimeout(600);
              const startedStatusVisible = await lastSeparatorText(page);
              const manualSeparatorStarted = startedStatusVisible;
              const manualSeparatorStartedPlacement = await lastSeparatorPlacement(page);
              await emitCompaction(page, { status: "skipped", source: "manual" });
              await page.waitForTimeout(250);
              const skippedStatusVisible = await lastSeparatorText(page);

              await emitCompaction(page, {
                status: "completed",
                source: "manual",
                tokens_before: 3500,
                tokens_after: 1300,
              });
              await page.waitForFunction(
                () => document.body.textContent.includes("context compacted"),
                null, { timeout: 5000 }
              );

              await emitCompaction(
                page,
                { status: "failed", source: "manual", message: "old replay" },
                { replayed: true }
              );
              await page.waitForTimeout(250);

              await emitCompaction(page, { status: "started", source: "manual" });
              await page.fill("#chat-textarea", "queued during compact");
              await page.click("#chat-btn-send");
              await page.waitForTimeout(150);
              const queuedBeforeSkipped = await page.evaluate(
                () => window.__compactUx.chatCalls.length
              );
              await emitCompaction(page, { status: "skipped", source: "manual" });
              await page.waitForFunction(
                () =>
                  window.__compactUx.chatCalls
                    .some(c => c.params.message === "queued during compact"),
                null, { timeout: 5000 }
              );
              await emitEvent(page, "session.event.done", { text: "compact queued answer" });
              await page.waitForTimeout(150);

              await page.fill("#chat-textarea", "seed automatic compact turn");
              await page.click("#chat-btn-send");
              await page.waitForTimeout(150);
              const callsBeforeAutomaticCompact = await page.evaluate(
                () => window.__compactUx.chatCalls.length
              );
              await emitCompaction(page, {
                status: "started",
                source: "automatic",
                phase: "preflight",
              });
              await page.waitForTimeout(800);
              const automaticStartedStatusVisible = await lastSeparatorText(page);
              const automaticSeparatorStarted = automaticStartedStatusVisible;
              const automaticSeparatorStartedPlacement = await lastSeparatorPlacement(page);
              await page.fill("#chat-textarea", "queued during automatic compact");
              await page.click("#chat-btn-send");
              await page.waitForTimeout(150);
              const automaticQueuedBeforeCompleted = await page.evaluate(
                () => window.__compactUx.chatCalls.length
              );
              await emitCompaction(page, {
                status: "observed",
                source: "automatic",
                event: "compaction.chunk_summarized",
                tokens_before: 5000,
                tokens_after: 2600,
              });
              await page.waitForTimeout(800);
              const automaticObservedStatusVisible = await lastSeparatorText(page);
              const automaticSeparatorObserved = automaticObservedStatusVisible;
              await emitCompaction(page, {
                status: "completed",
                source: "automatic",
                tokens_before: 5000,
                tokens_after: 1800,
              });
              await page.waitForTimeout(800);
              const automaticSeparatorCompleted = await lastSeparatorText(page);
              const automaticDidNotDrainBeforeDone = await page.evaluate(
                expected => window.__compactUx.chatCalls.length === expected,
                callsBeforeAutomaticCompact
              );
              await emitEvent(page, "session.event.done", { text: "automatic compact answer" });
              await page.waitForFunction(
                () =>
                  window.__compactUx.chatCalls
                    .some(c => c.params.message === "queued during automatic compact"),
                null, { timeout: 5000 }
              );

              // Wait >1500ms so the dedup guard resets before emitting another
              // "started" event with the same source signature.
              await page.waitForTimeout(1600);
              await emitCompaction(page, {
                status: "started",
                source: "automatic",
                phase: "preflight",
              });
              await page.waitForTimeout(800);
              await emitCompaction(page, {
                status: "skipped",
                source: "automatic",
                phase: "preflight",
                reason: "structured_content_noop",
                user_visible: false,
              });
              await page.waitForTimeout(300);
              const automaticNoopSeparatorHidden = await page
                .locator(".chat-context-separator")
                .count();
              const automaticNoopBodyText = await page.evaluate(
                () => document.body.textContent
              );

              await page.waitForTimeout(1600);
              await emitCompaction(page, {
                status: "started",
                source: "automatic",
                phase: "preflight",
              });
              await page.waitForTimeout(800);
              await emitCompaction(page, {
                status: "skipped",
                source: "automatic",
                phase: "preflight",
                reason: "empty_summary",
                user_visible: true,
              });
              await page.waitForTimeout(800);
              const automaticNonBenignSkipStatus = await lastSeparatorText(page);

              await page.waitForTimeout(1600);
              await emitCompaction(page, {
                status: "started",
                source: "automatic",
                phase: "preflight",
              });
              await page.waitForTimeout(800);
              await emitCompaction(page, {
                status: "emergency_ephemeral",
                source: "automatic",
                phase: "preflight",
                reason: "empty_summary",
                tokens_before: 5000,
                tokens_after: 2400,
              });
              await page.waitForTimeout(800);
              const emergencyStatusVisible = await lastSeparatorText(page);

              await page.waitForTimeout(1600);
              await emitCompaction(page, { status: "started", source: "manual" });
              await page.waitForTimeout(800);
              await page.fill("#chat-textarea", "queued after blocking compact failure");
              await page.click("#chat-btn-send");
              await page.waitForTimeout(150);
              await emitCompaction(page, {
                status: "failed",
                source: "manual",
                reason: "compaction_insufficient",
                message: "still over budget",
                refused: true,
              });
              await page.waitForTimeout(800);
              const failedStatusVisible = await lastSeparatorText(page);

              const bodyText = await page.locator("body").innerText();
              const toastMessages = await page.evaluate(
                () => window.__compactUx.toastCalls.map(t => t.message)
              );
              // Diagnostic: log actual rail text for debugging
              console.error("DIAG_EMERGENCY:", JSON.stringify(emergencyStatusVisible));
              console.error("DIAG_FAILED:", JSON.stringify(failedStatusVisible));
              const result = {
                hasStartedToast: toastMessages.includes("Compacting context..."),
                hasSkippedToast: toastMessages.includes(
                  "Already within context budget; no compact was applied."
                ),
                hasCompletedToast: toastMessages.some(m => m.includes("Context compacted")),
                hasEmergencyToast: toastMessages.includes(
                  "Continuing with temporary context compaction for this turn"
                ),
                hasFailedToast: toastMessages.some(
                  m => m.includes("Compact failed: still over budget")
                ),
                hasReplayedFailureToast: toastMessages.some(m => m.includes("old replay")),
                startedStatusVisible: startedStatusVisible.includes("context compacting"),
                manualRailStarted:
                  manualSeparatorStarted.includes("context compacting"),
                manualRailBottomAnchored:
                  manualSeparatorStartedPlacement &&
                  manualSeparatorStartedPlacement.bottomGap <= 60 &&
                  manualSeparatorStartedPlacement.className
                    .includes("chat-context-separator--session"),
                skippedStatusVisible: skippedStatusVisible.includes(
                  "no compaction needed"
                ),
                failedStatusVisible:
                  failedStatusVisible.includes("compaction failed"),
                queuedBeforeSkipped,
                skippedDrainedQueuedSend: await page.evaluate(
                  () => window.__compactUx.chatCalls
                    .some(c => c.params.message === "queued during compact")
                ),
                automaticStartedStatusVisible: automaticStartedStatusVisible.includes(
                  "context compacting"
                ),
                automaticRailStarted:
                  automaticSeparatorStarted.includes("context compacting"),
                automaticRailBottomAnchored:
                  automaticSeparatorStartedPlacement &&
                  automaticSeparatorStartedPlacement.bottomGap <= 60 &&
                  automaticSeparatorStartedPlacement.className
                    .includes("chat-context-separator--session"),
                automaticObservedStatusVisible: automaticObservedStatusVisible.includes(
                  "context compacting"
                ),
                automaticRailObserved:
                  automaticSeparatorObserved.includes("context compacting"),
                automaticRailCompleted:
                  automaticSeparatorCompleted.includes("context compacted"),
                automaticQueuedBeforeCompleted:
                  automaticQueuedBeforeCompleted === callsBeforeAutomaticCompact,
                automaticDidNotDrainBeforeDone,
                automaticDrainedAfterDone: await page.evaluate(
                  () => window.__compactUx.chatCalls
                    .some(c => c.params.message === "queued during automatic compact")
                ),
                emergencyStatusVisible:
                  emergencyStatusVisible.includes("temporary compaction") &&
                  !emergencyStatusVisible.includes("empty summary"),
                automaticNoopRailHidden: automaticNoopSeparatorHidden === 0,
                automaticNoopSkippedHidden:
                  !automaticNoopBodyText.includes("Context compaction skipped") &&
                  !automaticNoopBodyText.includes("structured content noop"),
                automaticNonBenignSkipVisible:
                  automaticNonBenignSkipStatus.includes("compaction skipped") &&
                  !automaticNonBenignSkipStatus.includes("empty summary"),
                blockingFailureKeptPending:
                  (await page.locator("#chat-pending").innerText())
                    .includes("queued after blocking compact"),
                blockingFailureDidNotDrain: await page.evaluate(
                  () => !window.__compactUx.chatCalls
                    .some(c => c.params.message === "queued after blocking compact failure")
                ),
                blockingFailureDidNotRecoverComposer:
                  (await page.locator("#chat-textarea").inputValue()) === "",
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
        "hasCompletedToast": False,
        "hasEmergencyToast": True,
        "hasFailedToast": True,
        "hasReplayedFailureToast": False,
        "startedStatusVisible": True,
        "manualRailStarted": True,
        "manualRailBottomAnchored": True,
        "skippedStatusVisible": True,
        "failedStatusVisible": True,
        "queuedBeforeSkipped": 0,
        "skippedDrainedQueuedSend": True,
        "automaticStartedStatusVisible": True,
        "automaticRailStarted": True,
        "automaticRailBottomAnchored": True,
        "automaticObservedStatusVisible": True,
        "automaticRailObserved": True,
        "automaticRailCompleted": True,
        "automaticQueuedBeforeCompleted": True,
        "automaticDidNotDrainBeforeDone": True,
        "automaticDrainedAfterDone": True,
        "emergencyStatusVisible": True,
        "automaticNoopRailHidden": True,
        "automaticNoopSkippedHidden": True,
        "automaticNonBenignSkipVisible": True,
        "blockingFailureKeptPending": True,
        "blockingFailureDidNotDrain": True,
        "blockingFailureDidNotRecoverComposer": True,
        "pageErrors": [],
    }


def test_router_fx_live_then_reopen_stays_settled_in_real_browser(tmp_path: Path) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_router_fx_server.py"
    browser_script = tmp_path / "webui_router_fx_browser.js"
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

            async function emit(page, event, payload, meta = {}) {
              await page.evaluate(
                ({ event, payload, meta }) => {
                  const rpc = App.getRpc();
                  const named = rpc._listeners.get(event);
                  if (named) named.forEach(h => h(payload, meta));
                  const wild = rpc._listeners.get("*");
                  if (wild) wild.forEach(h => h(event, payload, meta));
                },
                { event, payload, meta }
              );
            }

            async function snapshot(page) {
              return await page.evaluate(() => {
                const strips = Array.from(document.querySelectorAll(".router-fx"));
                const strip = strips[0] || null;
                const cells = Array.from(document.querySelectorAll(".router-fx-cell .nm"));
                const animations = strips.flatMap(el =>
                  el.getAnimations({ subtree: true })
                    .filter(anim => anim.playState !== "finished" && anim.playState !== "idle")
                    .map(anim => anim.animationName || "")
                );
                const overflows = cells.filter(el => el.scrollWidth > el.clientWidth + 1)
                  .map(el => el.textContent);
                const grid = document.querySelector(".router-fx-grid");
                const gridRect = grid ? grid.getBoundingClientRect() : null;
                return {
                  count: strips.length,
                  state: strip?.dataset.state || "",
                  renderMode: strip?.dataset.renderMode || "",
                  liveCount: document.querySelectorAll(".router-fx[data-live='true']").length,
                  scanningCount: document.querySelectorAll(
                    ".router-fx[data-scanning='true']"
                  ).length,
                  selectorVisible: document.querySelectorAll(".router-fx-selector.visible").length,
                  bursts: document.querySelectorAll(".router-fx-burst").length,
                  pinging: document.querySelectorAll(".router-fx-cell.pinging").length,
                  animations,
                  aria: strip?.getAttribute("aria-label") || "",
                  winner: document.querySelector(".router-fx-cell.win .nm")?.textContent || "",
                  winners: strips.map(
                    el => el.querySelector(".router-fx-cell.win .nm")?.textContent || ""
                  ),
                  cellCount: cells.length,
                  cellLabels: cells.map(el => el.textContent || ""),
                  hasLongLabel: cells.some(el => el.textContent === "gemini-3.1-flash-lite"),
                  overflows,
                  gridWithinViewport: gridRect
                    ? gridRect.left >= -1 && gridRect.right <= window.innerWidth + 1
                    : false,
                };
              });
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await waitRpc(page);

              await page.evaluate(() => {
                localStorage.setItem(
                  "opensquilla-router-fx",
                  JSON.stringify({ enabled: true, variant: "default" })
                );
                window.__routerFxTest = {
                  sessionKey: "agent:main:webchat:router-fx-panel",
                  historyMessages: [],
                  chatCalls: [],
                  routerConfig: {
                    enabled: true,
                    rollout_phase: "full",
                    tiers: {
                      c1: { model: "openrouter/deepseek-v4-flash" },
                      c2: { model: "openrouter/gemini-3.1-flash-lite" },
                      c3: { model: "openrouter/qwen3.6-max" },
                      image_model: {
                        model: "openrouter/kimi-k2.6",
                        supports_image: true,
                        image_only: true,
                      },
                    },
                  },
                };
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: window.__routerFxTest.routerConfig,
                    });
                  }
                  if (method === "chat.history") {
                    if (window.__routerFxTest.deferHistory) {
                      return new Promise(resolve => {
                        window.__routerFxTest.resolveHistory = () => {
                          window.__routerFxTest.deferHistory = false;
                          resolve({
                            messages: window.__routerFxTest.historyMessages,
                            history_scope: "complete",
                            has_more: false,
                          });
                        };
                      });
                    }
                    return Promise.resolve({
                      messages: window.__routerFxTest.historyMessages,
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 100,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  if (method === "chat.send") {
                    window.__routerFxTest.chatCalls.push({ method, params });
                    return Promise.resolve({ task_id: "router-fx-task" });
                  }
                  return originalCall(method, params);
                };
              });

              await page.evaluate(() =>
                Router.navigate("/chat?session=agent:main:webchat:router-fx-panel")
              );
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.waitForFunction(
                () => document.querySelector("#toggle-router")?.checked === true,
                { timeout: 15000 }
              );

              await page.fill("#chat-textarea", "route this with a long label");
              await page.click("#chat-btn-send");
              await page.waitForSelector(".router-fx[data-live='true'][data-scanning='true']", {
                timeout: 5000,
              });
              const sessionKey = await page.locator("#chat-session-chip-key").innerText();
              await emit(page, "session.event.router_decision", {
                session_key: sessionKey,
                stream_seq: 101,
                tier: "c1",
                model: "openrouter/deepseek-v4-flash",
                routing_source: "squilla_router",
                routing_applied: true,
              });
              await page.waitForSelector(".router-fx[data-state='settled'] .router-fx-cell.win", {
                timeout: 5000,
              });
              const liveSettled = await snapshot(page);

              await page.evaluate(() => {
                window.__routerFxTest.historyMessages = [
                  {
                    role: "user",
                    text: "route this with a long label",
                    message_id: "router-fx-u1",
                    timestamp: "2026-05-30T00:00:00Z",
                  },
                  {
                    role: "assistant",
                    text: "done",
                    message_id: "router-fx-a1",
                    timestamp: "2026-05-30T00:00:01Z",
                    model: "openrouter/deepseek-v4-flash",
                    usage: {
                      model: "openrouter/deepseek-v4-flash",
                      routed_model: "openrouter/deepseek-v4-flash",
                      routed_tier: "c1",
                      routing_source: "squilla_router",
                      routing_applied: true,
                      input_tokens: 11,
                      output_tokens: 2,
                    },
                  },
                ];
                Router.navigate("/overview");
                Router.navigate("/chat?session=agent:main:webchat:router-fx-panel");
              });
              await page.waitForSelector(
                ".router-fx[data-render-mode='history'][data-state='settled']",
                { timeout: 15000 }
              );
              const reopened = await snapshot(page);

              await emit(page, "session.event.router_decision", {
                session_key: sessionKey,
                stream_seq: 102,
                tier: "c1",
                model: "openrouter/deepseek-v4-flash",
                routing_source: "squilla_router",
                routing_applied: true,
              }, { replayed: true });
              await page.waitForTimeout(700);
              const afterReplay = await snapshot(page);

              await page.setViewportSize({ width: 520, height: 720 });
              await page.waitForTimeout(300);
              const narrow = await snapshot(page);

              await page.setViewportSize({ width: 1280, height: 720 });
              await page.evaluate(() => {
                window.__routerFxTest.historyMessages = [
                  {
                    role: "user",
                    text: "first routed turn",
                    message_id: "router-fx-u-race-1",
                    timestamp: "2026-05-30T00:00:00Z",
                  },
                  {
                    role: "assistant",
                    text: "first done",
                    message_id: "router-fx-a-race-1",
                    timestamp: "2026-05-30T00:00:01Z",
                    model: "openrouter/deepseek-v4-flash",
                    usage: {
                      model: "openrouter/deepseek-v4-flash",
                      routed_model: "openrouter/deepseek-v4-flash",
                      routed_tier: "c1",
                      routing_source: "squilla_router",
                      routing_applied: true,
                      input_tokens: 11,
                      output_tokens: 2,
                    },
                  },
                ];
                Router.navigate("/overview");
                Router.navigate("/chat?session=agent:main:webchat:router-fx-panel");
              });
              await page.waitForFunction(
                () =>
                  document.querySelectorAll(".router-fx").length === 1 &&
                  document.querySelector(".router-fx-cell.win .nm")?.textContent ===
                    "deepseek-v4-flash",
                { timeout: 15000 }
              );
              await page.evaluate(() => {
                window.__routerFxTest.historyMessages = [
                  {
                    role: "user",
                    text: "first routed turn",
                    message_id: "router-fx-u-race-1",
                    timestamp: "2026-05-30T00:00:00Z",
                  },
                  {
                    role: "assistant",
                    text: "first done",
                    message_id: "router-fx-a-race-1",
                    timestamp: "2026-05-30T00:00:01Z",
                    model: "openrouter/deepseek-v4-flash",
                    usage: {
                      model: "openrouter/deepseek-v4-flash",
                      routed_model: "openrouter/deepseek-v4-flash",
                      routed_tier: "c1",
                      routing_source: "squilla_router",
                      routing_applied: true,
                      input_tokens: 11,
                      output_tokens: 2,
                    },
                  },
                  {
                    role: "user",
                    text: "second routed turn",
                    message_id: "router-fx-u-race-2",
                    timestamp: "2026-05-30T00:00:02Z",
                  },
                  {
                    role: "assistant",
                    text: "second done",
                    message_id: "router-fx-a-race-2",
                    timestamp: "2026-05-30T00:00:03Z",
                    model: "openrouter/gemini-3.1-flash-lite",
                    usage: {
                      model: "openrouter/gemini-3.1-flash-lite",
                      routed_model: "openrouter/gemini-3.1-flash-lite",
                      routed_tier: "c2",
                      routing_source: "squilla_router",
                      routing_applied: true,
                      input_tokens: 13,
                      output_tokens: 3,
                    },
                  },
                ];
                window.__routerFxTest.deferHistory = true;
                Router.navigate("/overview");
                Router.navigate("/chat?session=agent:main:webchat:router-fx-panel");
              });
              await emit(page, "session.event.router_decision", {
                session_key: sessionKey,
                stream_seq: 103,
                tier: "c2",
                model: "openrouter/gemini-3.1-flash-lite",
                routing_source: "squilla_router",
                routing_applied: true,
              }, { replayed: true });
              await page.waitForTimeout(250);
              const duringHistoryHydrationReplay = await snapshot(page);
              await page.evaluate(() => window.__routerFxTest.resolveHistory());
              await page.waitForFunction(
                () => {
                  const winners = Array.from(document.querySelectorAll(".router-fx"))
                    .map(el => el.querySelector(".router-fx-cell.win .nm")?.textContent || "");
                  return winners.length === 2 &&
                    winners.includes("deepseek-v4-flash") &&
                    winners.includes("gemini-3.1-flash-lite");
                },
                { timeout: 15000 }
              );
              await page.waitForTimeout(300);
              const afterHistoryHydrationReplay = await snapshot(page);

              await page.evaluate(() => {
                window.__routerFxTest.historyMessages = [
                  {
                    role: "user",
                    text: "describe image",
                    message_id: "router-fx-u-image",
                    timestamp: "2026-05-30T00:00:04Z",
                    attachments: [{
                      mime: "image/png",
                      type: "image/png",
                      name: "preview.png",
                      data: "data:image/png;base64,iVBORw0KGgo=",
                    }],
                  },
                  {
                    role: "assistant",
                    text: "image done",
                    message_id: "router-fx-a-image",
                    timestamp: "2026-05-30T00:00:05Z",
                    model: "openrouter/kimi-k2.6",
                    usage: {
                      model: "openrouter/kimi-k2.6",
                      routed_model: "openrouter/kimi-k2.6",
                      routed_tier: "image_model",
                      routing_source: "image_route",
                      routing_applied: true,
                      input_tokens: 21,
                      output_tokens: 5,
                    },
                  },
                ];
                Router.navigate("/overview");
                Router.navigate("/chat?session=agent:main:webchat:router-fx-panel");
              });
              await page.waitForFunction(
                () =>
                  document.querySelector(".msg.user .msg-attachments") &&
                  document.querySelectorAll(".router-fx").length === 0,
                { timeout: 15000 }
              );
              const singleImageCandidate = await snapshot(page);

              await page.evaluate(() => {
                window.__routerFxTest.routerConfig = {
                  enabled: true,
                  rollout_phase: "full",
                  tiers: {
                    t1: { model: "openrouter/shared-model" },
                    t2: { model: "other-provider/shared-model" },
                  },
                };
                window.__routerFxTest.historyMessages = [
                  {
                    role: "user",
                    text: "same model different provider",
                    message_id: "router-fx-u-same-display",
                    timestamp: "2026-05-30T00:00:06Z",
                  },
                  {
                    role: "assistant",
                    text: "same done",
                    message_id: "router-fx-a-same-display",
                    timestamp: "2026-05-30T00:00:07Z",
                    model: "openrouter/shared-model",
                    usage: {
                      model: "openrouter/shared-model",
                      routed_model: "openrouter/shared-model",
                      routed_tier: "t1",
                      routing_source: "squilla_router",
                      routing_applied: true,
                      input_tokens: 8,
                      output_tokens: 2,
                    },
                  },
                ];
                Router.navigate("/overview");
                Router.navigate("/chat?session=agent:main:webchat:router-fx-panel");
              });
              await page.waitForFunction(
                () =>
                  document.querySelector(".msg.user")?.textContent.includes(
                    "same model different provider"
                  ) &&
                  document.querySelectorAll(".router-fx").length === 0,
                { timeout: 15000 }
              );
              const sameDisplaySingleCandidate = await snapshot(page);

              const result = {
                liveSettled,
                reopened,
                afterReplay,
                narrow,
                duringHistoryHydrationReplay,
                afterHistoryHydrationReplay,
                singleImageCandidate,
                sameDisplaySingleCandidate,
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
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/"),
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
    assert payload["liveSettled"]["state"] == "settled"
    assert payload["liveSettled"]["renderMode"] == "live"
    assert payload["liveSettled"]["liveCount"] == 0
    assert payload["liveSettled"]["scanningCount"] == 0
    assert payload["liveSettled"]["selectorVisible"] == 0
    assert payload["liveSettled"]["winner"] == "deepseek-v4-flash"
    assert "Router selected deepseek-v4-flash" in payload["liveSettled"]["aria"]
    assert payload["liveSettled"]["cellCount"] == 3
    assert set(payload["liveSettled"]["cellLabels"]) == {
        "deepseek-v4-flash",
        "gemini-3.1-flash-lite",
        "qwen3.6-max",
    }
    assert "kimi-k2.6" not in payload["liveSettled"]["cellLabels"]

    for key in ("reopened", "afterReplay", "narrow"):
        snap = payload[key]
        assert snap["count"] == 1, snap
        assert snap["state"] == "settled", snap
        assert snap["renderMode"] == "history", snap
        assert snap["liveCount"] == 0, snap
        assert snap["scanningCount"] == 0, snap
        assert snap["selectorVisible"] == 0, snap
        assert snap["bursts"] == 0, snap
        assert snap["pinging"] == 0, snap
        assert snap["animations"] == [], snap
        assert snap["winner"] == "deepseek-v4-flash", snap
        assert snap["hasLongLabel"] is True, snap
        assert snap["cellCount"] == 3, snap
        assert "kimi-k2.6" not in snap["cellLabels"], snap
        assert snap["overflows"] == [], snap
        assert snap["gridWithinViewport"] is True, snap

    during = payload["duringHistoryHydrationReplay"]
    assert during["count"] in (0, 1), during
    if during["count"] == 1:
        assert during["winners"] == ["deepseek-v4-flash"], during
    assert during["liveCount"] == 0, during
    assert during["scanningCount"] == 0, during
    assert during["selectorVisible"] == 0, during
    assert during["animations"] == [], during

    after_hydration = payload["afterHistoryHydrationReplay"]
    assert after_hydration["count"] == 2, after_hydration
    assert after_hydration["renderMode"] == "history", after_hydration
    assert after_hydration["liveCount"] == 0, after_hydration
    assert after_hydration["scanningCount"] == 0, after_hydration
    assert after_hydration["selectorVisible"] == 0, after_hydration
    assert after_hydration["bursts"] == 0, after_hydration
    assert after_hydration["pinging"] == 0, after_hydration
    assert after_hydration["animations"] == [], after_hydration
    assert after_hydration["overflows"] == [], after_hydration
    assert set(after_hydration["winners"]) == {
        "deepseek-v4-flash",
        "gemini-3.1-flash-lite",
    }, after_hydration

    image_single = payload["singleImageCandidate"]
    assert image_single["count"] == 0, image_single
    assert image_single["cellCount"] == 0, image_single
    assert image_single["liveCount"] == 0, image_single
    assert image_single["scanningCount"] == 0, image_single

    same_display_single = payload["sameDisplaySingleCandidate"]
    assert same_display_single["count"] == 0, same_display_single
    assert same_display_single["cellCount"] == 0, same_display_single
    assert same_display_single["liveCount"] == 0, same_display_single
    assert same_display_single["scanningCount"] == 0, same_display_single


def test_webchat_large_paste_auto_attaches_text_in_real_browser(tmp_path: Path) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_large_paste_server.py"
    browser_script = tmp_path / "webui_large_paste_browser.js"
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

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await waitRpc(page);

              await page.evaluate(() => {
                window.__largePaste = { calls: [] };
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: { enabled: false, rollout_phase: "off", tiers: {} },
                    });
                  }
                  if (method === "chat.history") {
                    return Promise.resolve({
                      messages: [],
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 0,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  if (method === "chat.send") {
                    window.__largePaste.calls.push({ method, params });
                    return Promise.resolve({ task_id: "large-paste-task" });
                  }
                  return originalCall(method, params);
                };
              });

              await page.fill("#chat-textarea", "x".repeat(20000));
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () => window.__largePaste?.calls?.length === 1,
                null, { timeout: 5000 }
              );

              const payload = await page.evaluate(() => {
                const call = window.__largePaste.calls[0];
                const params = call.params;
                const attachment = params.attachments?.[0] || {};
                const attachmentData = String(attachment.data || "");
                const inputProvenance = params.inputProvenance || {};
                const inputNormalization = inputProvenance.input_normalization || {};
                let decodedAttachmentText = "";
                try {
                  const bytes = Uint8Array.from(atob(attachmentData), char =>
                    char.charCodeAt(0)
                  );
                  decodedAttachmentText = new TextDecoder().decode(bytes);
                } catch (_err) {
                  decodedAttachmentText = "";
                }
                const userBubbleText = document.querySelector(".msg.user")?.textContent || "";
                const attachmentText =
                  document.querySelector(".msg.user .msg-attachments")?.textContent || "";
                const attachmentChip = document.querySelector(".msg.user .msg-file-chip");
                return {
                  callMethod: call.method,
                  message: params.message,
                  messageLength: String(params.message || "").length,
                  attachmentCount: Array.isArray(params.attachments)
                    ? params.attachments.length
                    : 0,
                  attachmentName: attachment.name || "",
                  attachmentMime: attachment.mime || attachment.type || "",
                  attachmentDataLength: attachmentData.length,
                  attachmentDataLooksBase64: /^[A-Za-z0-9+/]+={0,2}$/.test(attachmentData),
                  attachmentDecodedLength: decodedAttachmentText.length,
                  attachmentDecodedMatchesPaste: decodedAttachmentText === "x".repeat(20000),
                  inputProvenanceKind: inputProvenance.kind || "",
                  inputProvenanceSource: inputProvenance.source || "",
                  inputNormalizationGuardAction: inputNormalization.guard_action || "",
                  inputNormalizationOriginalChars: inputNormalization.original_chars || 0,
                  inputNormalizationMaterialEstimatedTokens:
                    inputNormalization.material_estimated_tokens || 0,
                  inputNormalizationGeneratedAttachmentCount:
                    inputNormalization.generated_attachment_count || 0,
                  bubbleHasPlaceholder: userBubbleText.includes(
                    "Please process the attached pasted text."
                  ),
                  bubbleHasLongRawPaste: userBubbleText.includes("x".repeat(500)),
                  attachmentChipHasGeneratedName: attachmentText.includes("webchat-paste-"),
                  attachmentChipTag: attachmentChip?.tagName || "",
                  attachmentChipDownload: attachmentChip?.getAttribute("download") || "",
                  attachmentChipHref: attachmentChip?.getAttribute("href") || "",
                };
              });
              await page.evaluate((attachmentName) => {
                const rpc = App.getRpc();
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: { enabled: false, rollout_phase: "off", tiers: {} },
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 0,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  if (method === "chat.history") {
                    return Promise.resolve({
                      messages: [{
                        role: "user",
                        text: "Please process the attached pasted text.",
                        timestamp: new Date().toISOString(),
                        attachments: [{
                          sha256_ref: "d".repeat(64),
                          name: attachmentName,
                          mime: "text/plain",
                          size: 20000,
                          download_url:
                            `/api/v1/attachments/${"d".repeat(64)}`
                            + "?sessionKey=agent%3Amain%3Awebchat%3Atest"
                            + `&name=${encodeURIComponent(attachmentName)}`
                            + "&mime=text%2Fplain",
                        }],
                      }],
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  return Promise.resolve({});
                };
                ChatView.destroy();
                ChatView.render(document.getElementById("content"));
              }, payload.attachmentName);
              await page.waitForSelector(".msg.user .msg-file-chip[href^='/api/v1/attachments/']", {
                timeout: 5000,
              });
              const historyPayload = await page.evaluate(() => {
                const chip = document.querySelector(".msg.user .msg-file-chip");
                return {
                  tag: chip?.tagName || "",
                  download: chip?.getAttribute("download") || "",
                  href: chip?.getAttribute("href") || "",
                };
              });
              Object.assign(payload, {
                historyAttachmentChipTag: historyPayload.tag,
                historyAttachmentChipDownload: historyPayload.download,
                historyAttachmentChipHref: historyPayload.href,
              });
              payload.pageErrors = errors;

              await browser.close();
              console.log(JSON.stringify(payload));
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

    assert payload["callMethod"] == "chat.send", payload
    assert payload["message"] == "Please process the attached pasted text.", payload
    assert payload["messageLength"] < 20000, payload
    assert payload["attachmentCount"] == 1, payload
    assert payload["attachmentName"].startswith("webchat-paste-"), payload
    assert payload["attachmentName"].endswith(".txt"), payload
    assert payload["attachmentMime"] == "text/plain", payload
    assert payload["attachmentDataLength"] > 1000, payload
    assert payload["attachmentDataLooksBase64"] is True, payload
    assert payload["attachmentDecodedLength"] == 20000, payload
    assert payload["attachmentDecodedMatchesPaste"] is True, payload
    assert payload["inputProvenanceKind"] == "web_message", payload
    assert payload["inputProvenanceSource"] == "WebChat", payload
    assert payload["inputNormalizationGuardAction"] == "generated_text_attachment", payload
    assert payload["inputNormalizationOriginalChars"] == 20000, payload
    assert payload["inputNormalizationMaterialEstimatedTokens"] == 5000, payload
    assert payload["inputNormalizationGeneratedAttachmentCount"] == 1, payload
    assert payload["bubbleHasPlaceholder"] is True, payload
    assert payload["bubbleHasLongRawPaste"] is False, payload
    assert payload["attachmentChipHasGeneratedName"] is True, payload
    assert payload["attachmentChipTag"] == "A", payload
    assert payload["attachmentChipDownload"].startswith("webchat-paste-"), payload
    assert payload["attachmentChipHref"].startswith("data:text/plain;base64,"), payload
    assert payload["historyAttachmentChipTag"] == "A", payload
    assert payload["historyAttachmentChipDownload"].startswith("webchat-paste-"), payload
    assert payload["historyAttachmentChipHref"].startswith("/api/v1/attachments/"), payload
    assert payload["pageErrors"] == [], payload


def test_image_paste_consumes_attachment_without_inserting_wsl_path_text_in_real_browser(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_image_paste_server.py"
    browser_script = tmp_path / "webui_image_paste_browser.js"
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

            async function dispatchSyntheticPaste(page, { includeImage, text }) {
              return await page.evaluate(async ({ includeImage, text }) => {
                const textarea = document.querySelector("#chat-textarea");
                const items = [];
                if (includeImage) {
                  const b64 =
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lHE7+QAAAABJRU5ErkJggg==";
                  const bytes = Uint8Array.from(atob(b64), ch => ch.charCodeAt(0));
                  const file = new File([bytes], "361d381f.png", { type: "image/png" });
                  items.push({
                    type: "image/png",
                    getAsFile: () => file,
                  });
                }
                items.push({
                  type: "text/plain",
                  getAsFile: () => null,
                });
                const event = new Event("paste", { bubbles: true, cancelable: true });
                Object.defineProperty(event, "clipboardData", {
                  value: {
                    items,
                    getData: type => (type === "text/plain" ? text : ""),
                  },
                });
                document.dispatchEvent(event);
                if (!event.defaultPrevented) {
                  textarea.value += text;
                  textarea.dispatchEvent(new Event("input", { bubbles: true }));
                }
                await new Promise(resolve => setTimeout(resolve, 250));
                return {
                  defaultPrevented: event.defaultPrevented,
                  textareaValue: textarea.value,
                  previewHidden: document
                    .querySelector("#chat-attach-preview")
                    ?.classList.contains("hidden"),
                  attachmentThumbs: document
                    .querySelectorAll("#chat-attach-preview .attachment-thumb")
                    .length,
                  attachmentChips: document
                    .querySelectorAll("#chat-attach-preview .attachment-chip")
                    .length,
                };
              }, { includeImage, text });
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await waitRpc(page);

              const wslPath = "/tmp/.wsl-screenshot-cli/"
                + "361d381f306061eb91d29b48ca876da8ab0ee3374a57bcfaa9212c3b7105858.png";
              const imagePaste = await dispatchSyntheticPaste(page, {
                includeImage: true,
                text: wslPath,
              });

              await page.locator(".attachment-remove").click();
              await page.fill("#chat-textarea", "");

              const textOnlyPaste = await dispatchSyntheticPaste(page, {
                includeImage: false,
                text: wslPath,
              });

              await browser.close();
              console.log(JSON.stringify({
                imagePaste,
                textOnlyPaste,
                pageErrors: errors,
              }));
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

    assert payload["imagePaste"]["defaultPrevented"] is True, payload
    assert payload["imagePaste"]["textareaValue"] == "", payload
    assert payload["imagePaste"]["previewHidden"] is False, payload
    assert payload["imagePaste"]["attachmentThumbs"] == 1, payload
    assert payload["textOnlyPaste"]["defaultPrevented"] is False, payload
    assert payload["textOnlyPaste"]["textareaValue"].startswith(
        "/tmp/.wsl-screenshot-cli/"
    ), payload
    assert payload["pageErrors"] == [], payload


def test_chat_image_attachment_layout_stays_aligned_in_real_browser(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_image_attachment_layout_server.py"
    browser_script = tmp_path / "webui_image_attachment_layout_browser.js"
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

            async function installMocks(page) {
              await page.evaluate(() => {
                window.__attachmentLayout = { sends: [] };
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: { enabled: false, rollout_phase: "off", tiers: {} },
                    });
                  }
                  if (method === "chat.history") {
                    return Promise.resolve({
                      messages: [],
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 0,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  if (method === "chat.send") {
                    window.__attachmentLayout.sends.push(params);
                    return Promise.resolve({ task_id: "attachment-layout-task" });
                  }
                  return originalCall(method, params);
                };
              });
            }

            async function pasteWideImage(page) {
              await page.evaluate(async () => {
                const canvas = document.createElement("canvas");
                canvas.width = 1600;
                canvas.height = 120;
                const ctx = canvas.getContext("2d");
                ctx.fillStyle = "#101014";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = "#ff6a00";
                ctx.fillRect(0, 54, canvas.width, 12);
                ctx.fillStyle = "#ffffff";
                ctx.font = "28px sans-serif";
                ctx.fillText("ultra wide screenshot", 40, 48);
                const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
                const file = new File([blob], "wide-screenshot.png", { type: "image/png" });
                const event = new Event("paste", { bubbles: true, cancelable: true });
                Object.defineProperty(event, "clipboardData", {
                  value: {
                    items: [
                      { type: "image/png", getAsFile: () => file },
                    ],
                    getData: () => "",
                  },
                });
                document.dispatchEvent(event);
              });
              await page.waitForSelector("#chat-attach-preview:not(.hidden) .attachment-thumb", {
                timeout: 5000,
              });
            }

            async function measure(page, viewport) {
              await page.setViewportSize({ width: viewport.width, height: viewport.height });
              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await waitRpc(page);
              await installMocks(page);
              await page.evaluate(() =>
                Router.navigate("/chat?session=agent:main:webchat:attachment-layout")
              );
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await pasteWideImage(page);
              const pending = await page.evaluate(() => {
                const box = (selector) => {
                  const el = document.querySelector(selector);
                  const r = el.getBoundingClientRect();
                  return {
                    left: r.left,
                    right: r.right,
                    top: r.top,
                    bottom: r.bottom,
                    width: r.width,
                    height: r.height,
                    visible:
                      r.width > 0 &&
                      r.height > 0 &&
                      getComputedStyle(el).display !== "none" &&
                      getComputedStyle(el).visibility !== "hidden",
                  };
                };
                return {
                  width: window.innerWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  preview: box("#chat-attach-preview"),
                  input: box(".chat-input-bar"),
                  composer: box("#chat-composer"),
                  thumb: box("#chat-attach-preview .attachment-thumb"),
                  remove: box("#chat-attach-preview .attachment-remove"),
                };
              });

              await page.locator("#chat-textarea").fill("这是什么");
              await page.locator("#chat-btn-send").click();
              await page.waitForFunction(
                () => window.__attachmentLayout?.sends?.length === 1,
                { timeout: 5000 }
              );
              await page.waitForSelector(".msg.user .msg-thumb", { timeout: 5000 });
              const sent = await page.evaluate(() => {
                const box = (selector) => {
                  const el = document.querySelector(selector);
                  const r = el.getBoundingClientRect();
                  return {
                    left: r.left,
                    right: r.right,
                    top: r.top,
                    bottom: r.bottom,
                    width: r.width,
                    height: r.height,
                    visible:
                      r.width > 0 &&
                      r.height > 0 &&
                      getComputedStyle(el).display !== "none" &&
                      getComputedStyle(el).visibility !== "hidden",
                  };
                };
                return {
                  width: window.innerWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  body: box(".msg.user .msg-body--has-attachments"),
                  text: box(".msg.user .msg-attachment-text"),
                  attachments: box(".msg.user .msg-attachments"),
                  thumb: box(".msg.user .msg-thumb"),
                  sendAttachmentCount: window.__attachmentLayout.sends[0].attachments?.length || 0,
                  sendMessage: window.__attachmentLayout.sends[0].message || "",
                };
              });
              return { name: viewport.name, pending, sent };
            }

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage();
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));
              const viewports = [
                { name: "desktop", width: 1365, height: 768 },
                { name: "wide", width: 2048, height: 900 },
                { name: "mobile", width: 390, height: 844 },
              ];
              const layouts = [];
              for (const viewport of viewports) layouts.push(await measure(page, viewport));
              await browser.close();
              console.log(JSON.stringify({ layouts, pageErrors: errors }));
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

    assert payload["pageErrors"] == []
    layouts = {item["name"]: item for item in payload["layouts"]}
    for name, item in layouts.items():
        pending = item["pending"]
        sent = item["sent"]
        assert pending["scrollWidth"] <= pending["width"], (name, pending)
        assert sent["scrollWidth"] <= sent["width"], (name, sent)
        assert pending["preview"]["visible"], (name, pending)
        assert pending["remove"]["visible"], (name, pending)
        assert pending["preview"]["left"] >= 0, (name, pending)
        assert pending["preview"]["right"] <= pending["width"], (name, pending)
        assert pending["thumb"]["right"] <= pending["preview"]["right"], (name, pending)
        assert sent["sendAttachmentCount"] == 1, (name, sent)
        assert sent["sendMessage"] == "这是什么", (name, sent)
        assert sent["text"]["right"] <= sent["body"]["right"] + 1, (name, sent)
        assert sent["thumb"]["width"] <= 280, (name, sent)
        assert sent["thumb"]["height"] <= 160, (name, sent)
        assert sent["thumb"]["right"] <= sent["width"], (name, sent)
        assert sent["attachments"]["right"] <= sent["body"]["right"] + 1, (name, sent)
        if name == "mobile":
            assert pending["preview"]["left"] >= pending["composer"]["left"], (name, pending)
            assert pending["preview"]["right"] <= pending["composer"]["right"], (name, pending)
        else:
            assert abs(pending["preview"]["left"] - pending["input"]["left"]) <= 1, (
                name,
                pending,
            )
            assert abs(pending["preview"]["right"] - pending["input"]["right"]) <= 1, (
                name,
                pending,
            )


def test_completed_reconnect_without_replay_refreshes_history_in_real_browser(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_completed_reconnect_server.py"
    browser_script = tmp_path / "webui_completed_reconnect_browser.js"
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

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await waitRpc(page);

              await page.evaluate(() => {
                window.__completedReconnectTest = {
                  sessionKey: "agent:main:webchat:completed-reconnect",
                  subscribeCalls: 0,
                  historyCalls: 0,
                  historyMessages: [
                    {
                      role: "user",
                      text: "late single chunk",
                      message_id: "completed-reconnect-u1",
                      timestamp: "2026-05-31T00:38:14Z",
                    },
                  ],
                };
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: {
                        enabled: true,
                        rollout_phase: "full",
                        tiers: {
                          c1: { model: "openrouter/deepseek-v4-flash" },
                        },
                      },
                    });
                  }
                  if (method === "chat.history") {
                    window.__completedReconnectTest.historyCalls += 1;
                    return Promise.resolve({
                      messages: window.__completedReconnectTest.historyMessages,
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    window.__completedReconnectTest.subscribeCalls += 1;
                    return new Promise(resolve => {
                      setTimeout(() => {
                        window.__completedReconnectTest.historyMessages = [
                          {
                            role: "user",
                            text: "late single chunk",
                            message_id: "completed-reconnect-u1",
                            timestamp: "2026-05-31T00:38:14Z",
                          },
                          {
                            role: "assistant",
                            text:
                              "未能解析回复：\n  - field 'intent': " +
                              "'不要用这个skill实施' not in choices",
                            message_id: "completed-reconnect-a1",
                            timestamp: "2026-05-31T00:38:28Z",
                            model: "openrouter/deepseek-v4-flash",
                            usage: {
                              model: "openrouter/deepseek-v4-flash",
                              routed_model: "openrouter/deepseek-v4-flash",
                              routed_tier: "c1",
                              routing_source: "squilla_router",
                              routing_applied: true,
                              input_tokens: 0,
                              output_tokens: 0,
                            },
                          },
                        ];
                        resolve({
                          subscribed: true,
                          key: params.key,
                          current_stream_seq: 0,
                          replay_complete: true,
                          replayed_count: 0,
                          run_status: "idle",
                          last_task: {
                            task_id: "completed-reconnect-task",
                            status: "succeeded",
                            terminal_reason: "completed",
                          },
                        });
                      }, 800);
                    });
                  }
                  return originalCall(method, params);
                };
              });

              await page.evaluate(() =>
                Router.navigate("/chat?session=agent:main:webchat:completed-reconnect")
              );
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });
              await page.waitForFunction(
                () =>
                  document.querySelector(".msg.user")?.textContent.includes(
                    "late single chunk"
                  ),
                null, { timeout: 5000 }
              );
              const userOnly = await page.evaluate(() => ({
                assistantHasReply: Array.from(document.querySelectorAll(".msg.assistant"))
                  .some(el => el.textContent.includes("未能解析回复")),
                historyCalls: window.__completedReconnectTest.historyCalls,
                subscribeCalls: window.__completedReconnectTest.subscribeCalls,
              }));

              await page.waitForFunction(
                () => Array.from(document.querySelectorAll(".msg.assistant"))
                  .some(el => el.textContent.includes("未能解析回复")),
                null, { timeout: 5000 }
              );
              const afterTerminalSubscribe = await page.evaluate(() => ({
                assistantHasReply: Array.from(document.querySelectorAll(".msg.assistant"))
                  .some(el => el.textContent.includes("未能解析回复")),
                thinkingCount: document.querySelectorAll(".msg.thinking").length,
                streamingCount: document.querySelectorAll(".msg.streaming").length,
                routerWinner: document.querySelector(".router-fx-cell.win .nm")?.textContent || "",
                historyCalls: window.__completedReconnectTest.historyCalls,
                subscribeCalls: window.__completedReconnectTest.subscribeCalls,
              }));

              await browser.close();
              console.log(JSON.stringify({
                userOnly,
                afterTerminalSubscribe: {
                  ...afterTerminalSubscribe,
                  pageErrors: errors,
                },
              }));
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
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/"),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload["userOnly"]["assistantHasReply"] is False, payload
    after = payload["afterTerminalSubscribe"]
    assert after["assistantHasReply"] is True, after
    assert after["thinkingCount"] == 0, after
    assert after["streamingCount"] == 0, after
    assert after["routerWinner"] == "deepseek-v4-flash", after
    assert after["historyCalls"] >= 2, after
    assert after["pageErrors"] == [], after


def test_replayed_savings_done_restores_reply_without_replaying_popup_in_real_browser(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E") != "1":
        pytest.skip("set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run chat browser e2e")

    port = _free_port()
    server_script = tmp_path / "webui_savings_replay_server.py"
    browser_script = tmp_path / "webui_savings_replay_browser.js"
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

            (async () => {
              const browser = await chromium.launch({ headless: true });
              const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
              const errors = [];
              page.on("pageerror", err => errors.push(String(err)));

              await page.goto(process.env.TARGET_URL, {
                waitUntil: "domcontentloaded",
                timeout: 30000,
              });
              await waitRpc(page);

              await page.evaluate(() => {
                window.__savingsReplayTest = {
                  fireCalls: 0,
                  sessionKey: "agent:main:webchat:savings-replay",
                };
                const originalFire = window.SavingsFX.fire.bind(window.SavingsFX);
                window.SavingsFX.fire = (...args) => {
                  window.__savingsReplayTest.fireCalls += 1;
                  return originalFire(...args);
                };
                const rpc = App.getRpc();
                const originalCall = rpc.call.bind(rpc);
                rpc.call = (method, params = {}) => {
                  if (method === "tools.search_provider") {
                    return Promise.resolve({ provider: "none" });
                  }
                  if (method === "config.get") {
                    return Promise.resolve({
                      permissions: { default_mode: "ask" },
                      squilla_router: {
                        enabled: true,
                        rollout_phase: "full",
                        tiers: {
                          c1: { model: "openrouter/deepseek-v4-flash" },
                        },
                      },
                    });
                  }
                  if (method === "chat.history") {
                    return Promise.resolve({
                      messages: [],
                      history_scope: "complete",
                      has_more: false,
                    });
                  }
                  if (method === "sessions.messages.subscribe") {
                    return Promise.resolve({
                      subscribed: true,
                      key: params.key,
                      current_stream_seq: 0,
                      replay_complete: true,
                      replayed_count: 0,
                      run_status: "idle",
                    });
                  }
                  return originalCall(method, params);
                };
              });

              await page.evaluate(() =>
                Router.navigate("/chat?session=agent:main:webchat:savings-replay")
              );
              await page.waitForSelector("#chat-textarea", { timeout: 15000 });

              await page.evaluate(() => {
                const rpc = App.getRpc();
                const ls = rpc._listeners;
                const sessionKey = window.__savingsReplayTest.sessionKey;
                const deltaHandlers = ls.get("session.event.text_delta");
                if (deltaHandlers) {
                  deltaHandlers.forEach(h => h({
                    session_key: sessionKey,
                    stream_seq: 41,
                    text: "replayed savings answer",
                  }));
                }
                const wildHandlers = ls.get("*");
                if (wildHandlers) {
                  wildHandlers.forEach(h => h("session.event.done", {
                    session_key: sessionKey,
                    stream_seq: 42,
                    text: "replayed savings answer",
                    input_tokens: 17800,
                    output_tokens: 661,
                    model: "openrouter/deepseek-v4-flash",
                    routed_model: "openrouter/deepseek-v4-flash",
                    routed_tier: "c1",
                    routing_source: "squilla_router",
                    routing_applied: true,
                    total_savings_pct: 97,
                    total_savings_usd: 0.01,
                  }, { replayed: true }));
                }
              });

              await page.waitForFunction(
                () => Array.from(document.querySelectorAll(".msg.assistant"))
                  .some(el => el.textContent.includes("replayed savings answer")),
                null, { timeout: 5000 }
              );
              await page.waitForTimeout(300);
              const payload = await page.evaluate(() => ({
                assistantHasReply: Array.from(document.querySelectorAll(".msg.assistant"))
                  .some(el => el.textContent.includes("replayed savings answer")),
                savedChipVisible: Array.from(document.querySelectorAll(".msg-meta__saved"))
                  .some(el => el.textContent.includes("Saved")),
                fireCalls: window.__savingsReplayTest.fireCalls,
                floatingLabels: document.querySelectorAll(".savings-float").length,
              }));

              await browser.close();
              console.log(JSON.stringify({ ...payload, pageErrors: errors }));
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
            env=dict(env, TARGET_URL=f"http://127.0.0.1:{port}/control/"),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _stop_process(server)

    assert payload["assistantHasReply"] is True, payload
    assert payload["savedChipVisible"] is True, payload
    assert payload["fireCalls"] == 0, payload
    assert payload["floatingLabels"] == 0, payload
    assert payload["pageErrors"] == [], payload


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
              await emit(page, "sessions.changed", {
                key: sessionKey,
                run_status: "running",
                active_task: { task_id: "running-task", status: "running" },
                reason: "task_running",
              });
              await page.waitForFunction(
                () => document.querySelector("#chat-run-status")?.innerText === "Running",
                null, { timeout: 5000 }
              );
              await emit(page, "task.queued", {
                task_id: "queued-behind-running",
                session_key: sessionKey,
                queue_depth: 1,
                queue_position: 2,
              });
              await page.waitForTimeout(150);
              const statusAfterQueuedBehindRunning =
                await page.locator("#chat-run-status").innerText();
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
                null, { timeout: 5000 }
              );
              await emit(page, "session.event.done", { text: "first answer" });
              await page.waitForFunction(
                () => document.querySelectorAll(".msg.assistant").length >= 1,
                null, { timeout: 5000 }
              );

              await page.fill("#chat-textarea", "second prompt");
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () => window.__hotfix.chatCalls.some(c => c.params.message === "second prompt"),
                null, { timeout: 5000 }
              );
              await emit(page, "session.event.done", { text: "second answer" });
              await page.waitForFunction(
                () => document.querySelectorAll(".msg.assistant").length >= 2,
                null, { timeout: 5000 }
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
                null, { timeout: 5000 }
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
                null, { timeout: 5000 }
              );
              const draftAfterQueueDrain = await page.locator("#chat-textarea").inputValue();

              await page.fill("#chat-textarea", "queued from terminal session change");
              await page.click("#chat-btn-send");
              await emit(page, "sessions.changed", {
                key: sessionKey,
                run_status: "idle",
                last_task: { status: "succeeded" },
                reason: "turn_complete",
              });
              await page.waitForFunction(
                () =>
                  window.__hotfix.chatCalls
                    .some(c => c.params.message === "queued from terminal session change"),
                null, { timeout: 5000 }
              );
              await emit(page, "session.event.done", { text: "terminal queued answer" });
              await page.waitForFunction(
                () => document.querySelector("#chat-run-status")?.innerText === "Idle",
                null, { timeout: 5000 }
              );

              await page.fill("#chat-textarea", "first before error");
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () => window.__hotfix.chatCalls
                  .some(c => c.params.message === "first before error"),
                null, { timeout: 5000 }
              );
              await page.fill("#chat-textarea", "queued before error");
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () => document.querySelector("#chat-pending")
                  ?.innerText.includes("queued before error"),
                null, { timeout: 5000 }
              );
              const queuedBeforeErrorSentPrematurely = await page.evaluate(
                () => window.__hotfix.chatCalls
                  .some(c => c.params.message === "queued before error")
              );
              await emit(page, "session.event.error", {
                session_key: sessionKey,
                message: "synthetic failure",
                code: "failed",
              });
              await page.waitForFunction(
                () => document.querySelector("#chat-textarea")
                  ?.value.includes("queued before error"),
                null, { timeout: 5000 }
              );
              const errorRecoveredComposer = await page.locator("#chat-textarea").inputValue();
              const queuedBeforeErrorSentAfterFailure = await page.evaluate(
                () => window.__hotfix.chatCalls
                  .some(c => c.params.message === "queued before error")
              );
              await page.fill("#chat-textarea", "");

              await page.fill("#chat-textarea", "approval turn");
              await page.click("#chat-btn-send");
              await page.waitForFunction(
                () => window.__hotfix.chatCalls.some(c => c.params.message === "approval turn"),
                null, { timeout: 5000 }
              );
              await page.evaluate((sessionKey) => {
                window.dispatchEvent(new CustomEvent("opensquilla:approvals-pending", {
                  detail: {
                    pending: [{ id: "approval-1", namespace: "exec", sessionKey }],
                    count: 1,
                  },
                }));
              }, sessionKey);
              await page.waitForFunction(
                () => document.querySelector("#chat-run-status")
                  ?.innerText === "Waiting for approval",
                null, { timeout: 5000 }
              );
              const approvalStatusDuring = await page.locator("#chat-run-status").innerText();
              await page.evaluate(() => {
                window.dispatchEvent(new CustomEvent("opensquilla:approvals-pending", {
                  detail: { pending: [], count: 0 },
                }));
              });
              await page.waitForFunction(
                () => document.querySelector("#chat-run-status")?.innerText === "Running",
                null, { timeout: 5000 }
              );
              const approvalStatusAfterResolve = await page.locator("#chat-run-status").innerText();
              await emit(page, "session.event.done", { text: "approval answer" });
              await page.waitForFunction(
                () => document.querySelector("#chat-run-status")?.innerText === "Idle",
                null, { timeout: 5000 }
              );

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
                null, { timeout: 5000 }
              );
              const sessionDeleteBody = await page.locator("body").innerText();

              await page.evaluate(() => Router.navigate("/logs"));
              await page.waitForSelector("#logs-display", { timeout: 15000 });
              await page.waitForFunction(
                () => document.body.innerText.includes("Log refresh failed"),
                null, { timeout: 5000 }
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
                statusAfterQueuedBehindRunning,
                regenerateMessages,
                bubblesAfterRegenerate,
                draftAfterQueueDrain,
                queuedBeforeErrorSentPrematurely,
                errorRecoveredComposer,
                queuedBeforeErrorSentAfterFailure,
                approvalStatusDuring,
                approvalStatusAfterResolve,
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
    assert payload["statusAfterQueuedBehindRunning"] == "Running"
    assert payload["regenerateMessages"].count("first prompt") >= 2
    first_regenerate = payload["regenerateMessages"].index("first prompt")
    second_send = payload["regenerateMessages"].index("second prompt")
    assert first_regenerate < second_send
    assert payload["bubblesAfterRegenerate"] <= 3
    assert payload["draftAfterQueueDrain"] == "draft typed during stream"
    assert payload["queuedBeforeErrorSentPrematurely"] is False
    assert "queued before error" in payload["errorRecoveredComposer"]
    assert payload["queuedBeforeErrorSentAfterFailure"] is False
    assert payload["approvalStatusDuring"] == "Waiting for approval"
    assert payload["approvalStatusAfterResolve"] == "Running"
    assert payload["yamlDraftPreserved"] is True
    assert payload["configResetToForm"] is True
    assert payload["channelStatusCallsAfterDestroyedWait"] == 0
    assert payload["sessionDeleteFailed"] is True
    assert payload["sessionDeleteFalseSuccess"] is False
    assert payload["logState"]["tailCalls"] >= 2
    assert payload["logState"]["maxInFlight"] == 1
