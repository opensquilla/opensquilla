"""Chat transcript normalization shared by frontends."""

from __future__ import annotations

import json
import re
from typing import Any

from opensquilla.artifacts import artifact_payload, strip_artifact_markers_from_text


def transcript_entries_to_chat_messages(
    entries: list[object],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = entries[-limit:] if limit is not None else entries
    messages: list[dict[str, Any]] = []
    for entry in selected:
        content = getattr(entry, "content", "") or ""
        attachments = None
        artifacts = None
        if content and content.startswith("{"):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "text" in parsed:
                    display_text = parsed.get("display_text")
                    content = display_text if isinstance(display_text, str) else parsed["text"]
                    attachments = parsed.get("attachments")
                    parsed_artifacts = parsed.get("artifacts")
                    if isinstance(parsed_artifacts, list):
                        artifacts = [
                            artifact_payload(item)
                            for item in parsed_artifacts
                            if isinstance(item, dict)
                        ]
                        if artifacts:
                            content = strip_artifact_markers_from_text(content)
            except (ValueError, KeyError):
                pass
        if content and content.lstrip().startswith("[ContentBlock"):
            texts = re.findall(
                r"ContentBlockText\(type='text', text='(.*?)'\)",
                content,
            )
            content = "\n".join(t.replace("\\n", "\n") for t in texts) if texts else ""
            if not content.strip():
                continue
        msg: dict[str, Any] = {
            "id": getattr(entry, "message_id", None),
            "message_id": getattr(entry, "message_id", None),
            "role": getattr(entry, "role", "unknown"),
            "text": content,
            "timestamp": getattr(entry, "created_at", None),
            "provenance_kind": getattr(entry, "provenance_kind", None),
            "provenance_source_session_key": getattr(entry, "provenance_source_session_key", None),
            "provenance_source_tool": getattr(entry, "provenance_source_tool", None),
        }
        transcript_id = getattr(entry, "id", None)
        if transcript_id is not None:
            msg["transcript_id"] = transcript_id
        if attachments:
            msg["attachments"] = attachments
        if artifacts:
            msg["artifacts"] = artifacts
        usage = getattr(entry, "turn_usage", None)
        if isinstance(usage, dict):
            msg["usage"] = usage
            model = usage.get("model") or usage.get("routed_model")
            if model:
                msg["model"] = model
            input_tokens = int(usage.get("input_tokens") or usage.get("inputTokens") or 0)
            output_tokens = int(usage.get("output_tokens") or usage.get("outputTokens") or 0)
            msg["input"] = input_tokens
            msg["output"] = output_tokens
            msg["input_tokens"] = input_tokens
            msg["output_tokens"] = output_tokens
            if usage.get("cost_usd") is not None:
                msg["cost_usd"] = float(usage.get("cost_usd") or 0.0)
        tool_calls = getattr(entry, "tool_calls", None)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)
    return messages
