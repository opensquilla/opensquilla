"""OpenAIProvider — streams via OpenAI Chat Completions API using httpx."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

if TYPE_CHECKING:
    from opensquilla.engine.types import ThinkingLevel

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env

from .minimax_compat import contains_minimax_protocol, parse_minimax_tool_calls
from .openrouter_attribution import openrouter_app_headers
from .protocol import ProviderConnectionConfig, ProviderMetadata
from .types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelCapabilities,
    ModelInfo,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolUseDeltaEvent,
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


def _resolve_reasoning_effort(level: ThinkingLevel | None, budget: int) -> str:
    """Map ThinkingLevel to OpenRouter/DeepSeek effort string."""
    from opensquilla.engine.types import (
        ThinkingLevel,  # local: avoids circular import at module load
    )

    _level_map = {
        ThinkingLevel.MINIMAL: "minimal",
        ThinkingLevel.LOW: "low",
        ThinkingLevel.MEDIUM: "medium",
        ThinkingLevel.HIGH: "high",
        ThinkingLevel.XHIGH: "xhigh",
    }
    if level and level in _level_map:
        return _level_map[level]
    if budget <= 1024:
        return "low"
    elif budget <= 10000:
        return "medium"
    else:
        return "high"


def _resolve_deepseek_reasoning_effort(level: ThinkingLevel | None) -> str:
    """Map OpenSquilla thinking levels to DeepSeek V4's documented effort values."""
    from opensquilla.engine.types import (
        ThinkingLevel,  # local: avoids circular import at module load
    )

    if level == ThinkingLevel.XHIGH:
        return "max"
    return "high"


def _gemini_supports_reasoning_none(model: str) -> bool:
    """Return True for Gemini OpenAI-compatible models with documented off control."""
    model_name = model.rsplit("/", 1)[-1].strip().lower()
    return model_name.startswith("gemini-2.5-flash")


def _extract_think_tags(text: str) -> str:
    """Extract content from <think> tags. Returns empty string if none found."""
    matches = re.findall(r"<think>([\s\S]*?)</think>", text)
    return "\n".join(matches) if matches else ""


def _strip_think_tags(text: str) -> str:
    """Remove <think> tags from text, including unclosed trailing tags."""
    result = re.sub(r"<think>[\s\S]*?</think>", "", text)
    result = re.sub(r"<think>[\s\S]*$", "", result)
    return result.strip()


def _should_disable_openrouter_reasoning_by_default(model: str) -> bool:
    """Return True for OpenRouter models known to default into reasoning streams.

    OpenRouter's reasoning controls are model/provider-specific: GLM 4.5 can be
    stabilized by explicitly disabling reasoning when OpenSquilla has not requested
    thinking, while MiniMax reasoning endpoints reject that same payload.
    """
    return model.strip().lower() in {
        "z-ai/glm-4.5",
        "z-ai/glm-4.5-air",
        "z-ai/glm-5",
        "z-ai/glm-5.1",
    }


def _direct_openai_uses_max_completion_tokens(
    provider_kind: str,
    base_url: str,
    model: str,
) -> bool:
    if provider_kind != "openai" or "api.openai.com" not in base_url.lower():
        return False
    model_name = model.rsplit("/", 1)[-1].strip().lower()
    return model_name.startswith(("gpt-5", "o1", "o3", "o4"))


def _is_kimi_fixed_sampling_model(provider_kind: str, model: str) -> bool:
    if provider_kind != "moonshot":
        return False
    model_name = model.rsplit("/", 1)[-1].strip().lower()
    return model_name.startswith(("kimi-k2.5", "kimi-k2.6"))


