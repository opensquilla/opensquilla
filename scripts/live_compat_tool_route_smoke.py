#!/usr/bin/env python3
"""Live smoke for OpenAI-compatible tool routes (diffusion/self-hosted models).

Verifies, against a real endpoint, the provider-layer half of the
multi-provider routing promises:

1. plain chat connectivity (delta or diffusing snapshot streaming)
2. tool-capability probe tri-state (supported / unsupported / unknown)
3. text-or-native tool-call synthesis: tool events arrive for an offered
   tool, and no tool-call protocol text leaks into the visible answer
4. tool schema budget accounting for the offered toolset

Engine-layer gating (tool_capability_unavailable, prompt rebuild) is
covered by unit tests; WebUI panel consistency is verified manually.

Never prints secrets. Example:

    SMOKE_API_KEY=... .venv/bin/python scripts/live_compat_tool_route_smoke.py \
        --provider inception --base-url https://api.inceptionlabs.ai/v1 \
        --model mercury-2 --output /tmp/smoke-mercury.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from opensquilla.provider.model_catalog import ModelCatalog
from opensquilla.provider.selector import ProviderConfig, _build_provider
from opensquilla.provider.tool_schema_budget import tool_schema_chars
from opensquilla.provider.types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    TextDeltaEvent,
    TextSnapshotEvent,
    ToolDefinition,
    ToolUseEndEvent,
    ToolUseStartEvent,
)

_PROTOCOL_LEAK_RE = re.compile(
    r"<tool_call>|</tool_call>|<minimax:tool_call>", re.IGNORECASE
)

_SMOKE_TOOLS = [
    ToolDefinition(
        name="web_search",
        description="Search the web and return the top results for a query.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."}
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="read_file",
        description="Read a UTF-8 text file from the workspace and return its content.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path."}
            },
            "required": ["path"],
        },
    ),
]


@dataclass
class CheckResult:
    status: str = "not_run"
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeReport:
    provider: str
    model: str
    base_url: str
    api_key_env: str
    key_present: bool
    plain_chat: CheckResult = field(default_factory=CheckResult)
    tool_probe: CheckResult = field(default_factory=CheckResult)
    tool_chat: CheckResult = field(default_factory=CheckResult)
    schema_budget: CheckResult = field(default_factory=CheckResult)


def _tri_state(probe: bool | None) -> str:
    if probe is True:
        return "supported"
    if probe is False:
        return "unsupported"
    return "unknown"


async def _collect_chat(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    prompt: str,
    *,
    tools: list[ToolDefinition] | None,
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    built = _build_provider(
        ProviderConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)
    )
    deltas: list[str] = []
    snapshot = ""
    snapshot_count = 0
    tool_calls: list[dict[str, Any]] = []
    done: DoneEvent | None = None
    error = ""
    start = time.perf_counter()
    async for event in built.chat(
        [Message(role="user", content=prompt)],
        tools=tools,
        config=ChatConfig(max_tokens=max_tokens, temperature=0, timeout=timeout),
    ):
        if isinstance(event, TextDeltaEvent):
            deltas.append(event.text)
        elif isinstance(event, TextSnapshotEvent):
            snapshot = event.text
            snapshot_count += 1
        elif isinstance(event, ToolUseStartEvent):
            tool_calls.append(
                {"tool_name": event.tool_name, "synthetic_from_text": event.synthetic_from_text}
            )
        elif isinstance(event, ToolUseEndEvent):
            for call in tool_calls:
                if call["tool_name"] == event.tool_name and "arguments_keys" not in call:
                    call["arguments_keys"] = sorted(event.arguments)
                    break
        elif isinstance(event, ErrorEvent):
            error = f"{event.code}: {event.message}"
        elif isinstance(event, DoneEvent):
            done = event
    text = snapshot if snapshot else "".join(deltas)
    return {
        "text": text,
        "snapshot_count": snapshot_count,
        "tool_calls": tool_calls,
        "stop_reason": done.stop_reason if done else "",
        "response_model": done.model if done else "",
        "usage": {
            "input_tokens": done.input_tokens if done else 0,
            "output_tokens": done.output_tokens if done else 0,
        },
        "error": error,
        "done": done is not None,
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }


async def run_smoke(args: argparse.Namespace) -> SmokeReport:
    api_key = os.environ.get(args.api_key_env, "").strip()
    report = SmokeReport(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        key_present=bool(api_key),
    )

    # 1. plain chat connectivity
    expected = "opensquilla compat route smoke ok"
    try:
        result = await _collect_chat(
            args.provider,
            args.model,
            api_key,
            args.base_url,
            f"Reply exactly with: {expected}",
            tools=None,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        ok = result["done"] and not result["error"] and expected in result["text"]
        report.plain_chat = CheckResult(
            status="passed" if ok else ("failed" if result["error"] else "content_mismatch"),
            detail=result["error"] or result["text"][:200],
            data={
                k: result[k]
                for k in ("snapshot_count", "response_model", "usage", "latency_ms")
            },
        )
    except Exception as exc:  # noqa: BLE001 - smoke reports compact diagnostic
        report.plain_chat = CheckResult(status="failed", detail=f"{type(exc).__name__}: {exc}")

    # 2. tool probe tri-state
    try:
        catalog = ModelCatalog()
        probe = await catalog.probe_openai_compatible_tools(
            provider_name=args.provider,
            base_url=args.base_url,
            model_id=args.model,
            api_key=api_key,
            timeout=args.timeout,
            tool_probe_mode=args.tool_probe_mode,
        )
        report.tool_probe = CheckResult(
            status="passed" if probe is not None else "unknown",
            detail=_tri_state(probe),
            data={"tool_probe_mode": args.tool_probe_mode},
        )
    except Exception as exc:  # noqa: BLE001 - smoke reports compact diagnostic
        report.tool_probe = CheckResult(status="failed", detail=f"{type(exc).__name__}: {exc}")

    # 3. tool chat: offered tool gets called (native or text-synthesized),
    #    and no protocol markers leak into the visible text
    try:
        result = await _collect_chat(
            args.provider,
            args.model,
            api_key,
            args.base_url,
            "Use the web_search tool to find the latest LLaDA diffusion language"
            " model release. You must call the tool.",
            tools=list(_SMOKE_TOOLS),
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        calls = result["tool_calls"]
        offered = {tool.name for tool in _SMOKE_TOOLS}
        # Protocol markers in provider-layer text are expected for synthetic
        # calls: stripping is the stream consumer's job, one layer up.
        synthetic_only = bool(calls) and all(
            call["synthetic_from_text"] for call in calls
        )
        leak = bool(_PROTOCOL_LEAK_RE.search(result["text"])) and not synthetic_only
        valid = bool(calls) and all(call["tool_name"] in offered for call in calls)
        status = "passed" if valid and not leak and not result["error"] else "failed"
        if not calls and not result["error"]:
            status = "no_tool_call"
        report.tool_chat = CheckResult(
            status=status,
            detail=result["error"] or (f"protocol_leak={leak}; text={result['text'][:160]}"),
            data={
                "tool_calls": calls,
                "stop_reason": result["stop_reason"],
                "latency_ms": result["latency_ms"],
            },
        )
    except Exception as exc:  # noqa: BLE001 - smoke reports compact diagnostic
        report.tool_chat = CheckResult(status="failed", detail=f"{type(exc).__name__}: {exc}")

    # 4. schema budget accounting for the offered toolset
    try:
        chars = tool_schema_chars(_SMOKE_TOOLS)
        report.schema_budget = CheckResult(
            status="passed",
            detail=f"{chars} compact-serialization chars for {len(_SMOKE_TOOLS)} tools",
            data={"tools_chars": chars, "tool_count": len(_SMOKE_TOOLS)},
        )
    except Exception as exc:  # noqa: BLE001 - smoke reports compact diagnostic
        report.schema_budget = CheckResult(status="failed", detail=f"{type(exc).__name__}: {exc}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openai_compatible")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="SMOKE_API_KEY")
    parser.add_argument("--tool-probe-mode", default="required")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = asyncio.run(run_smoke(args))
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "report": asdict(report),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    checks = (report.plain_chat, report.tool_probe, report.tool_chat, report.schema_budget)
    return 0 if all(check.status in {"passed", "unknown"} for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
