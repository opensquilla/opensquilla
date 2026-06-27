from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opensquilla.cli.chat.turn import UsageSummary  # type: ignore[import-untyped]

ARCHITECTURE_PROMPT_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "tui"
    / "architecture_prompt_replay.json"
)


async def replay_architecture_prompt(renderer: Any, output: Any) -> UsageSummary:
    fixture = json.loads(ARCHITECTURE_PROMPT_FIXTURE.read_text(encoding="utf-8"))
    usage = UsageSummary(model="fake-terminal", input_tokens=1, output_tokens=2)
    events = fixture["events"]
    tool_outputs_by_id = _tool_outputs_by_id(events)

    for event in events:
        kind = event["kind"]
        payload = event.get("payload", {})
        if kind == "toolbar":
            _set_toolbar(output, "router_hud", payload.get("router_hud"))
            _set_toolbar(output, "router_hud_style", payload.get("router_hud_style"))
            _invalidate(output)
        elif kind == "status":
            await renderer.astatus(str(payload.get("message", "")))
            for detail in _details_from_payload(payload):
                await renderer.astatus(detail)
        elif kind == "tool_start":
            args = payload.get("args")
            await renderer.atool_start(
                str(payload.get("name", "tool")),
                args if isinstance(args, dict) else None,
                str(payload.get("tool_use_id", "")),
            )
        elif kind == "tool_finished":
            elapsed = payload.get("elapsed")
            tool_use_id = str(payload.get("tool_use_id", ""))
            await renderer.atool_finished(
                tool_use_id,
                success=bool(payload.get("success", True)),
                elapsed=elapsed if isinstance(elapsed, float | int) else None,
                error=str(payload["error"]) if "error" in payload else None,
                result=_tool_result_from_output(tool_outputs_by_id.get(tool_use_id)),
            )
        elif kind == "tool_output":
            continue
        elif kind == "text_delta":
            await renderer.aappend_text(str(payload.get("text", "")))
        elif kind == "done":
            usage_payload = payload.get("usage", {})
            if isinstance(usage_payload, dict):
                usage = UsageSummary(
                    model=str(usage_payload.get("model", "fake-terminal")),
                    input_tokens=int(usage_payload.get("input_tokens", 0)),
                    output_tokens=int(usage_payload.get("output_tokens", 0)),
                )
    return usage


def _details_from_payload(payload: dict[str, Any]) -> list[str]:
    details = payload.get("detail", [])
    if isinstance(details, list):
        return [str(detail) for detail in details]
    return []


def _tool_outputs_by_id(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("kind") != "tool_output":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        tool_use_id = payload.get("tool_use_id")
        if tool_use_id is None:
            continue
        outputs[str(tool_use_id)] = payload
    return outputs


def _tool_result_from_output(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None

    parts: list[str] = []
    summary = str(payload.get("summary", "")).strip()
    if summary:
        parts.append(summary)

    stdout = payload.get("stdout", [])
    if isinstance(stdout, list) and stdout:
        parts.extend(str(line) for line in stdout)

    return "\n".join(parts) if parts else None


def _set_toolbar(output: Any, key: str, value: object | None) -> None:
    setter = getattr(output, "set_toolbar", None)
    if callable(setter):
        setter(key, value)


def _invalidate(output: Any) -> None:
    invalidate = getattr(output, "invalidate", None)
    if callable(invalidate):
        invalidate()
