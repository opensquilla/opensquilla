"""OpenAIProvider — streams via OpenAI Chat Completions API using httpx."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast
from uuid import uuid4

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env
from opensquilla.execution_status import compact_provider_status, derive_is_error
from opensquilla.secrets import clean_header_secret

from .compat_policy import OpenAICompatPolicy, compat_policy_for_kind
from .context_capabilities import supports_openrouter_explicit_prompt_cache
from .failures import retry_after_from_headers
from .minimax_compat import contains_minimax_protocol, parse_minimax_tool_calls
from .openrouter_attribution import openrouter_app_headers
from .protocol import ProviderConnectionConfig, ProviderMetadata
from .reasoning_dialects import (
    ReasoningDisableArgs,
    ReasoningEnableArgs,
    apply_reasoning_disable,
    apply_reasoning_enable,
)
from .request_proof import (
    ProviderRequestBudgetExceededError,
    prove_provider_payload_from_env,
)
from .stream_assembly import ReasoningAccumulator, ToolStreamAccumulator
from .types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelCapabilities,
    ModelInfo,
    ProviderHeartbeatEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolUseEndEvent,
    ToolUseStartEvent,
)

_OPENAI_API_BASE = "https://api.openai.com"
log = structlog.get_logger(__name__)
_PLAIN_JSON_TOOL_CALL_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s*(\{.*\})\s*$",
    re.DOTALL,
)
_PLAIN_JSON_TOOL_PREFIX_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.:-]*)\s*(?=\{)",
)

_OPENAI_TOOL_STATUS_OUTPUT_MAX_CHARS = 4000
_VERSIONED_BASE_URL_RE = re.compile(r"/v\d+$")


def _openai_tool_result_content(block: Any) -> str:
    content = block.content if isinstance(block.content, str) else json.dumps(block.content)
    status = getattr(block, "execution_status", None)
    if status is None or not derive_is_error(status):
        return content
    output = content
    if len(output) > _OPENAI_TOOL_STATUS_OUTPUT_MAX_CHARS:
        output = output[:_OPENAI_TOOL_STATUS_OUTPUT_MAX_CHARS]
    return json.dumps(
        {
            "execution_status": compact_provider_status(status),
            "output": output,
        },
        ensure_ascii=False,
    )


def _http_error_body_text(body: bytes | str) -> str:
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    text = text.strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, str) and message.strip():
        return message.strip()
    return text


def _format_chat_http_error(display_name: str, status_code: int, body: bytes | str) -> str:
    body_text = _http_error_body_text(body) or "empty response body"
    return f"{display_name} chat request failed (HTTP {status_code}): {body_text}"


def _strip_tool_schema_keywords(value: Any, unsupported: frozenset[str]) -> Any:
    if not unsupported:
        return value
    if isinstance(value, dict):
        return {
            key: _strip_tool_schema_keywords(item, unsupported)
            for key, item in value.items()
            if key not in unsupported
        }
    if isinstance(value, list):
        return [_strip_tool_schema_keywords(item, unsupported) for item in value]
    return value


def _extract_think_tags(text: str) -> str:
    """Extract content from <think> tags. Returns empty string if none found."""
    matches = re.findall(r"<think>([\s\S]*?)</think>", text)
    return "\n".join(matches) if matches else ""


def _strip_think_tags(text: str) -> str:
    """Remove <think> tags from text, including unclosed trailing tags."""
    result = re.sub(r"<think>[\s\S]*?</think>", "", text)
    result = re.sub(r"<think>[\s\S]*$", "", result)
    return result.strip()


def _model_basename(model: str) -> str:
    return model.rsplit("/", 1)[-1].strip().lower()


def _on_official_host(policy: OpenAICompatPolicy, base_url: str) -> bool:
    return bool(policy.official_host) and policy.official_host in base_url.lower()


def _uses_max_completion_tokens(
    policy: OpenAICompatPolicy,
    base_url: str,
    model: str,
) -> bool:
    if not policy.max_completion_tokens_model_prefixes:
        return False
    if not _on_official_host(policy, base_url):
        return False
    return _model_basename(model).startswith(policy.max_completion_tokens_model_prefixes)


def _should_send_temperature(
    policy: OpenAICompatPolicy,
    base_url: str,
    model: str,
    cfg: ChatConfig,
    caps: Any,
) -> bool:
    if cfg.temperature is None:
        return False
    model_name = _model_basename(model)
    if (
        policy.fixed_sampling_model_prefixes
        and model_name.startswith(policy.fixed_sampling_model_prefixes)
        and cfg.temperature != 1.0
    ):
        return False
    if (
        policy.omit_temperature_when_thinking_model_prefixes
        and _on_official_host(policy, base_url)
        and cfg.thinking
        and bool(caps and caps.supports_reasoning)
        and model_name.startswith(policy.omit_temperature_when_thinking_model_prefixes)
    ):
        return False
    return True


def _resolve_llm_proxy(proxy: str | None) -> str | None:
    if proxy is None:
        return os.environ.get("OPENSQUILLA_LLM_PROXY", "").strip() or None
    return proxy.strip() or None


def _parse_exact_plain_json_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a bare ``tool_name{...}`` assistant text response."""
    candidates = [text]
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if non_empty_lines:
        last_line = non_empty_lines[-1]
        if last_line != text:
            candidates.append(last_line)

    match = None
    for candidate in candidates:
        match = _PLAIN_JSON_TOOL_CALL_RE.match(candidate)
        if match:
            break
    if match is None:
        return None

    try:
        arguments = json.loads(match.group(2))
    except json.JSONDecodeError:
        return None
    if not isinstance(arguments, dict):
        return None
    return match.group(1), arguments