def _should_send_temperature(
    provider_kind: str,
    base_url: str,
    model: str,
    cfg: ChatConfig,
    caps: Any,
) -> bool:
    if cfg.temperature is None:
        return False
    if _is_kimi_fixed_sampling_model(provider_kind, model) and cfg.temperature != 1.0:
        return False
    if (
        provider_kind == "openai"
        and "api.openai.com" in base_url.lower()
        and cfg.thinking
        and bool(caps and caps.supports_reasoning)
    ):
        model_name = model.rsplit("/", 1)[-1].strip().lower()
        if model_name.startswith(("gpt-5.4", "gpt-5.5")):
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
    ``prompt_cache_miss_tokens``. Use ``in`` instead so a real zero wins.
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
    #   - usage.prompt_cache_miss_tokens             — DeepSeek (miss == write under their
    #     prompt-cache pricing model).
    #   - prompt_tokens_details.cache_creation_tokens — defensive fallback.
    cache_write_tokens = _first_present(
        (usage, "cache_creation_input_tokens"),
        (prompt_details, "cache_write_tokens"),
        (usage, "cache_write_tokens"),
        (usage, "prompt_cache_miss_tokens"),
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
    if provider_kind == "openrouter" and raw_billed_cost > 0.0:
        return raw_billed_cost, "provider_billed"
    return 0.0, "none"


def _resolve_tool_call_index(
    tc: Mapping[str, Any],
    pending_calls: Mapping[int, dict[str, Any]],
    *,
    provider_kind: str,
) -> int:
    if "index" in tc:
        return _coerce_int(tc["index"])
    if provider_kind != "gemini":
        raise KeyError("index")
    if len(pending_calls) == 1:
        return cast(int, next(iter(pending_calls)))
    return max(pending_calls.keys(), default=-1) + 1


def _stream_timeout(timeout: float) -> httpx.Timeout:
    connect = _coerce_float(os.environ.get("OPENSQUILLA_LLM_STREAM_CONNECT_TIMEOUT_SECONDS"))
    if connect <= 0:
        connect = 12.0
    connect = min(connect, max(timeout, 1.0))
    return httpx.Timeout(timeout, connect=connect, write=10.0, pool=10.0)


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


def _build_openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema.model_dump(exclude_none=True),
        },
    }


def _openrouter_model_likely_supports_explicit_prompt_cache(model: str) -> bool:
    model_l = model.strip().lower()
    return model_l.startswith(
        (
            "anthropic/",
            "google/",
            "deepseek/",
            "x-ai/",
        )
    )


def _openrouter_model_is_anthropic(model: str) -> bool:
    return model.strip().lower().startswith("anthropic/")


def _openrouter_anthropic_should_use_top_level_cache(
    *,
    provider_kind: str,
    model: str,
    cfg: ChatConfig,
) -> bool:
    return (
        provider_kind == "openrouter"
        and cfg.cache_mode in {"auto", "on"}
        and _openrouter_model_is_anthropic(model)
    )


def _stable_json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


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


def _is_direct_deepseek_v4_model_id(model: str) -> bool:
    return model.strip().lower() in {"deepseek-v4-flash", "deepseek-v4-pro"}


def _is_direct_deepseek_v4_request(provider_kind: str, model: str) -> bool:
    return provider_kind == "deepseek" and _is_direct_deepseek_v4_model_id(model)


def _should_replay_reasoning_content(
    *,
    provider_kind: str,
    model: str,
    caps: ModelCapabilities | None,
) -> bool:
    if provider_kind == "openrouter":
        if not caps or not caps.supports_reasoning:
            return False
        return caps.reasoning_format == "openrouter"
    if _is_direct_deepseek_v4_request(provider_kind, model):
        return True
    if not caps or not caps.supports_reasoning:
        return False
    return (
        provider_kind == "deepseek"
        and caps.reasoning_format == "deepseek"
        and _is_direct_deepseek_v4_model_id(model)
    )


