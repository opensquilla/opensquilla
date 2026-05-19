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
from _webui_browser_playwright import install_playwright, node_command

pytestmark = pytest.mark.webui_browser


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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
        install_playwright(tmp_path)
        result = subprocess.run(
            [node_command(), str(browser_script)],
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