def _parse_trailing_plain_json_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a trailing ``tool_name{...}``, allowing prose before it."""
    decoder = json.JSONDecoder()
    for match in reversed(list(_PLAIN_JSON_TOOL_PREFIX_RE.finditer(text))):
        try:
            arguments, end = decoder.raw_decode(text, match.end())
        except json.JSONDecodeError:
            continue
        if text[end:].strip():
            continue
        if not isinstance(arguments, dict):
            continue
        return match.group(1), arguments
    return None


def _parse_plain_json_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a text response ending in ``tool_name{...}``."""
    exact_call = _parse_exact_plain_json_tool_call(text)
    if exact_call is not None:
        return exact_call
    return _parse_trailing_plain_json_tool_call(text)


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_present(*sources: tuple[Mapping[str, Any], str]) -> int:
    """Return the first source[key] that is actually present (key in dict).

    Truthiness chains via ``or`` would skip an explicit ``0`` from the canonical
    field and silently fall through to a less-canonical one — e.g. an
    ``cache_creation_input_tokens=0`` getting overwritten by a non-zero
    ``prompt_tokens_details.cache_write_tokens``. Use ``in`` instead so a real
    zero wins.
    """
    for src, key in sources:
        if isinstance(src, Mapping) and key in src:
            return _coerce_int(src[key])
    return 0


def _usage_fields(usage: Mapping[str, Any] | None) -> tuple[int, int, int, int, int, float]:
    if not usage:
        return 0, 0, 0, 0, 0, 0.0

    input_tokens = _coerce_int(usage.get("prompt_tokens"))
    output_tokens = _coerce_int(usage.get("completion_tokens"))
    completion_details = usage.get("completion_tokens_details") or {}
    reasoning_tokens = _coerce_int(completion_details.get("reasoning_tokens"))
    prompt_details = usage.get("prompt_tokens_details") or {}

    # Cache reads: keys we accept, in priority order.
    #   - prompt_tokens_details.cached_tokens  — OpenAI native + most OpenRouter
    #     proxies.
    #   - usage.prompt_cache_hit_tokens        — DeepSeek native shape.
    cached_tokens = _first_present(
        (prompt_details, "cached_tokens"),
        (usage, "prompt_cache_hit_tokens"),
    )

    # Cache writes: keys we accept, in priority order.
    #   - usage.cache_creation_input_tokens          — Anthropic-via-OpenRouter passthrough.
    #   - prompt_tokens_details.cache_write_tokens   — OpenRouter documented field.
    #   - usage.cache_write_tokens                   — top-level alias some proxies use.
    #   - prompt_tokens_details.cache_creation_tokens — defensive fallback.
    cache_write_tokens = _first_present(
        (usage, "cache_creation_input_tokens"),
        (prompt_details, "cache_write_tokens"),
        (usage, "cache_write_tokens"),
        (prompt_details, "cache_creation_tokens"),
    )

    billed_cost = _coerce_float(usage.get("cost", usage.get("total_cost")))
    return (
        input_tokens,
        output_tokens,
        reasoning_tokens,
        cached_tokens,
        cache_write_tokens,
        billed_cost,
    )


def _provider_billed_cost(provider_kind: str, raw_billed_cost: float) -> tuple[float, str]:
    """Return trusted provider-billed cost and its source marker."""
    if compat_policy_for_kind(provider_kind).trust_billed_cost and raw_billed_cost > 0.0:
        return raw_billed_cost, "provider_billed"
    return 0.0, "none"


def _resolve_tool_call_index(
    tc: Mapping[str, Any],
    tools_acc: ToolStreamAccumulator,
) -> int:
    """Resolve the accumulator slot for a streamed tool-call delta.

    Most upstreams send an explicit ``index``, but some (Gemini's
    OpenAI-compat endpoint, assorted local gateways) omit it: fall back to
    matching the provider-supplied id against known calls, then to opening a
    new slot — a missing index must never fail the stream.
    """
    if "index" in tc:
        return _coerce_int(tc["index"])
    tool_call_id = tc.get("id")
    if isinstance(tool_call_id, str) and tool_call_id:
        key = tools_acc.find_key_for_tool_call_id(tool_call_id)
        if key is not None:
            return cast(int, key)
        return tools_acc.next_int_key()
    single = tools_acc.single_key()
    if single is not None:
        return cast(int, single)
    return tools_acc.next_int_key()


def _stream_timeout(timeout: float) -> httpx.Timeout:
    connect = _coerce_float(os.environ.get("OPENSQUILLA_LLM_STREAM_CONNECT_TIMEOUT_SECONDS"))
    if connect <= 0:
        connect = 12.0
    connect = min(connect, max(timeout, 1.0))
    write = _coerce_float(os.environ.get("OPENSQUILLA_LLM_STREAM_WRITE_TIMEOUT_SECONDS"))
    if write <= 0:
        write = max(60.0, timeout)
    return httpx.Timeout(timeout, connect=connect, write=write, pool=10.0)


