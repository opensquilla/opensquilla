"""Provider-adapter final payload budget proof helpers."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from typing import Any

_COMPACTED_STRING_MAX_CHARS = 1200
_COMPACTED_TAIL_STRING_MAX_CHARS = 640
_COMPACTED_ARGUMENT_PREVIEW_CHARS = 360
_COMPACTED_ARGUMENT_TAIL_CHARS = 120


class ProviderRequestBudgetExceededError(RuntimeError):
    def __init__(self, proof: dict[str, Any]) -> None:
        self.proof = proof
        super().__init__("provider_request_budget_exhausted")


ProviderRequestBudgetExceeded = ProviderRequestBudgetExceededError


def _payload_chars(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _is_data_url(value: str) -> bool:
    return value.startswith("data:") and ";base64," in value[:128]


def _media_placeholder(kind: str, value: str) -> str:
    return f"[provider_request_{kind}_omitted: {len(value)} chars]"


def _budget_projection(payload: Any) -> tuple[Any, int, int]:
    media_chars = 0
    media_blocks = 0

    def visit(value: Any) -> Any:
        nonlocal media_chars, media_blocks
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value

        if value.get("type") == "image_url":
            image_url = value.get("image_url")
            if isinstance(image_url, dict):
                url = image_url.get("url")
                if isinstance(url, str) and _is_data_url(url):
                    media_chars += len(url)
                    media_blocks += 1
                    replaced = dict(value)
                    replaced["image_url"] = {
                        **image_url,
                        "url": _media_placeholder("image_url", url),
                    }
                    return replaced

        source = value.get("source")
        if isinstance(source, dict) and source.get("type") == "base64":
            data = source.get("data")
            media_type = source.get("media_type")
            if (
                isinstance(data, str)
                and isinstance(media_type, str)
                and (media_type.startswith("image/") or media_type == "application/pdf")
            ):
                media_chars += len(data)
                media_blocks += 1
                replaced = dict(value)
                replaced["source"] = {
                    **source,
                    "data": _media_placeholder("base64_media", data),
                }
                return replaced

        return {key: visit(item) for key, item in value.items()}

    return visit(payload), media_chars, media_blocks


def _top_contributors(payload: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    contributors: list[dict[str, Any]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, str):
            contributors.append({"path": path, "chars": len(value)})
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f"{path}.{key}")

    visit(payload, "$")
    contributors.sort(key=lambda item: int(item["chars"]), reverse=True)
    return contributors[:limit]


def _compact_string(value: str) -> str:
    if len(value) <= _COMPACTED_STRING_MAX_CHARS:
        return value
    head = value[:900]
    tail = value[-200:]
    omitted = len(value) - len(head) - len(tail)
    return f"{head}\n\n[provider_request_compacted: omitted {omitted} chars]\n\n{tail}"


def _compact_tail_string(value: str, *, label: str) -> str:
    if len(value) <= _COMPACTED_TAIL_STRING_MAX_CHARS:
        return value
    head = value[:420]
    tail = value[-120:]
    omitted = len(value) - len(head) - len(tail)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return (
        f"{head}\n\n"
        f"[provider_request_{label}_compacted: omitted {omitted} chars; "
        f"original_chars={len(value)}; sha256={digest}]\n\n"
        f"{tail}"
    )


def _emergency_compact_string(value: str, *, label: str) -> str:
    if len(value) <= 320:
        return value
    head = value[:180]
    tail = value[-40:]
    omitted = len(value) - len(head) - len(tail)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return (
        f"{head}\n\n"
        f"[provider_request_{label}_emergency_compacted: omitted {omitted} chars; "
        f"original_chars={len(value)}; sha256={digest}]\n\n"
        f"{tail}"
    )


def _compact_tool_arguments(value: str) -> str:
    if len(value) <= _COMPACTED_TAIL_STRING_MAX_CHARS:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    compacted = {
        "_opensquilla_compacted_tool_arguments": True,
        "original_chars": len(value),
        "sha256": digest,
        "head": value[:_COMPACTED_ARGUMENT_PREVIEW_CHARS],
        "tail": value[-_COMPACTED_ARGUMENT_TAIL_CHARS:],
    }
    return json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))


def _compact_tool_input(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(raw) <= _COMPACTED_TAIL_STRING_MAX_CHARS:
        return value
    compacted = dict(value)
    changed = False
    for key, item in value.items():
        if not isinstance(item, str):
            continue
        next_item = _compact_tail_string(item, label="tool_input")
        if next_item != item:
            compacted[key] = next_item
            changed = True
    if changed:
        return compacted
    return {
        "_opensquilla_compacted_tool_input": True,
        "original_chars": len(raw),
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "head": raw[:_COMPACTED_ARGUMENT_PREVIEW_CHARS],
        "tail": raw[-_COMPACTED_ARGUMENT_TAIL_CHARS:],
    }


def _compact_tool_payload_once(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = deepcopy(payload)
    for message in compacted.get("messages", []):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if message.get("role") == "tool" and isinstance(content, str):
            message["content"] = _compact_string(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            block_content = block.get("content")
            if isinstance(block_content, str):
                block["content"] = _compact_string(block_content)
            elif isinstance(block_content, list):
                for item in block_content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        item["text"] = _compact_string(item["text"])
    return compacted


def _compact_recent_tail_payload_once(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = deepcopy(payload)
    for message in compacted.get("messages", []):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str):
                message["reasoning_content"] = _compact_tail_string(
                    reasoning_content,
                    label="reasoning_content",
                )
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function")
                    if not isinstance(function, dict):
                        continue
                    arguments = function.get("arguments")
                    if isinstance(arguments, str):
                        function["arguments"] = _compact_tool_arguments(arguments)
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                block["input"] = _compact_tool_input(block.get("input"))
            elif block.get("type") == "thinking" and isinstance(block.get("thinking"), str):
                block["thinking"] = _compact_tail_string(
                    block["thinking"],
                    label="thinking_block",
                )
    return compacted


def _emergency_compact_current_turn_payload_once(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = deepcopy(payload)
    for message in compacted.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, str) and role in {"assistant", "tool"}:
            message["content"] = _emergency_compact_string(
                content,
                label=f"{role}_content",
            )
        if role == "assistant":
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str):
                message["reasoning_content"] = _emergency_compact_string(
                    reasoning_content,
                    label="reasoning_content",
                )
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function")
                    if not isinstance(function, dict):
                        continue
                    arguments = function.get("arguments")
                    if isinstance(arguments, str):
                        function["arguments"] = _emergency_compact_string(
                            arguments,
                            label="tool_arguments",
                        )
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                block_content = block.get("content")
                if isinstance(block_content, str):
                    block["content"] = _emergency_compact_string(
                        block_content,
                        label="tool_result",
                    )
                elif isinstance(block_content, list):
                    for item in block_content:
                        if isinstance(item, dict) and isinstance(item.get("text"), str):
                            item["text"] = _emergency_compact_string(
                                item["text"],
                                label="tool_result_text",
                            )
            elif block.get("type") == "thinking" and isinstance(block.get("thinking"), str):
                block["thinking"] = _emergency_compact_string(
                    block["thinking"],
                    label="thinking_block",
                )
    return compacted


def _component_chars(payload: dict[str, Any], key: str) -> int:
    if key not in payload:
        return 0
    return _payload_chars(payload[key])


def _message_role_chars(payload: dict[str, Any], role: str) -> int:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return 0
    role_messages = [
        message
        for message in messages
        if isinstance(message, dict) and message.get("role") == role
    ]
    return _payload_chars(role_messages) if role_messages else 0


def _top_level_chars(payload: dict[str, Any]) -> int:
    top_level_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"messages", "tools", "system"}
    }
    return _payload_chars(top_level_payload) if top_level_payload else 0


def _payload_component_chars(payload: dict[str, Any], proof_budget: int) -> dict[str, Any]:
    messages_chars = _component_chars(payload, "messages")
    tools_chars = _component_chars(payload, "tools")
    system_chars = _component_chars(payload, "system") + _message_role_chars(
        payload,
        "system",
    )
    tool_schema_too_large = False
    if proof_budget > 0 and tools_chars > 0:
        tool_schema_too_large = tools_chars >= max(16_000, proof_budget // 4)
    return {
        "messages_chars": messages_chars,
        "tools_chars": tools_chars,
        "system_chars": system_chars,
        "top_level_chars": _top_level_chars(payload),
        "tool_schema_too_large": tool_schema_too_large,
    }

def prove_provider_payload(
    payload: dict[str, Any],
    *,
    projection_adapter: str,
    proof_budget: int,
    status_projection_mode: str = "native_or_none",
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    budget_payload, media_chars, media_blocks = _budget_projection(payload)
    estimated_chars = _payload_chars(budget_payload)
    estimated_tokens = max(1, estimated_chars // 4)
    fits = proof_budget <= 0 or estimated_chars <= proof_budget
    proof: dict[str, Any] = {
        "projection_adapter": projection_adapter,
        "execution_status_version": 1,
        "status_projection_mode": status_projection_mode,
        "estimated_chars": estimated_chars,
        "estimated_tokens": estimated_tokens,
        "proof_budget": proof_budget,
        "fits": fits,
        "compact_needed": not fits,
        "recent_tail_too_large": False,
        "compaction_not_smaller": False,
        "provider_window_mismatch": False,
        "fallback_reason": fallback_reason,
        "top_contributors": _top_contributors(budget_payload),
        "retry_count": 0,
        **_payload_component_chars(budget_payload, proof_budget),
    }
    if media_blocks:
        proof["media_chars_excluded"] = media_chars
        proof["media_blocks_excluded"] = media_blocks
    if not fits:
        proof["fallback_reason"] = "provider_request_budget_exhausted"
        raise ProviderRequestBudgetExceededError(proof)
    return proof


def prove_or_compact_provider_payload(
    payload: dict[str, Any],
    *,
    projection_adapter: str,
    proof_budget: int,
    status_projection_mode: str = "native_or_none",
    fallback_reason: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if proof_budget <= 0:
        return payload, None
    try:
        return payload, prove_provider_payload(
            payload,
            projection_adapter=projection_adapter,
            proof_budget=proof_budget,
            status_projection_mode=status_projection_mode,
            fallback_reason=fallback_reason,
        )
    except ProviderRequestBudgetExceededError as first_error:
        first_chars = int(first_error.proof["estimated_chars"])

    tool_compacted = _compact_tool_payload_once(payload)
    tool_compacted_chars = _payload_chars(tool_compacted)
    try:
        proof = prove_provider_payload(
            tool_compacted,
            projection_adapter=projection_adapter,
            proof_budget=proof_budget,
            status_projection_mode=status_projection_mode,
            fallback_reason=fallback_reason,
        )
    except ProviderRequestBudgetExceededError:
        pass
    else:
        proof["retry_count"] = 1
        proof["compact_needed"] = True
        proof["compaction_not_smaller"] = tool_compacted_chars >= first_chars
        proof["recent_tail_too_large"] = False
        return tool_compacted, proof

    tail_compacted = _compact_recent_tail_payload_once(tool_compacted)
    tail_compacted_chars = _payload_chars(tail_compacted)
    try:
        proof = prove_provider_payload(
            tail_compacted,
            projection_adapter=projection_adapter,
            proof_budget=proof_budget,
            status_projection_mode=status_projection_mode,
            fallback_reason=fallback_reason,
        )
    except ProviderRequestBudgetExceededError as tail_error:
        emergency_compacted = _emergency_compact_current_turn_payload_once(tail_compacted)
        emergency_compacted_chars = _payload_chars(emergency_compacted)
        try:
            proof = prove_provider_payload(
                emergency_compacted,
                projection_adapter=projection_adapter,
                proof_budget=proof_budget,
                status_projection_mode=status_projection_mode,
                fallback_reason=fallback_reason,
            )
        except ProviderRequestBudgetExceededError as exc:
            exc.proof["retry_count"] = 2
            exc.proof["compact_needed"] = True
            exc.proof["tool_payload_compaction_not_smaller"] = (
                tool_compacted_chars >= first_chars
            )
            exc.proof["tail_compaction_not_smaller"] = (
                tail_compacted_chars >= tool_compacted_chars
            )
            exc.proof["emergency_current_turn_compacted"] = True
            exc.proof["emergency_compaction_not_smaller"] = (
                emergency_compacted_chars >= tail_compacted_chars
            )
            exc.proof["compaction_not_smaller"] = emergency_compacted_chars >= first_chars
            exc.proof["recent_tail_too_large"] = bool(tail_error.proof.get("top_contributors"))
            raise
        proof["retry_count"] = 3
        proof["compact_needed"] = True
        proof["tool_payload_compaction_not_smaller"] = tool_compacted_chars >= first_chars
        proof["tail_compaction_not_smaller"] = tail_compacted_chars >= tool_compacted_chars
        proof["emergency_current_turn_compacted"] = True
        proof["emergency_compaction_not_smaller"] = (
            emergency_compacted_chars >= tail_compacted_chars
        )
        proof["compaction_not_smaller"] = emergency_compacted_chars >= first_chars
        proof["recent_tail_too_large"] = False
        return emergency_compacted, proof
    proof["retry_count"] = 2
    proof["compact_needed"] = True
    proof["tool_payload_compaction_not_smaller"] = tool_compacted_chars >= first_chars
    proof["tail_compaction_not_smaller"] = tail_compacted_chars >= tool_compacted_chars
    proof["compaction_not_smaller"] = tail_compacted_chars >= first_chars
    proof["recent_tail_too_large"] = False
    return tail_compacted, proof


def prove_provider_payload_from_env(
    payload: dict[str, Any],
    *,
    projection_adapter: str,
    status_projection_mode: str = "native_or_none",
    fallback_reason: str | None = None,
) -> dict[str, Any] | None:
    raw = os.environ.get("OPENSQUILLA_PROVIDER_REQUEST_PROOF_MAX_CHARS")
    if not raw:
        return None
    try:
        proof_budget = int(raw)
    except ValueError:
        return None
    return prove_provider_payload(
        payload,
        projection_adapter=projection_adapter,
        proof_budget=proof_budget,
        status_projection_mode=status_projection_mode,
        fallback_reason=fallback_reason,
    )