def _build_openai_messages(
    msg: Message,
    *,
    include_reasoning_content: bool = True,
    require_assistant_reasoning_content: bool = False,
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

    for block in msg.content:
        if block.type == "text":
            parts.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    },
                }
            )
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
                    "content": (
                        block.content
                        if isinstance(block.content, str)
                        else json.dumps(block.content)
                    ),
                }
            )

    # Tool results → one message per result (OpenAI requirement)
    if tool_results:
        return tool_results

    # Assistant message with tool_calls (preserve text alongside calls)
    if tool_calls:
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
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._proxy = _resolve_llm_proxy(proxy)
        self._org_id = org_id
        inferred_kind = "openrouter" if "openrouter.ai" in self._base_url else "openai"
        self._provider_kind = provider_kind or inferred_kind
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
        """Build an API URL without duplicating the version prefix."""
        if self._base_url.endswith("/v1") and path.startswith("/v1/"):
            return f"{self._base_url}{path[3:]}"
        if self._base_url.endswith("/v2") and path.startswith("/v1/"):
            return f"{self._base_url}{path[3:]}"
        if self._base_url.endswith("/v3") and path.startswith("/v1/"):
            return f"{self._base_url}{path[3:]}"
        if self._base_url.endswith("/v4") and path.startswith("/v1/"):
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
            provider_kind=self._provider_kind,
            model=self._model,
            caps=caps,
        )
        if cfg.system:
            explicit_cache_supported = self._provider_kind == "openrouter" and (
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
                        _is_direct_deepseek_v4_request(self._provider_kind, self._model)
                    ),
                )
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if _direct_openai_uses_max_completion_tokens(
            self._provider_kind,
            self._base_url,
            self._model,
        ):
            payload["max_completion_tokens"] = cfg.max_tokens
        else:
            payload["max_tokens"] = cfg.max_tokens
        if self._provider_kind == "openrouter":
            payload["usage"] = {"include": True}
            if _openrouter_anthropic_should_use_top_level_cache(
                provider_kind=self._provider_kind,
                model=self._model,
                cfg=cfg,
            ):
                payload["cache_control"] = {"type": "ephemeral"}
        if _should_send_temperature(
            self._provider_kind,
            self._base_url,
            self._model,
            cfg,
            caps,
        ):
            payload["temperature"] = cfg.temperature
        if cfg.stop_sequences:
            payload["stop"] = cfg.stop_sequences
        if tools:
            payload["tools"] = [_build_openai_tool(t) for t in tools]
        if self._provider_kind == "openrouter":
            pinned_provider = self._provider_routing.get(self._model)
            if pinned_provider:
                payload["provider"] = {
                    "only": [pinned_provider],
                    "allow_fallbacks": True,
                }

        # Reasoning injection (gated on thinking being enabled)
        direct_deepseek_v4 = _is_direct_deepseek_v4_request(self._provider_kind, self._model)
        if (caps and caps.supports_reasoning and cfg.thinking) or (
            direct_deepseek_v4 and cfg.thinking
        ):
            effort = _resolve_reasoning_effort(cfg.thinking_level, cfg.thinking_budget_tokens)
            reasoning_format = caps.reasoning_format if caps is not None else "deepseek"
            if reasoning_format == "openrouter":
                payload["reasoning"] = {"effort": effort}
            elif reasoning_format == "openai":
                payload["reasoning_effort"] = effort
            elif reasoning_format == "deepseek":
                payload["thinking"] = {"type": "enabled"}
                payload["reasoning_effort"] = _resolve_deepseek_reasoning_effort(
                    cfg.thinking_level
                )
            elif reasoning_format == "gemini":
                payload["reasoning_effort"] = effort
            elif reasoning_format == "zai":
                payload["thinking"] = {"type": "enabled"}
            elif reasoning_format == "dashscope":
                payload["enable_thinking"] = True
                payload["thinking_budget"] = cfg.thinking_budget_tokens
            elif reasoning_format in {"moonshot", "volcengine"}:
                payload["thinking"] = {"type": "enabled"}
        elif direct_deepseek_v4 or (
            caps and caps.supports_reasoning and caps.reasoning_format == "deepseek"
        ):
            payload["thinking"] = {"type": "disabled"}
        elif (
            caps
            and caps.supports_reasoning
            and caps.reasoning_format == "gemini"
            and _gemini_supports_reasoning_none(self._model)
        ):
            payload["reasoning_effort"] = "none"
        elif caps and caps.supports_reasoning and caps.reasoning_format == "zai":
            payload["thinking"] = {"type": "disabled"}
        elif caps and caps.supports_reasoning and caps.reasoning_format == "dashscope":
            payload["enable_thinking"] = False
        elif caps and caps.supports_reasoning and caps.reasoning_format in {
            "moonshot",
            "volcengine",
        }:
            payload["thinking"] = {"type": "disabled"}
        elif (
            self._provider_kind == "openrouter"
            and caps
            and caps.supports_reasoning
            and caps.reasoning_format == "openrouter"
            and _should_disable_openrouter_reasoning_by_default(self._model)
        ):
            payload["reasoning"] = {"enabled": False}

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        headers.update(openrouter_app_headers(self._base_url))
        if self._org_id:
            headers["OpenAI-Organization"] = self._org_id

        # tool_call accumulator: index -> {id, name, json_parts}
        pending_calls: dict[int, dict[str, Any]] = {}
        reasoning_parts: list[str] = []
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
        if self._provider_kind == "openrouter":
            system_payload = (
                openai_messages[0]
                if openai_messages and openai_messages[0].get("role") == "system"
                else None
            )
            log.debug(
                "openrouter.payload_cache_shape",
                model=self._model,
                top_level_cache_control=bool(payload.get("cache_control")),
                system_hash=_stable_json_hash(system_payload) if system_payload else "",
                tools_hash=_stable_json_hash(payload.get("tools", [])) if tools else "",
                messages_prefix_hash=_stable_json_hash(openai_messages[:-1]),
                message_count=len(openai_messages),
            )

        try:
            async with httpx.AsyncClient(
                timeout=(
                    _stream_timeout(cfg.timeout)
                    if self._provider_kind == "openrouter"
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
                    if response.status_code != 200:
                        body = await response.aread()
                        yield ErrorEvent(
                            message=f"HTTP {response.status_code}: {body.decode()}",
                            code=str(response.status_code),
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

                            # Reasoning content (always parsed, not gated on thinking)
                            reasoning_details = delta.get("reasoning_details")
                            if reasoning_details:
                                for detail in reasoning_details:
                                    if isinstance(detail, dict):
                                        text_val = detail.get("text", "")
                                        if text_val:
                                            reasoning_parts.append(text_val)
                            reasoning_str = delta.get("reasoning_content")
                            if reasoning_str:
                                reasoning_parts.append(reasoning_str)

                            # Tool calls (may stream over multiple chunks)
                            for tc in delta.get("tool_calls", []):
                                idx = _resolve_tool_call_index(
                                    tc,
                                    pending_calls,
                                    provider_kind=self._provider_kind,
                                )
                                if idx not in pending_calls:
                                    pending_calls[idx] = {
                                        "id": tc.get("id", f"call_{uuid4().hex[:12]}"),
                                        "name": tc.get("function", {}).get("name", ""),
                                        "parts": [],
                                    }
                                    emitted_stream_event = True
                                    yield ToolUseStartEvent(
                                        tool_use_id=pending_calls[idx]["id"],
                                        tool_name=pending_calls[idx]["name"],
                                    )
                                else:
                                    # id/name may arrive in later chunks
                                    if tc.get("id"):
                                        pending_calls[idx]["id"] = tc["id"]
                                    fname = tc.get("function", {}).get("name", "")
                                    if fname:
                                        pending_calls[idx]["name"] = fname

                                fragment = tc.get("function", {}).get("arguments", "")
                                if fragment:
                                    pending_calls[idx]["parts"].append(fragment)
                                    emitted_stream_event = True
                                    yield ToolUseDeltaEvent(
                                        tool_use_id=pending_calls[idx]["id"],
                                        json_fragment=fragment,
                                    )

                    # Emit ToolUseEnd for each completed call
                    for call in pending_calls.values():
                        full_json = "".join(call["parts"])
                        try:
                            args = json.loads(full_json) if full_json else {}
                        except json.JSONDecodeError:
                            args = {"_raw": full_json}
                        emitted_stream_event = True
                        yield ToolUseEndEvent(
                            tool_use_id=call["id"],
                            tool_name=call["name"],
                            arguments=args,
                        )

                    # Last-resort MiniMax compatibility: some OpenRouter
                    # upstreams leak native MiniMax XML tool calls as text
                    # instead of structured tool_calls. Only synthesize calls
                    # when no structured calls arrived, tools were offered, and
                    # the parsed tool name is explicitly allowed by this turn.
                    if not pending_calls and tools and assistant_text_parts:
                        full_text = "".join(assistant_text_parts)
                        for event in _synthesize_text_tool_events(full_text, tools):
                            emitted_stream_event = True
                            yield event

                    # Assemble reasoning from structured fields
                    reasoning_text = "".join(reasoning_parts)

                    # Fallback: <think> tag extraction from accumulated text
                    caps = cfg.model_capabilities
                    if not reasoning_text and caps and caps.reasoning_format == "think_tags":
                        full_text = "".join(assistant_text_parts)
                        reasoning_text = _extract_think_tags(full_text)

                    yield DoneEvent(
                        stop_reason=stop_reason,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_content=reasoning_text or None,
                        reasoning_tokens=reasoning_tokens,
                        cached_tokens=cached_tokens,
                        cache_write_tokens=cache_write_tokens,
                        billed_cost=billed_cost,
                        model=actual_model,
                        cost_source=cost_source,
                    )

        except httpx.TimeoutException as exc:
            if self._provider_kind == "openrouter" and not emitted_stream_event:
                async for fallback_event in self._complete_non_stream(
                    payload=payload,
                    headers=headers,
                    cfg=cfg,
                    tools=tools,
                    timeout_exc=exc,
                ):
                    yield fallback_event
                return
            yield ErrorEvent(message=f"Request timed out: {exc}", code="timeout")
        except httpx.RequestError as exc:
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")

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
            yield ErrorEvent(message=f"Request timed out: {timeout_exc}", code="timeout")
            return
        except httpx.RequestError as exc:
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")
            return

        if response.status_code != 200:
            yield ErrorEvent(
                message=f"HTTP {response.status_code}: {response.text}",
                code=str(response.status_code),
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
        reasoning_parts: list[str] = []
        emitted_structured_tool = False

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
                        text_val = detail.get("text", "")
                        if text_val:
                            reasoning_parts.append(text_val)
            for key in ("reasoning_content", "reasoning"):
                reasoning_str = message.get(key)
                if isinstance(reasoning_str, str) and reasoning_str:
                    reasoning_parts.append(reasoning_str)

            for tc in message.get("tool_calls") or []:
                function = tc.get("function") or {}
                tool_use_id = tc.get("id") or f"call_{uuid4().hex[:12]}"
                tool_name = function.get("name") or ""
                arguments_text = function.get("arguments") or ""
                emitted_structured_tool = True
                yield ToolUseStartEvent(tool_use_id=tool_use_id, tool_name=tool_name)
                if arguments_text:
                    yield ToolUseDeltaEvent(
                        tool_use_id=tool_use_id,
                        json_fragment=arguments_text,
                    )
                try:
                    arguments = json.loads(arguments_text) if arguments_text else {}
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments_text}
                yield ToolUseEndEvent(
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )

        if not emitted_structured_tool and tools and assistant_text_parts:
            for event in _synthesize_text_tool_events("".join(assistant_text_parts), tools):
                yield event

        reasoning_text = "".join(reasoning_parts)
        if (
            not reasoning_text
            and cfg.model_capabilities
            and cfg.model_capabilities.reasoning_format == "think_tags"
        ):
            reasoning_text = _extract_think_tags("".join(assistant_text_parts))

        yield DoneEvent(
            stop_reason=stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_content=reasoning_text or None,
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
                        provider=self.provider_name,
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