def _synthesize_text_tool_events(
    full_text: str,
    tools: list[ToolDefinition] | None,
) -> list[ToolUseStartEvent | ToolUseEndEvent]:
    if not tools or not full_text:
        return []

    events: list[ToolUseStartEvent | ToolUseEndEvent] = []
    allowed_tool_names = {tool.name for tool in tools}
    if contains_minimax_protocol(full_text):
        for minimax_call in parse_minimax_tool_calls(full_text):
            if minimax_call.name not in allowed_tool_names:
                continue
            tool_use_id = f"minimax_compat_{uuid4().hex[:12]}"
            events.append(
                ToolUseStartEvent(
                    tool_use_id=tool_use_id,
                    tool_name=minimax_call.name,
                    synthetic_from_text=True,
                )
            )
            events.append(
                ToolUseEndEvent(
                    tool_use_id=tool_use_id,
                    tool_name=minimax_call.name,
                    arguments=dict(minimax_call.arguments),
                    synthetic_from_text=True,
                )
            )
    else:
        plain_call = _parse_plain_json_tool_call(full_text)
        if plain_call is not None:
            tool_name, arguments = plain_call
            if tool_name in allowed_tool_names:
                tool_use_id = f"text_compat_{uuid4().hex[:12]}"
                events.append(
                    ToolUseStartEvent(
                        tool_use_id=tool_use_id,
                        tool_name=tool_name,
                        synthetic_from_text=True,
                    )
                )
                events.append(
                    ToolUseEndEvent(
                        tool_use_id=tool_use_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        synthetic_from_text=True,
                    )
                )
    return events


def _build_openai_tool(
    tool: ToolDefinition,
    *,
    unsupported_keywords: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    schema = tool.input_schema.model_dump(exclude_none=True)
    schema = _strip_tool_schema_keywords(schema, unsupported_keywords)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        },
    }


def _openrouter_model_likely_supports_explicit_prompt_cache(model: str) -> bool:
    return supports_openrouter_explicit_prompt_cache(model)


def _openrouter_model_is_anthropic(model: str) -> bool:
    return model.strip().lower().startswith("anthropic/")


def _stable_json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _openrouter_non_system_prefix_item_hashes(
    messages: list[dict[str, Any]], *, max_items: int = 3
) -> list[str]:
    hashes: list[str] = []
    for message in messages:
        if message.get("role") == "system":
            continue
        hashes.append(_stable_json_hash(message))
        if len(hashes) >= max_items:
            break
    return hashes


def _attach_reasoning_content(
    msg: Message,
    payload: dict[str, Any],
    *,
    include_reasoning_content: bool = True,
    require_assistant_reasoning_content: bool = False,
) -> dict[str, Any]:
    if include_reasoning_content and msg.role == "assistant" and msg.reasoning_content:
        payload["reasoning_content"] = msg.reasoning_content
    elif (
        include_reasoning_content
        and require_assistant_reasoning_content
        and msg.role == "assistant"
    ):
        payload["reasoning_content"] = ""
    return payload


def _requires_assistant_reasoning_content(policy: OpenAICompatPolicy, model: str) -> bool:
    return model.strip().lower() in policy.require_reasoning_content_model_ids


def _should_replay_reasoning_content(
    *,
    policy: OpenAICompatPolicy,
    model: str,
    caps: ModelCapabilities | None,
) -> bool:
    if _requires_assistant_reasoning_content(policy, model):
        return True
    if not caps or not caps.supports_reasoning:
        return False
    return bool(policy.replay_reasoning_format) and (
        caps.reasoning_format == policy.replay_reasoning_format
    )


