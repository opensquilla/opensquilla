"""Provider-adapter final payload budget proof helpers."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from copy import deepcopy
from typing import Any

_COMPACTED_STRING_MAX_CHARS = 1200
_COMPACTED_TAIL_STRING_MAX_CHARS = 640
_COMPACTED_ARGUMENT_PREVIEW_CHARS = 360
_COMPACTED_ARGUMENT_TAIL_CHARS = 120
_PROOF_BUDGET_HEADROOM_RATIO = 0.10
_PROOF_BUDGET_HEADROOM_MAX_CHARS = 16_384
_PROOF_BUDGET_HEADROOM_MIN_CHARS = 512
_TOOL_ARGUMENT_PROJECTION_PREFIX = "[tool_use_argument_projection]\n"
_INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY = "_invalid_provider_context_arguments"
_COMPACTED_TOOL_ARGUMENT_MARKERS = frozenset(
    {
        "_opensquilla_compacted_tool_arguments",
        "_opensquilla_compacted_tool_input",
    }
)


class ProviderRequestBudgetExceededError(RuntimeError):
    def __init__(self, proof: dict[str, Any]) -> None:
        self.proof = proof
        super().__init__("provider_request_budget_exhausted")


ProviderRequestBudgetExceeded = ProviderRequestBudgetExceededError


def _payload_chars(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _effective_proof_budget(proof_budget: int) -> tuple[int, int]:
    if proof_budget <= 0:
        return proof_budget, 0
    ratio_headroom = int(proof_budget * _PROOF_BUDGET_HEADROOM_RATIO)
    headroom = max(_PROOF_BUDGET_HEADROOM_MIN_CHARS, ratio_headroom)
    headroom = min(_PROOF_BUDGET_HEADROOM_MAX_CHARS, headroom)
    if proof_budget <= headroom:
        headroom = max(0, proof_budget // 4)
    return max(1, proof_budget - headroom), headroom


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


def _hard_compact_string(value: str, *, label: str) -> str:
    if len(value) <= 96:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"[opensquilla_compacted:{label}:{len(value)}:{digest}]"


def _compact_tool_arguments(value: str, *, preview: bool = True) -> str:
    if preview and len(value) <= _COMPACTED_TAIL_STRING_MAX_CHARS:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    compacted = {
        "_opensquilla_compacted_tool_arguments": True,
        "original_chars": len(value),
        "sha256": digest,
    }
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            compacted["argument_keys"] = sorted(str(key) for key in parsed)
            path = parsed.get("path")
            if isinstance(path, str):
                compacted["path"] = path
    if preview:
        compacted["head"] = value[:_COMPACTED_ARGUMENT_PREVIEW_CHARS]
        compacted["tail"] = value[-_COMPACTED_ARGUMENT_TAIL_CHARS:]
    return json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))


def _invalid_provider_context_arguments(value: str | dict[str, Any]) -> dict[str, Any]:
    return {
        _INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY: True,
        "reason": "provider_context_omitted",
    }


def _has_provider_context_argument_marker(value: dict[str, Any]) -> bool:
    return (
        value.get(_INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY) is True
        or any(value.get(marker) is True for marker in _COMPACTED_TOOL_ARGUMENT_MARKERS)
    )


def _parsed_tool_arguments(arguments: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tool_arguments_are_invalid_provider_context(arguments: str) -> bool:
    parsed = _parsed_tool_arguments(arguments)
    return (
        isinstance(parsed, dict)
        and parsed.get(_INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY) is True
    )


def _tool_arguments_have_compacted_marker(arguments: str) -> bool:
    parsed = _parsed_tool_arguments(arguments)
    return (
        isinstance(parsed, dict)
        and any(parsed.get(marker) is True for marker in _COMPACTED_TOOL_ARGUMENT_MARKERS)
    )


def _compact_tool_input(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if _has_provider_context_argument_marker(value):
        return _invalid_provider_context_arguments(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if any(
        isinstance(item, str) and item.startswith(_TOOL_ARGUMENT_PROJECTION_PREFIX)
        for item in value.values()
    ):
        return _invalid_provider_context_arguments(value)
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


def _tool_arguments_contain_projection(arguments: str) -> bool:
    parsed = _parsed_tool_arguments(arguments)
    if parsed is None:
        return arguments.startswith(_TOOL_ARGUMENT_PROJECTION_PREFIX)
    return any(
        isinstance(value, str) and value.startswith(_TOOL_ARGUMENT_PROJECTION_PREFIX)
        for value in parsed.values()
    )


def _provider_context_arguments_json(
    arguments: str,
    *,
    include_compacted_markers: bool = False,
) -> str | None:
    if (
        not _tool_arguments_are_invalid_provider_context(arguments)
        and not _tool_arguments_contain_projection(arguments)
        and not (
            include_compacted_markers
            and _tool_arguments_have_compacted_marker(arguments)
        )
    ):
        return None
    return json.dumps(
        _invalid_provider_context_arguments(arguments),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _scrub_leaked_tool_argument_projections_once(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    compacted = deepcopy(payload)
    changed = False
    for message in compacted.get("messages", []):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                arguments = function.get("arguments")
                normalized = (
                    _provider_context_arguments_json(
                        arguments,
                        include_compacted_markers=True,
                    )
                    if isinstance(arguments, str)
                    else None
                )
                if normalized is not None:
                    function["arguments"] = normalized
                    changed = True
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                continue
            compacted_input = _compact_tool_input(tool_input)
            if compacted_input != tool_input:
                block["input"] = compacted_input
                changed = True
    return (compacted, changed) if changed else (payload, False)


def _compact_text_block(block: dict[str, Any], *, emergency: bool = False) -> None:
    text = block.get("text")
    if not isinstance(text, str):
        return
    if emergency:
        block["text"] = _emergency_compact_string(text, label="text_block")
    else:
        block["text"] = _compact_tail_string(text, label="text_block")


def _compact_user_content_for_provider(content: Any) -> Any:
    if isinstance(content, str):
        return _emergency_compact_string(content, label="user_context")
    if not isinstance(content, list):
        return content
    compacted: list[Any] = []
    for block in content:
        if not isinstance(block, dict):
            compacted.append(block)
            continue
        next_block = dict(block)
        if next_block.get("type") == "text" and isinstance(next_block.get("text"), str):
            next_block["text"] = _emergency_compact_string(
                next_block["text"],
                label="user_text",
            )
        compacted.append(next_block)
    return compacted


def _hard_compact_content_for_provider(content: Any, *, label: str) -> Any:
    if isinstance(content, str):
        return _hard_compact_string(content, label=label)
    if not isinstance(content, list):
        return content
    compacted: list[Any] = []
    for block in content:
        if not isinstance(block, dict):
            compacted.append(block)
            continue
        next_block = dict(block)
        if isinstance(next_block.get("text"), str):
            next_block["text"] = _hard_compact_string(
                next_block["text"],
                label=f"{label}_text",
            )
        if isinstance(next_block.get("content"), str):
            next_block["content"] = _hard_compact_string(
                next_block["content"],
                label=f"{label}_content",
            )
        if isinstance(next_block.get("thinking"), str):
            next_block["thinking"] = _hard_compact_string(
                next_block["thinking"],
                label=f"{label}_thinking",
            )
        compacted.append(next_block)
    return compacted


def _execution_status_is_failure(status: Any) -> bool:
    if not isinstance(status, dict):
        return False
    return str(status.get("status") or "").lower() in {
        "error",
        "timeout",
        "cancelled",
    }


def _tool_content_is_critical(content: Any) -> bool:
    if isinstance(content, str):
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                if _execution_status_is_failure(parsed.get("execution_status")):
                    return True
                if parsed.get("is_error") is True:
                    return True
        lowered = content.lower()
        return "execution_status" in lowered and any(
            marker in lowered
            for marker in (
                '"status":"error"',
                '"status": "error"',
                '"status":"timeout"',
                '"status": "timeout"',
                '"status":"cancelled"',
                '"status": "cancelled"',
            )
        )
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("is_error") is True:
            return True
        if _tool_content_is_critical(block.get("content")):
            return True
    return False


def _critical_tool_content_for_provider(content: Any) -> Any:
    if isinstance(content, str):
        return _emergency_compact_string(content, label="tool_result")
    if not isinstance(content, list):
        return content
    compacted: list[Any] = []
    for block in content:
        if not isinstance(block, dict):
            compacted.append(block)
            continue
        next_block = dict(block)
        if isinstance(next_block.get("content"), str):
            next_block["content"] = _emergency_compact_string(
                next_block["content"],
                label="tool_result",
            )
        compacted.append(next_block)
    return compacted


def _compact_tool_arguments_for_final_cap(arguments: str) -> str:
    return json.dumps(
        {_INVALID_PROVIDER_CONTEXT_ARGUMENTS_KEY: True},
        ensure_ascii=False,
        separators=(",", ":"),
    )


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


def _compact_recent_tail_payload_once(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    compacted = deepcopy(payload)
    tool_argument_refs: list[tuple[dict[str, Any], str]] = []
    total_tool_argument_chars = 0
    for message in compacted.get("messages", []):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                tool_argument_refs.append((function, arguments))
                total_tool_argument_chars += len(arguments)
    aggregate_tool_arguments = (
        len(tool_argument_refs) > 1
        and total_tool_argument_chars > _COMPACTED_TAIL_STRING_MAX_CHARS * 4
    )
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
                        normalized = _provider_context_arguments_json(arguments)
                        function["arguments"] = (
                            normalized
                            if normalized is not None
                            else _compact_tool_arguments(
                                arguments,
                                preview=not aggregate_tool_arguments,
                            )
                        )
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
            elif message.get("role") == "assistant" and block.get("type") == "text":
                _compact_text_block(block)
    return compacted, {"aggregate_tool_arguments_compacted": aggregate_tool_arguments}


def _emergency_compact_current_turn_payload_once(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = deepcopy(payload)
    messages = compacted.get("messages", [])
    last_user_index = None
    if isinstance(messages, list):
        for index, message in enumerate(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                last_user_index = index
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role == "user" and index != last_user_index:
            message["content"] = _compact_user_content_for_provider(content)
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
                        normalized = _provider_context_arguments_json(arguments)
                        function["arguments"] = (
                            normalized
                            if normalized is not None
                            else _emergency_compact_string(
                                arguments,
                                label="tool_arguments",
                            )
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
            elif role == "assistant" and block.get("type") == "text":
                _compact_text_block(block, emergency=True)
    return compacted


def _final_hard_cap_payload_once(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = deepcopy(payload)
    messages = compacted.get("messages", [])
    latest_user_index = None
    if isinstance(messages, list):
        for index, message in enumerate(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                latest_user_index = index
    for index, message in enumerate(messages if isinstance(messages, list) else []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role == "user":
            if index == latest_user_index:
                message["content"] = _compact_user_content_for_provider(content)
            else:
                message["content"] = _hard_compact_content_for_provider(
                    content,
                    label="user_context",
                )
            continue
        if role == "tool":
            if _tool_content_is_critical(content):
                message["content"] = _critical_tool_content_for_provider(content)
            else:
                message["content"] = _hard_compact_content_for_provider(
                    content,
                    label="tool_result",
                )
            continue
        if role != "assistant":
            continue
        message["content"] = _hard_compact_content_for_provider(
            content,
            label="assistant_content",
        )
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str):
            message["reasoning_content"] = _hard_compact_string(
                reasoning_content,
                label="reasoning_content",
            )
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                function["arguments"] = _compact_tool_arguments_for_final_cap(arguments)
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
    effective_budget, headroom_chars = _effective_proof_budget(proof_budget)
    fits = proof_budget <= 0 or estimated_chars <= effective_budget
    proof: dict[str, Any] = {
        "projection_adapter": projection_adapter,
        "execution_status_version": 1,
        "status_projection_mode": status_projection_mode,
        "estimated_chars": estimated_chars,
        "estimated_tokens": estimated_tokens,
        "proof_budget": proof_budget,
        "raw_proof_budget": proof_budget,
        "effective_proof_budget": effective_budget,
        "proof_headroom_chars": headroom_chars,
        "fits": fits,
        "compact_needed": not fits,
        "recent_tail_too_large": False,
        "compaction_not_smaller": False,
        "provider_window_mismatch": False,
        "fallback_reason": fallback_reason,
        "top_contributors": _top_contributors(budget_payload),
        "retry_count": 0,
        **_payload_component_chars(budget_payload, effective_budget),
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
    payload, scrubbed_projection = _scrub_leaked_tool_argument_projections_once(payload)
    try:
        proof = prove_provider_payload(
            payload,
            projection_adapter=projection_adapter,
            proof_budget=proof_budget,
            status_projection_mode=status_projection_mode,
            fallback_reason=fallback_reason,
        )
    except ProviderRequestBudgetExceededError as first_error:
        first_chars = int(first_error.proof["estimated_chars"])
    else:
        if scrubbed_projection:
            proof["compact_needed"] = True
            proof["tool_argument_projection_scrubbed"] = True
        return payload, proof

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

    tail_compacted, tail_metadata = _compact_recent_tail_payload_once(tool_compacted)
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
            hard_compacted = _final_hard_cap_payload_once(emergency_compacted)
            hard_compacted_chars = _payload_chars(hard_compacted)
            try:
                proof = prove_provider_payload(
                    hard_compacted,
                    projection_adapter=projection_adapter,
                    proof_budget=proof_budget,
                    status_projection_mode=status_projection_mode,
                    fallback_reason=fallback_reason,
                )
            except ProviderRequestBudgetExceededError:
                pass
            else:
                proof["retry_count"] = 4
                proof["compact_needed"] = True
                proof["tool_payload_compaction_not_smaller"] = (
                    tool_compacted_chars >= first_chars
                )
                proof["tail_compaction_not_smaller"] = (
                    tail_compacted_chars >= tool_compacted_chars
                )
                proof["emergency_current_turn_compacted"] = True
                proof["emergency_compaction_not_smaller"] = (
                    emergency_compacted_chars >= tail_compacted_chars
                )
                proof["final_hard_cap_compacted"] = True
                proof["final_hard_cap_not_smaller"] = (
                    hard_compacted_chars >= emergency_compacted_chars
                )
                proof["compaction_not_smaller"] = hard_compacted_chars >= first_chars
                proof["recent_tail_too_large"] = False
                proof.update(tail_metadata)
                return hard_compacted, proof
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
            exc.proof["final_hard_cap_compacted"] = True
            exc.proof["final_hard_cap_not_smaller"] = (
                hard_compacted_chars >= emergency_compacted_chars
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
        proof.update(tail_metadata)
        return emergency_compacted, proof
    proof["retry_count"] = 2
    proof["compact_needed"] = True
    proof["tool_payload_compaction_not_smaller"] = tool_compacted_chars >= first_chars
    proof["tail_compaction_not_smaller"] = tail_compacted_chars >= tool_compacted_chars
    proof["compaction_not_smaller"] = tail_compacted_chars >= first_chars
    proof["recent_tail_too_large"] = False
    proof.update(tail_metadata)
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
