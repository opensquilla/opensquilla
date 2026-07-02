#!/usr/bin/env python3
"""Live smoke for the openai_codex (ChatGPT OAuth) provider.

Gated on the Codex CLI auth file existing (``$CODEX_HOME/auth.json`` or
``~/.codex/auth.json``); exits 2 with guidance when it does not. Runs one
text turn and one tool-call turn against the real ChatGPT backend and
prints a compact JSON verdict. No secrets are printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from opensquilla.provider.codex_auth import CodexAuthError, codex_auth_path, load_codex_credentials
from opensquilla.provider.openai_codex import OpenAICodexProvider
from opensquilla.provider.types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ReasoningDeltaEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
    ToolUseEndEvent,
)


async def _run_turn(
    provider: OpenAICodexProvider,
    prompt: str,
    *,
    tools: list[ToolDefinition] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    start = time.perf_counter()
    text_parts: list[str] = []
    tool_ends: list[dict[str, Any]] = []
    reasoning_chars = 0
    done: DoneEvent | None = None
    error: ErrorEvent | None = None
    async for event in provider.chat(
        [Message(role="user", content=prompt)],
        tools=tools,
        config=ChatConfig(max_tokens=512, timeout=timeout),
    ):
        if isinstance(event, TextDeltaEvent):
            text_parts.append(event.text)
        elif isinstance(event, ReasoningDeltaEvent):
            reasoning_chars += len(event.text)
        elif isinstance(event, ToolUseEndEvent):
            tool_ends.append({"name": event.tool_name, "arguments": event.arguments})
        elif isinstance(event, DoneEvent):
            done = event
        elif isinstance(event, ErrorEvent):
            error = event
    return {
        "content": "".join(text_parts),
        "tool_calls": tool_ends,
        "reasoning_chars": reasoning_chars,
        "usage": (
            {
                "input_tokens": done.input_tokens,
                "output_tokens": done.output_tokens,
                "cached_tokens": done.cached_tokens,
                "reasoning_tokens": done.reasoning_tokens,
                "model": done.model,
                "stop_reason": done.stop_reason,
            }
            if done
            else None
        ),
        "error": {"code": error.code, "message": error.message[:300]} if error else None,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--skip-tools", action="store_true")
    args = parser.parse_args()

    try:
        credentials = load_codex_credentials()
    except CodexAuthError as exc:
        print(f"SKIP: {exc}", file=sys.stderr)
        return 2
    account_hint = credentials.account_id[:8] if credentials.account_id else "(from JWT)"
    print(f"auth file: {codex_auth_path()} (account {account_hint}...)", file=sys.stderr)

    provider = OpenAICodexProvider(model=args.model)
    report: dict[str, Any] = {"model": args.model}

    marker = f"codex smoke {int(time.time())}"
    text = await _run_turn(
        provider, f"Reply exactly with: {marker}", timeout=args.timeout
    )
    text["marker_present"] = marker in text.pop("content", "")
    report["text_turn"] = text

    if not args.skip_tools:
        tool = ToolDefinition(
            name="get_weather",
            description="Get current weather for a city.",
            input_schema=ToolInputSchema(
                properties={"city": {"type": "string"}}, required=["city"]
            ),
        )
        tool_turn = await _run_turn(
            provider,
            "Use the get_weather tool to check the weather in Tokyo.",
            tools=[tool],
            timeout=args.timeout,
        )
        tool_turn.pop("content", None)
        report["tool_turn"] = tool_turn

    print(json.dumps(report, indent=2, ensure_ascii=False))
    text_ok = bool(report["text_turn"].get("marker_present")) and not report["text_turn"]["error"]
    tool_ok = args.skip_tools or (
        bool(report.get("tool_turn", {}).get("tool_calls"))
        and not report.get("tool_turn", {}).get("error")
    )
    return 0 if text_ok and tool_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