def _build_openai_messages(
    msg: Message,
    *,
    include_reasoning_content: bool = True,
    require_assistant_reasoning_content: bool = False,
    replay_provider_state: bool = True,
) -> list[dict[str, Any]]:
    """Convert a opensquilla Message into one or more OpenAI-format message dicts.

    Returns a list because OpenAI requires one ``{"role": "tool"}`` message
    per tool result, while opensquilla packs multiple tool results into a single
    Message.

    Invariant: tool_result blocks never coexist with text/image blocks in the
    same Message (agent.py always packs tool results into a dedicated message).
    """
    if isinstance(msg.content, str):
        return [
            _attach_reasoning_content(
                msg,
                {"role": msg.role, "content": msg.content},
                include_reasoning_content=include_reasoning_content,
                require_assistant_reasoning_content=require_assistant_reasoning_content,
            )
        ]

    parts: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    thinking_signature: str | None = None

    for block in msg.content:
        if block.type == "text":
            parts.append({"type": "text", "text": block.text})
        elif block.type == "thinking":
            sig = getattr(block, "signature", None)
            if isinstance(sig, str) and sig:
                thinking_signature = sig
        elif block.type == "tool_use":
            tc_dict: dict[str, Any] = {
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                },
            }
            tool_calls.append(tc_dict)
        elif block.type == "image":
            if block.source_type == "url":
                parts.append({"type": "image_url", "image_url": {"url": block.data}})
            else:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{block.media_type};base64,{block.data}"},
                    }
                )
        elif block.type == "tool_result":
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": block.tool_use_id,
                    "content": _openai_tool_result_content(block),
                }
            )

    # Tool results → one message per result (OpenAI requirement)
    if tool_results:
        return tool_results

    # Assistant message with tool_calls (preserve text alongside calls)
    if tool_calls:
        # Gemini requires thought_signature on the first tool_call in each
        # step of the current turn. Attach it if a ContentBlockThinking with
        # a signature preceded the tool_use blocks — but never replay a
        # signature to a provider that did not mint it.
        if thinking_signature and tool_calls and replay_provider_state:
            tool_calls[0]["extra_content"] = {
                "google": {"thought_signature": thinking_signature},
            }
        result: dict[str, Any] = {"role": msg.role, "tool_calls": tool_calls}
        text_content = " ".join(p["text"] for p in parts if p.get("type") == "text")
        if text_content:
            result["content"] = text_content
        return [
            _attach_reasoning_content(
                msg,
                result,
                include_reasoning_content=include_reasoning_content,
                require_assistant_reasoning_content=require_assistant_reasoning_content,
            )
        ]

    # If parts contain mixed content (text + images), return as list for multimodal
    has_non_text = any(p["type"] != "text" for p in parts)
    if has_non_text:
        return [
            _attach_reasoning_content(
                msg,
                {"role": msg.role, "content": parts},
                include_reasoning_content=include_reasoning_content,
                require_assistant_reasoning_content=require_assistant_reasoning_content,
            )
        ]
    content_text = " ".join(p["text"] for p in parts if p["type"] == "text")
    return [
        _attach_reasoning_content(
            msg,
            {"role": msg.role, "content": content_text},
            include_reasoning_content=include_reasoning_content,
            require_assistant_reasoning_content=require_assistant_reasoning_content,
        )
    ]


