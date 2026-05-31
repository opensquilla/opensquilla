#!/usr/bin/env python3
"""Live long-context WebChat smoke.

Opt-in maintainer gate. Requires OPENROUTER_API_KEY and starts a temporary
gateway against a temporary state dir. The smoke verifies that WebChat accepts
and completes a turn whose current user input is far above the gateway soft
context budget, instead of returning a synchronous context-overflow refusal.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path
from typing import Any

_THIS_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_THIS_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_THIS_REPO_ROOT))

from scripts.smoke_v4_phase3_router import (  # noqa: E402
    REPO_ROOT,
    SRC_DIR,
    _free_port,
    _post_json,
    _read_json,
    _read_turn_call_records,
    _summarize_llm_request_context,
    _wait_for_assistant_reply,
    _write_live_gateway_config,
)


def _long_message(marker: str, chars: int) -> str:
    filler = "\n".join(
        f"long-context-line-{index:05d}: preserve liveness while compacting history."
        for index in range(max(chars // 72, 1))
    )
    return (
        f"Reply with one short sentence and include marker {marker}. Do not call tools.\n"
        f"{filler}\n"
        f"Final reminder: the reply must include {marker}."
    )


def _enable_memory_distill_failure_simulation(config_path: Path) -> None:
    text = config_path.read_text(encoding="utf-8")
    text = text.replace(
        'debug = false\n',
        'debug = false\ncontext_budget_tokens = 256\n',
        1,
    )
    text = text.replace(
        '[memory]\nsource = "state"\n',
        (
            '[memory]\n'
            'source = "state"\n'
            'flush_enabled = true\n'
            'flush_timeout_seconds = 0.001\n'
            'flush_background_timeout_seconds = 0.001\n'
            'flush_compaction_requires_safe_receipt = false\n'
            'flush_compaction_safety_mode = "protect"\n'
        ),
        1,
    )
    config_path.write_text(text, encoding="utf-8")


def _blocking_memory_errors(turns: list[dict[str, Any]]) -> list[str]:
    blocked: list[str] = []
    needles = ("flush failed", "bad json", "memory distill failed")
    for turn in turns:
        accepted = str(turn.get("accepted") or "").lower()
        if any(needle in accepted for needle in needles):
            blocked.append(str(turn.get("name") or turn.get("index") or "unknown"))
    return blocked


def run_live_long_context_smoke(
    *,
    long_chars: int,
    timeout_seconds: float,
    simulate_memory_distill_failure: bool = False,
) -> dict[str, Any]:
    if not os.environ.get("OPENROUTER_API_KEY"):
        return {
            "name": "opensquilla_gateway_live_long_context_chat",
            "ok": False,
            "error": "OPENROUTER_API_KEY is required",
        }

    port = _free_port()
    live_model = os.environ.get("OPENSQUILLA_LIVE_LLM_MODEL", "").strip()
    session_key = f"live-long-context:{int(time.time() * 1000)}"
    turns_spec = [
        {
            "message": (
                "Long-context baseline turn: reply with one short sentence. Do not call tools."
            ),
            "intent": "new_chat",
            "name": "baseline",
        },
        {
            "message": _long_message("LONG_CONTEXT_CONTINUES", long_chars),
            "intent": "continue",
            "name": "oversized_current_input",
        },
    ]

    with tempfile.TemporaryDirectory(
        prefix="opensquilla-live-long-context-",
        ignore_cleanup_errors=True,
    ) as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "live-config.toml"
        turn_log_dir = tmp_path / "turn-calls"
        _write_live_gateway_config(config_path, live_model)
        if simulate_memory_distill_failure:
            _enable_memory_distill_failure_simulation(config_path)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        env["OPENSQUILLA_GATEWAY_CONFIG_PATH"] = str(config_path)
        env["OPENSQUILLA_STATE_DIR"] = str(tmp_path / "state")
        env["OPENSQUILLA_MEMORY_DREAM_DISABLED"] = "1"
        env["OPENSQUILLA_SANDBOX_SANDBOX"] = "false"
        env["OPENSQUILLA_SANDBOX_SECURITY_GRADING"] = "false"
        env["OPENSQUILLA_TURN_CALL_LOG"] = "1"
        env["OPENSQUILLA_TURN_CALL_LOG_DIR"] = str(turn_log_dir)
        if simulate_memory_distill_failure:
            env["OPENSQUILLA_SESSION_FLUSH"] = "1"

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "opensquilla.cli.main",
                "gateway",
                "run",
                "--port",
                str(port),
                "--bind",
                "127.0.0.1",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        turns: list[dict[str, Any]] = []
        health: dict[str, Any] | None = None
        usage: dict[str, Any] = {}
        error: str | None = None
        stdout_tail = ""
        stderr_tail = ""
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    stdout, stderr = proc.communicate(timeout=1)
                    error = f"gateway exited early with code {proc.returncode}: {stderr or stdout}"
                    break
                try:
                    health = _read_json(f"http://127.0.0.1:{port}/health")
                    break
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                    time.sleep(0.25)
            if health is None and error is None:
                error = "gateway did not become healthy before timeout"

            assistant_count = 0
            if error is None:
                for index, spec in enumerate(turns_spec, start=1):
                    accepted = _post_json(
                        f"http://127.0.0.1:{port}/api/chat",
                        {
                            "sessionKey": session_key,
                            "message": spec["message"],
                            "intent": spec["intent"],
                        },
                        timeout=20.0,
                    )
                    if accepted.get("ok") is not True:
                        error = f"turn {index} was not accepted: {accepted}"
                        break
                    assistant, history, turn_error = _wait_for_assistant_reply(
                        port=port,
                        session_key=session_key,
                        previous_assistant_count=assistant_count,
                        timeout_seconds=timeout_seconds,
                    )
                    if turn_error:
                        error = f"turn {index} failed: {turn_error}"
                        break
                    assistant_count += 1
                    turns.append(
                        {
                            "index": index,
                            "name": spec["name"],
                            "accepted": accepted,
                            "assistant_text": str((assistant or {}).get("text", "")).strip(),
                            "history_message_count": len((history or {}).get("messages", [])),
                            "message_chars": len(spec["message"]),
                        }
                    )
                if error is None:
                    usage = _read_json(f"http://127.0.0.1:{port}/api/usage", timeout=5.0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            stdout, stderr = proc.communicate(timeout=1)
            stdout_tail = (stdout or "")[-2000:]
            stderr_tail = (stderr or "")[-2000:]
            turn_call_records = _read_turn_call_records(turn_log_dir)

    context_summary = _summarize_llm_request_context(
        turn_call_records,
        session_keys={session_key},
    )
    blocking_memory_errors = _blocking_memory_errors(turns)
    ok = (
        error is None
        and len(turns) == len(turns_spec)
        and all(turn.get("assistant_text") for turn in turns)
        and int(usage.get("totalTokens", 0) or 0) > 0
        and not blocking_memory_errors
    )
    return {
        "name": "opensquilla_gateway_live_long_context_chat",
        "ok": ok,
        "session_key": session_key,
        "model": live_model,
        "long_chars": long_chars,
        "simulate_memory_distill_failure": simulate_memory_distill_failure,
        "blocking_memory_errors": blocking_memory_errors,
        "health": health or {},
        "turns": turns,
        "usage": usage,
        "llm_request_context_summary": context_summary,
        "error": error,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long-chars", type=int, default=350_000)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--simulate-memory-distill-failure",
        action="store_true",
        help=(
            "Lower the context budget and flush timeouts so pre-compaction "
            "memory distill cannot block WebChat sendability."
        ),
    )
    args = parser.parse_args()

    result = run_live_long_context_smoke(
        long_chars=max(args.long_chars, 1),
        timeout_seconds=max(args.timeout_seconds, 1.0),
        simulate_memory_distill_failure=args.simulate_memory_distill_failure,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
