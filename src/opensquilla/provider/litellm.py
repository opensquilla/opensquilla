"""LiteLLMProvider — streams via litellm.acompletion() for 100+ LLM backends."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import structlog

from .protocol import ProviderConnectionConfig, ProviderMetadata
from .types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelInfo,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)

log = structlog.get_logger(__name__)


def _build_openai_messages(msg: Message) -> list[dict]:
    """Convert an opensquilla Message into OpenAI-format message dicts."""
    if isinstance(msg.content, str):
        return [{"role": msg.role, "content": msg.content}]

    parts = []
    tool_calls = []
    tool_results = []

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

    if tool_results:
        return tool_results
    if tool_calls:
        result = {"role": msg.role, "tool_calls": tool_calls}
        text = " ".join(p["text"] for p in parts if p.get("type") == "text")
        if text:
            result["content"] = text
        return [result]

    has_non_text = any(p["type"] != "text" for p in parts)
    if has_non_text:
        return [{"role": msg.role, "content": parts}]
    content = " ".join(p["text"] for p in parts if p["type"] == "text")
    return [{"role": msg.role, "content": content}]


def _build_tool(tool: ToolDefinition) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema.model_dump(exclude_none=True),
        },
    }


class LiteLLMProvider:
    """Streams from any LiteLLM-supported provider via litellm.acompletion()."""

    provider_name = "litellm"

    def __init__(
        self,
        api_key: str = "",
        model: str = "openai/gpt-4o-mini",
        api_base: str = "",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_base = api_base

    @property
    def model(self) -> str:
        return self._model

    def provider_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_name=self.provider_name,
            provider_kind="litellm",
            model=self._model,
            base_url=self._api_base,
        )

    def provider_connection_config(self) -> ProviderConnectionConfig:
        return ProviderConnectionConfig(
            provider_kind="litellm",
            model=self._model,
            api_key=self._api_key,
            base_url=self._api_base,
        )

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
        import litellm

        openai_messages: list[dict] = []
        if cfg.system:
            openai_messages.append({"role": "system", "content": cfg.system})
        for m in messages:
            openai_messages.extend(_build_openai_messages(m))

        kwargs = {
            "model": self._model,
            "messages": openai_messages,
            "max_tokens": cfg.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "drop_params": True,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if cfg.temperature is not None:
            kwargs["temperature"] = cfg.temperature
        if cfg.stop_sequences:
            kwargs["stop"] = cfg.stop_sequences
        if tools:
            kwargs["tools"] = [_build_tool(t) for t in tools]

        pending_calls: dict[int, dict] = {}
        input_tokens = 0
        output_tokens = 0
        actual_model = self._model
        stop_reason = "stop"

        try:
            response = await litellm.acompletion(**kwargs)

            async for chunk in response:
                usage = getattr(chunk, "usage", None)
                if usage:
                    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(usage, "completion_tokens", 0) or 0

                for choice in chunk.choices:
                    finish = getattr(choice, "finish_reason", None)
                    if finish:
                        stop_reason = finish

                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue

                    text = getattr(delta, "content", None)
                    if text:
                        yield TextDeltaEvent(text=text)

                    for tc in getattr(delta, "tool_calls", None) or []:
                        idx = getattr(tc, "index", 0)
                        if idx not in pending_calls:
                            tc_id = getattr(tc, "id", None) or f"call_{uuid4().hex[:12]}"
                            func = getattr(tc, "function", None)
                            tc_name = getattr(func, "name", "") if func else ""
                            pending_calls[idx] = {
                                "id": tc_id,
                                "name": tc_name,
                                "parts": [],
                            }
                            yield ToolUseStartEvent(
                                tool_use_id=pending_calls[idx]["id"],
                                tool_name=pending_calls[idx]["name"],
                            )
                        else:
                            if getattr(tc, "id", None):
                                pending_calls[idx]["id"] = tc.id
                            func = getattr(tc, "function", None)
                            if func and getattr(func, "name", None):
                                pending_calls[idx]["name"] = func.name

                        func = getattr(tc, "function", None)
                        fragment = getattr(func, "arguments", "") if func else ""
                        if fragment:
                            pending_calls[idx]["parts"].append(fragment)
                            yield ToolUseDeltaEvent(
                                tool_use_id=pending_calls[idx]["id"],
                                json_fragment=fragment,
                            )

            for call in pending_calls.values():
                full_json = "".join(call["parts"])
                try:
                    args = json.loads(full_json) if full_json else {}
                except json.JSONDecodeError:
                    args = {"_raw": full_json}
                yield ToolUseEndEvent(
                    tool_use_id=call["id"],
                    tool_name=call["name"],
                    arguments=args,
                )

            yield DoneEvent(
                stop_reason=stop_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=actual_model,
            )

        except Exception as exc:
            log.warning("litellm.chat_error", model=self._model, error=str(exc))
            yield ErrorEvent(
                message=str(exc),
                code=type(exc).__name__,
            )

    async def list_models(self) -> list[ModelInfo]:
        try:
            import litellm

            models = litellm.model_list or []
            return [
                ModelInfo(
                    provider="litellm",
                    model_id=m,
                    display_name=m,
                )
                for m in models[:50]
            ]
        except Exception:
            return []