class OpenAIProvider:
    """Streams from OpenAI-compatible Chat Completions API (SSE)."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = _OPENAI_API_BASE,
        org_id: str | None = None,
        proxy: str | None = None,
        provider_kind: str | None = None,
        provider_routing: Mapping[str, str] | None = None,
        compat: OpenAICompatPolicy | None = None,
        replay_provider_state: bool = True,
    ) -> None:
        self._api_key = clean_header_secret(api_key, label="LLM API key")
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._proxy = _resolve_llm_proxy(proxy)
        self._org_id = org_id
        if not provider_kind:
            # Fallback for direct construction only (tests, ad-hoc
            # embedding): every production path flows through
            # selector._build_provider, which always passes the registry
            # spec's provider_kind. The base-url sniff keeps a bare
            # OpenAIProvider(base_url="https://openrouter.ai/...") resolving
            # the OpenRouter dialect instead of silently degrading.
            provider_kind = "openrouter" if "openrouter.ai" in self._base_url else "openai"
        self._provider_kind = provider_kind
        self._compat = compat or compat_policy_for_kind(self._provider_kind)
        self._replay_provider_state = replay_provider_state
        self._provider_routing: Mapping[str, str] = provider_routing or {}

    @property
    def model(self) -> str:
        """Model id this provider was configured with.

        Public so callers (e.g. derived-cache key construction) can identify
        the underlying model without prying at private state.
        """
        return self._model

    def provider_metadata(self) -> ProviderMetadata:
        """Return read-only non-secret provider metadata for consumers."""
        return ProviderMetadata(
            provider_name=self.provider_name,
            provider_kind=self._provider_kind,
            model=self._model,
            base_url=self._base_url,
        )

    def provider_connection_config(self) -> ProviderConnectionConfig:
        """Return provider-owned connection fields for internal runtime calls."""
        return ProviderConnectionConfig(
            provider_kind=self._provider_kind,
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
        )

    def _api_url(self, path: str) -> str:
        """Build an API URL without duplicating the version prefix.

        A base URL already carrying a version segment (``/v1``…``/vN``, e.g.
        Qianfan's ``/v2``, Volcengine's ``/api/v3``, Zhipu's ``/paas/v4``)
        absorbs the canonical ``/v1`` path prefix.
        """
        if path.startswith("/v1/") and _VERSIONED_BASE_URL_RE.search(self._base_url):
            return f"{self._base_url}{path[3:]}"
        return f"{self._base_url}{path}"

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        cfg = config or ChatConfig()
        return self._stream(messages, tools, cfg)

    async def _stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        cfg: ChatConfig,
    ) -> AsyncIterator[StreamEvent]:
        openai_messages: list[dict[str, Any]] = []
        caps = cfg.model_capabilities
        include_reasoning_content = _should_replay_reasoning_content(
            policy=self._compat,
            model=self._model,
            caps=caps,
        )
        if cfg.system:
            explicit_cache_supported = self._compat.supports_explicit_prompt_cache and (
                cfg.cache_mode == "on"
                or (
                    cfg.cache_mode == "auto"
                    and _openrouter_model_likely_supports_explicit_prompt_cache(self._model)
                )
            )
            if cfg.cache_breakpoints and explicit_cache_supported:
                # Split system prompt into cached base + dynamic parts
                content_blocks = []
                for bp in cfg.cache_breakpoints:
                    block: dict[str, Any] = {"type": "text", "text": bp["text"]}
                    if bp.get("cache"):
                        block["cache_control"] = {"type": "ephemeral"}
                    content_blocks.append(block)
                openai_messages.append({"role": "system", "content": content_blocks})
            else:
                openai_messages.append({"role": "system", "content": cfg.system})
        for m in messages:
            openai_messages.extend(
                _build_openai_messages(
                    m,
                    include_reasoning_content=include_reasoning_content,
                    require_assistant_reasoning_content=(
                        _requires_assistant_reasoning_content(self._compat, self._model)
                    ),
                    replay_provider_state=self._replay_provider_state,
                )
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if _uses_max_completion_tokens(self._compat, self._base_url, self._model):
            payload["max_completion_tokens"] = cfg.max_tokens
        else:
            payload["max_tokens"] = cfg.max_tokens
        if self._compat.sends_usage_include:
            payload["usage"] = {"include": True}
        if self._compat.sends_disable_fallbacks:
            # Gateway proxies must not silently substitute another model:
            # SquillaRouter is the single routing authority.
            payload["disable_fallbacks"] = True
        if (
            self._compat.anthropic_top_level_cache
            and cfg.cache_mode in {"auto", "on"}
            and _openrouter_model_is_anthropic(self._model)
        ):
            payload["cache_control"] = {"type": "ephemeral"}
        if _should_send_temperature(
            self._compat,
            self._base_url,
            self._model,
            cfg,
            caps,
        ):
            payload["temperature"] = cfg.temperature
        if cfg.stop_sequences:
            payload["stop"] = cfg.stop_sequences
        if tools:
            payload["tools"] = [
                _build_openai_tool(
                    t,
                    unsupported_keywords=self._compat.tool_schema_unsupported_keywords,
                )
                for t in tools
            ]
            if cfg.tool_choice is not None:
                payload["tool_choice"] = cfg.tool_choice
        if self._compat.supports_provider_routing_pin:
            pinned_provider = self._provider_routing.get(self._model)
            if pinned_provider:
                payload["provider"] = {
                    "order": [pinned_provider],
                    "allow_fallbacks": True,
                }

        # Reasoning injection (gated on thinking being enabled). Gating —
        # which model/capability profile triggers a payload at all — lives
        # here; how each dialect spells it lives in reasoning_dialects.
        thinking_toggle_model = (
            self._model.strip().lower() in self._compat.thinking_toggle_model_ids
        )
        if (caps and caps.supports_reasoning and cfg.thinking) or (
            thinking_toggle_model and cfg.thinking
        ):
            reasoning_format = (
                caps.reasoning_format
                if caps is not None
                else self._compat.default_reasoning_format
            )
            apply_reasoning_enable(
                payload,
                reasoning_format,
                ReasoningEnableArgs(
                    thinking_level=cfg.thinking_level,
                    thinking_budget_tokens=cfg.thinking_budget_tokens,
                ),
            )
        elif thinking_toggle_model:
            # Toggle models need an explicit off payload even without a
            # capability profile (policy gating, independent of dialect).
            payload["thinking"] = {"type": "disabled"}
        elif caps and caps.supports_reasoning:
            apply_reasoning_disable(
                payload,
                caps.reasoning_format,
                ReasoningDisableArgs(
                    model=self._model,
                    disable_reasoning_by_default_models=(
                        self._compat.disable_reasoning_by_default_models
                    ),
                ),
            )

        fallback_reason = (
            "native_is_error_unavailable"
            if any(message.get("role") == "tool" for message in openai_messages)
            else None
        )
        from opensquilla.engine.context_budget import coordinate_provider_context_budget

        budget_decision = coordinate_provider_context_budget(
            payload,
            projection_adapter=self._provider_kind,
            proof_budget=cfg.provider_request_max_chars,
            status_projection_mode="content_envelope",
            fallback_reason=fallback_reason,
        )
        if budget_decision.action == "budget_limited":
            proof = budget_decision.proof or {}
            log.warning("provider.request_budget_exhausted", **proof)
            yield ErrorEvent(
                message=json.dumps(proof, ensure_ascii=False, sort_keys=True),
                code="provider_request_budget_exhausted",
            )
            return
        payload = budget_decision.payload or payload
        if budget_decision.proof is not None:
            log.info("provider.request_proof", **budget_decision.proof)
        try:
            prove_provider_payload_from_env(
                payload,
                projection_adapter=self._provider_kind,
                status_projection_mode="content_envelope",
                fallback_reason=fallback_reason,
            )
        except ProviderRequestBudgetExceededError as exc:
            log.warning("provider.request_budget_exhausted", **exc.proof)
            yield ErrorEvent(
                message=json.dumps(exc.proof, ensure_ascii=False, sort_keys=True),
                code="provider_request_budget_exhausted",
            )
            return

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        headers.update(openrouter_app_headers(self._base_url))
        if self._org_id:
            headers["OpenAI-Organization"] = self._org_id

        tools_acc = ToolStreamAccumulator()
        # Gemini thought_signature streamed on a non-FC text delta. Kept
        # separate from the tool accumulator (whose keys MUST stay int — see
        # _resolve_tool_call_index's next_int_key) so a str key can never
        # poison the next-index computation with a TypeError.
        streamed_thought_signature: str | None = None
        reasoning = ReasoningAccumulator()
        assistant_text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        reasoning_tokens = 0
        cached_tokens = 0
        cache_write_tokens = 0
        billed_cost = 0.0
        cost_source = "none"
        actual_model = self._model
        stop_reason = "stop"
        emitted_stream_event = False

        if os.environ.get("OPENSQUILLA_TRACE_ROUTING"):
            print(
                f"[CALLED] base={self._base_url} model={self._model} "
                f"n_messages={len(openai_messages)}",
                file=sys.stderr,
                flush=True,
            )
        if self._compat.log_payload_cache_shape:
            system_payload = (
                openai_messages[0]
                if openai_messages and openai_messages[0].get("role") == "system"
                else None
            )
            non_system_prefix_item_hashes = _openrouter_non_system_prefix_item_hashes(
                openai_messages
            )
            log.debug(
                "openrouter.payload_cache_shape",
                model=self._model,
                top_level_cache_control=bool(payload.get("cache_control")),
                system_hash=_stable_json_hash(system_payload) if system_payload else "",
                tools_hash=_stable_json_hash(payload.get("tools", [])) if tools else "",
                messages_prefix_hash=_stable_json_hash(openai_messages[:-1]),
                first_non_system_hash=(
                    non_system_prefix_item_hashes[0] if non_system_prefix_item_hashes else ""
                ),
                non_system_prefix_item_hashes=non_system_prefix_item_hashes,
                message_count=len(openai_messages),
            )

        try:
            async with httpx.AsyncClient(
                timeout=(
                    _stream_timeout(cfg.timeout)
                    if self._compat.stream_timeout_fallback
                    else cfg.timeout
                ),
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                async with client.stream(
                    "POST",
                    self._api_url("/v1/chat/completions"),
                    headers=headers,
                    json=payload,
                ) as response:
                    if self._compat.attribution_response_headers:
                        attribution = {
                            name: response.headers[name]
                            for name in self._compat.attribution_response_headers
                            if name in response.headers
                        }
                        if attribution:
                            fallbacks_taken = _coerce_int(
                                attribution.get("x-litellm-attempted-fallbacks")
                            )
                            log_fn = log.warning if fallbacks_taken > 0 else log.info
                            log_fn(
                                "provider.gateway_attribution",
                                provider=self._provider_kind,
                                requested_model=self._model,
                                **{k.replace("-", "_"): v for k, v in attribution.items()},
                            )
                    if response.status_code != 200:
                        body = await response.aread()
                        message = _format_chat_http_error(
                            self._compat.display_name,
                            response.status_code,
                            body,
                        )
                        # Diagnostic: dump payload head (no auth headers)
                        # so 400s from picky upstreams are debuggable. Truncated
                        # to keep memory low.
                        _body_text = (
                            body.decode("utf-8", errors="replace")
                            if isinstance(body, bytes)
                            else str(body)
                        )
                        try:
                            _payload_head = json.dumps(
                                payload,
                                ensure_ascii=False,
                            )[:4000]
                        except Exception:  # noqa: BLE001
                            _payload_head = repr(payload)[:4000]
                        log.warning(
                            "provider.chat_http_error",
                            provider=self._provider_kind,
                            model=self._model,
                            status_code=response.status_code,
                            message=message,
                            response_body=_body_text[:2000],
                            request_payload_head=_payload_head,
                        )
                        yield ErrorEvent(
                            message=message,
                            code=str(response.status_code),
                            retry_after_s=retry_after_from_headers(
                                response.status_code,
                                getattr(response, "headers", None),
                            ),
                        )
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        chunk_model = chunk.get("model")
                        if chunk_model:
                            actual_model = chunk_model

                        # Usage may appear in the final chunk
                        if chunk.get("usage"):
                            (
                                input_tokens,
                                output_tokens,
                                reasoning_tokens,
                                cached_tokens,
                                cache_write_tokens,
                                raw_billed_cost,
                            ) = _usage_fields(chunk["usage"])
                            billed_cost, cost_source = _provider_billed_cost(
                                self._provider_kind,
                                raw_billed_cost,
                            )

                        for choice in chunk.get("choices", []):
                            finish = choice.get("finish_reason")
                            if finish:
                                stop_reason = finish

                            delta = choice.get("delta", {})

                            # Text content
                            text = delta.get("content")
                            if text:
                                emitted_stream_event = True
                                yield TextDeltaEvent(text=text)
                                assistant_text_parts.append(text)

                            # Reasoning content (always parsed, not gated on thinking).
                            # Streamed in real time as ReasoningDeltaEvent; the
                            # accumulator also retains the joined text for DoneEvent.
                            reasoning_details = delta.get("reasoning_details")
                            if reasoning_details:
                                for detail in reasoning_details:
                                    if isinstance(detail, dict):
                                        reasoning_event = reasoning.emit(detail.get("text", ""))
                                        if reasoning_event is not None:
                                            yield reasoning_event
                            reasoning_event = reasoning.emit(delta.get("reasoning_content"))
                            if reasoning_event is not None:
                                yield reasoning_event

                            # Gemini thought_signature on non-FC deltas
                            # (streamed thinking path): Gemini sends it on
                            # the top-level delta instead of attaching it to
                            # a tool_call. Keep it out of the tool accumulator.
                            ts_delta = delta.get("thought_signature")
                            if isinstance(ts_delta, str) and ts_delta:
                                streamed_thought_signature = ts_delta

                            # Tool calls (may stream over multiple chunks)
                            for tc in delta.get("tool_calls", []):
                                idx = _resolve_tool_call_index(tc, tools_acc)
                                function = tc.get("function", {}) or {}
                                for tool_event in tools_acc.append_or_start(
                                    idx,
                                    tool_call_id=tc.get("id"),
                                    tool_name=function.get("name", ""),
                                    fragment=function.get("arguments", ""),
                                ):
                                    emitted_stream_event = True
                                    yield tool_event

                                # Gemini thought_signature (OpenAI compat format):
                                # tool_calls[].extra_content.google.thought_signature
                                sig = (
                                    (tc.get("extra_content") or {})
                                    .get("google", {})
                                    .get("thought_signature")
                                )
                                if isinstance(sig, str) and sig:
                                    tools_acc.set_metadata(idx, "thought_signature", sig)

                    # Chat Completions has no per-call stop event: close every
                    # assembled call once the stream ends.
                    for tool_event in tools_acc.finish_all():
                        emitted_stream_event = True
                        yield tool_event

                    # Last-resort MiniMax compatibility: some OpenRouter
                    # upstreams leak native MiniMax XML tool calls as text
                    # instead of structured tool_calls. Only synthesize calls
                    # for provider kinds known to leak the text protocol, when
                    # no structured calls arrived, tools were offered, and the
                    # parsed tool name is explicitly allowed by this turn.
                    if (
                        not tools_acc.has_calls
                        and tools
                        and assistant_text_parts
                        and self._compat.text_tool_synthesis
                    ):
                        full_text = "".join(assistant_text_parts)
                        for event in _synthesize_text_tool_events(full_text, tools):
                            emitted_stream_event = True
                            yield event

                    # Assemble reasoning from the structured fields already
                    # streamed in real time via ReasoningDeltaEvent.
                    reasoning_text = reasoning.finalize()

                    # Fallback: <think> tag extraction from accumulated text.
                    # This format embeds reasoning inside the answer text, so it
                    # can only be recovered after the full text arrives — it is
                    # inherently non-streamable and stays a turn-end assembly.
                    caps = cfg.model_capabilities
                    if not reasoning_text and caps and caps.reasoning_format == "think_tags":
                        full_text = "".join(assistant_text_parts)
                        reasoning_text = _extract_think_tags(full_text) or None

                    # Gemini thought_signature: extract from the first tool call
                    # that carries one (Gemini attaches it to the first FC only).
                    # Fallback: when Gemini streams the signature on a non-FC
                    # text delta (no tool_call carries it), use the streamed one.
                    gemini_thought_sig = cast(
                        "str | None",
                        tools_acc.first_metadata("thought_signature"),
                    )
                    if gemini_thought_sig is None:
                        gemini_thought_sig = streamed_thought_signature

                    yield DoneEvent(
                        stop_reason=stop_reason,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_content=reasoning_text or None,
                        thinking_signature=gemini_thought_sig,
                        reasoning_tokens=reasoning_tokens,
                        cached_tokens=cached_tokens,
                        cache_write_tokens=cache_write_tokens,
                        billed_cost=billed_cost,
                        model=actual_model,
                        cost_source=cost_source,
                    )

        except httpx.TimeoutException as exc:
            if self._compat.stream_timeout_fallback and not emitted_stream_event:
                log.warning(
                    "openrouter.stream_timeout_fallback_started",
                    model=self._model,
                    timeout_seconds=cfg.timeout,
                    timeout_phase=type(exc).__name__,
                    error=str(exc) or repr(exc),
                )
                yield ProviderHeartbeatEvent(
                    phase="llm_fallback",
                    message="OpenRouter stream timed out; retrying without streaming.",
                )
                try:
                    async for fallback_event in self._complete_non_stream(
                        payload=payload,
                        headers=headers,
                        cfg=cfg,
                        tools=tools,
                        timeout_exc=exc,
                    ):
                        yield fallback_event
                except Exception as fallback_exc:  # noqa: BLE001 - see contract note below
                    log.exception(
                        "provider.stream_internal_error",
                        provider=self._provider_kind,
                        model=self._model,
                    )
                    yield ErrorEvent(
                        message=f"Provider response handling failed: {fallback_exc}",
                        code="provider_internal",
                    )
                return
            yield ErrorEvent(message=f"Request timed out: {exc}", code="timeout")
        except httpx.RequestError as exc:
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")
        except Exception as exc:  # noqa: BLE001 - chat() contract: ErrorEvent instead of raising
            log.exception(
                "provider.stream_internal_error",
                provider=self._provider_kind,
                model=self._model,
            )
            yield ErrorEvent(
                message=f"Provider response handling failed: {exc}",
                code="provider_internal",
            )

    async def _complete_non_stream(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        cfg: ChatConfig,
        tools: list[ToolDefinition] | None,
        timeout_exc: httpx.TimeoutException,
    ) -> AsyncIterator[StreamEvent]:
        fallback_payload = dict(payload)
        fallback_payload["stream"] = False
        fallback_payload.pop("stream_options", None)
        fallback_headers = dict(headers)
        fallback_headers["Accept"] = "application/json"

        try:
            async with httpx.AsyncClient(
                timeout=cfg.timeout,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                response = await client.post(
                    self._api_url("/v1/chat/completions"),
                    headers=fallback_headers,
                    json=fallback_payload,
                )
        except httpx.TimeoutException:
            log.warning(
                "openrouter.non_stream_fallback_timeout",
                model=self._model,
                timeout_seconds=cfg.timeout,
                stream_error=str(timeout_exc),
            )
            yield ErrorEvent(message=f"Request timed out: {timeout_exc}", code="timeout")
            return
        except httpx.RequestError as exc:
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")
            return

        if response.status_code != 200:
            yield ErrorEvent(
                message=_format_chat_http_error(
                    self._compat.display_name,
                    response.status_code,
                    response.text,
                ),
                code=str(response.status_code),
                retry_after_s=retry_after_from_headers(
                    response.status_code,
                    getattr(response, "headers", None),
                ),
            )
            return

        try:
            data = response.json()
        except json.JSONDecodeError:
            yield ErrorEvent(message="Invalid JSON response from provider", code="invalid_json")
            return

        actual_model = data.get("model") or self._model
        (
            input_tokens,
            output_tokens,
            reasoning_tokens,
            cached_tokens,
            cache_write_tokens,
            raw_billed_cost,
        ) = _usage_fields(data.get("usage"))
        billed_cost, cost_source = _provider_billed_cost(self._provider_kind, raw_billed_cost)
        stop_reason = "stop"
        assistant_text_parts: list[str] = []
        reasoning = ReasoningAccumulator()
        tools_acc = ToolStreamAccumulator()

        for choice in data.get("choices", []):
            if choice.get("finish_reason"):
                stop_reason = choice["finish_reason"]
            message = choice.get("message") or {}

            text = message.get("content")
            if isinstance(text, str) and text:
                assistant_text_parts.append(text)
                yield TextDeltaEvent(text=text)

            reasoning_details = message.get("reasoning_details")
            if reasoning_details:
                for detail in reasoning_details:
                    if isinstance(detail, dict):
                        reasoning_event = reasoning.emit(detail.get("text", ""))
                        if reasoning_event is not None:
                            yield reasoning_event
            for key in ("reasoning_content", "reasoning"):
                reasoning_str = message.get(key)
                if isinstance(reasoning_str, str):
                    reasoning_event = reasoning.emit(reasoning_str)
                    if reasoning_event is not None:
                        yield reasoning_event

            for tc in message.get("tool_calls") or []:
                function = tc.get("function") or {}
                tool_use_id = tc.get("id") or f"call_{uuid4().hex[:12]}"
                call_key = tools_acc.next_int_key()
                for tool_event in tools_acc.start(
                    call_key,
                    tool_use_id=tool_use_id,
                    tool_name=function.get("name") or "",
                ):
                    yield tool_event
                arguments_text = function.get("arguments") or ""
                if arguments_text:
                    for tool_event in tools_acc.append(call_key, arguments_text):
                        yield tool_event
                sig = (tc.get("extra_content") or {}).get("google", {}).get("thought_signature")
                if isinstance(sig, str) and sig:
                    tools_acc.set_metadata(call_key, "thought_signature", sig)
                for tool_event in tools_acc.finish(call_key):
                    yield tool_event

        if (
            not tools_acc.has_calls
            and tools
            and assistant_text_parts
            and self._compat.text_tool_synthesis
        ):
            for event in _synthesize_text_tool_events("".join(assistant_text_parts), tools):
                yield event

        reasoning_text = reasoning.finalize()
        if (
            not reasoning_text
            and cfg.model_capabilities
            and cfg.model_capabilities.reasoning_format == "think_tags"
        ):
            reasoning_text = _extract_think_tags("".join(assistant_text_parts)) or None

        yield DoneEvent(
            stop_reason=stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_content=reasoning_text or None,
            thinking_signature=cast(
                "str | None",
                tools_acc.first_metadata("thought_signature"),
            ),
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            billed_cost=billed_cost,
            model=actual_model,
            cost_source=cost_source,
        )

    async def list_models(self) -> list[ModelInfo]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        headers.update(openrouter_app_headers(self._base_url))
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                resp = await client.get(self._api_url("/v1/models"), headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return [
                    ModelInfo(
                        provider=self._provider_kind,
                        model_id=m["id"],
                        display_name=m.get("name", m.get("id", "")),
                        context_window=m.get("context_length", 0),
                        max_output_tokens=(m.get("top_provider") or {}).get("max_completion_tokens")
                        or 0,
                    )
                    for m in data.get("data", [])
                ]
        except Exception:
            return []
