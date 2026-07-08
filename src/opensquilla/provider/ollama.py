"""OllamaProvider — streams via Ollama local/cloud API using httpx."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env
from opensquilla.secrets import clean_header_secret

from .stream_assembly import ToolStreamAccumulator
from .trace_recorder import LLMTraceRecorder
from .types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelInfo,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
)

log = structlog.get_logger(__name__)

_OLLAMA_DEFAULT_BASE = "http://localhost:11434"
# Ollama's server default num_ctx is 2048, which silently truncates the front of
# an agent prompt (system prompt + tool schemas) and makes tool use look broken.
# Default to a context window large enough for real agent turns; callers can
# override via the ``num_ctx`` constructor argument.
_OLLAMA_DEFAULT_NUM_CTX = 8192


def _build_ollama_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema.model_dump(exclude_none=True),
        },
    }


def _tool_result_content(block: Any) -> str:
    content = block.content
    return content if isinstance(content, str) else json.dumps(content)


def _build_ollama_messages(
    msg: Message,
    tool_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert one internal message into one or more Ollama chat messages.

    A single message may expand into several Ollama messages: assistant turns
    carry their ``tool_calls`` so the model keeps a record of what it invoked,
    and each ``tool_result`` block becomes its own ``tool`` role message (Ollama
    has no notion of bundled parallel results) tagged with ``tool_name`` so the
    model can correlate the result with the call.
    """
    if isinstance(msg.content, str):
        return [{"role": msg.role, "content": msg.content}]

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    images: list[str] = []
    tool_messages: list[dict[str, Any]] = []

    for block in msg.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({"function": {"name": block.name, "arguments": block.input}})
        elif block.type == "image":
            # Ollama expects raw base64 strings in `images`; it does not fetch URLs.
            if block.source_type == "base64":
                images.append(block.data)
        elif block.type == "tool_result":
            tool_message: dict[str, Any] = {
                "role": "tool",
                "content": _tool_result_content(block),
            }
            name = tool_names.get(block.tool_use_id)
            if name:
                tool_message["tool_name"] = name
            tool_messages.append(tool_message)

    out: list[dict[str, Any]] = []
    if text_parts or tool_calls or images:
        main: dict[str, Any] = {"role": msg.role, "content": " ".join(text_parts)}
        if tool_calls:
            main["tool_calls"] = tool_calls
        if images:
            main["images"] = images
        out.append(main)
    out.extend(tool_messages)
    return out


def _convert_messages(messages: list[Message], system: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})

    # Map tool_use ids to their tool name so tool results can be correlated.
    tool_names: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg.content, list):
            for block in msg.content:
                if block.type == "tool_use":
                    tool_names[block.id] = block.name

    for msg in messages:
        out.extend(_build_ollama_messages(msg, tool_names))
    return out


class OllamaProvider:
    """Streams from an Ollama instance (local or cloud) using /api/chat."""

    provider_name = "ollama"

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = _OLLAMA_DEFAULT_BASE,
        proxy: str | None = None,
        api_key: str | None = None,
        num_ctx: int | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._proxy = proxy or None
        self._api_key = clean_header_secret(api_key, label="Ollama API key") if api_key else ""
        self._num_ctx = num_ctx or _OLLAMA_DEFAULT_NUM_CTX

    @property
    def model(self) -> str:
        """Model id this provider was configured with.

        Public so callers (e.g. derived-cache key construction) can identify
        the underlying model without prying at private state.
        """
        return self._model

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

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
        ollama_messages = _convert_messages(messages, cfg.system)

        options: dict[str, Any] = {
            "num_predict": cfg.max_tokens,
            "num_ctx": self._num_ctx,
        }
        if cfg.temperature is not None:
            options["temperature"] = cfg.temperature

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ollama_messages,
            "stream": True,
            "options": options,
        }
        if tools:
            payload["tools"] = [_build_ollama_tool(t) for t in tools]
        endpoint = f"{self._base_url}/api/chat"
        trace = LLMTraceRecorder(
            provider="ollama",
            model=self._model,
            base_url=self._base_url,
            endpoint=endpoint,
            stream=True,
        )
        trace.record_request(
            payload=payload,
            metadata={"timeout_seconds": cfg.timeout, "tools_count": len(tools or [])},
        )

        input_tokens = 0
        output_tokens = 0
        assistant_text_parts: list[str] = []
        # Ollama tool calls accumulate in the full response (not streamed per-chunk)
        pending_tool_calls: list[dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(
                timeout=cfg.timeout,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        body_text = body.decode("utf-8", errors="replace")
                        trace.record_error(
                            code=str(response.status_code),
                            message=f"HTTP {response.status_code}: {body_text}",
                            status_code=response.status_code,
                            response_body=body_text,
                        )
                        yield ErrorEvent(
                            message=f"HTTP {response.status_code}: {body_text}",
                            code=str(response.status_code),
                        )
                        return

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        trace.record_chunk(chunk)
                        msg_chunk = chunk.get("message", {})

                        # Text content
                        text = msg_chunk.get("content", "")
                        if text:
                            assistant_text_parts.append(text)
                            yield TextDeltaEvent(text=text)

                        # Ollama delivers tool_calls in a single chunk (non-streaming)
                        for tc in msg_chunk.get("tool_calls", []):
                            fn = tc.get("function", {})
                            pending_tool_calls.append(
                                {
                                    "id": tc.get("id", f"call_{len(pending_tool_calls)}"),
                                    "name": fn.get("name", ""),
                                    "arguments": fn.get("arguments", {}),
                                }
                            )

                        # Final chunk carries usage stats
                        if chunk.get("done"):
                            input_tokens = chunk.get("prompt_eval_count", 0)
                            output_tokens = chunk.get("eval_count", 0)

                    # Emit tool events after streaming completes
                    tools_acc = ToolStreamAccumulator()
                    for key, call in enumerate(pending_tool_calls):
                        for tool_event in tools_acc.start(
                            key,
                            tool_use_id=call["id"],
                            tool_name=call["name"],
                        ):
                            yield tool_event
                        for tool_event in tools_acc.append(key, json.dumps(call["arguments"])):
                            yield tool_event
                        # Ollama already delivers parsed arguments — they are
                        # authoritative, not reassembled from fragments.
                        for tool_event in tools_acc.finish_with_arguments(
                            key,
                            call["arguments"],
                        ):
                            yield tool_event

                    trace.record_response(
                        usage={
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        },
                        stop_reason="stop",
                        actual_model=self._model,
                        assistant_text="".join(assistant_text_parts),
                        tool_calls=[
                            {
                                "id": call["id"],
                                "name": call["name"],
                                "arguments": call["arguments"],
                                "arguments_json_valid": True,
                            }
                            for call in pending_tool_calls
                        ],
                    )
                    yield DoneEvent(
                        stop_reason="stop",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )

        except httpx.TimeoutException as exc:
            trace.record_error(code="timeout", message=f"Request timed out: {exc}")
            yield ErrorEvent(message=f"Request timed out: {exc}", code="timeout")
        except httpx.RequestError as exc:
            trace.record_error(code="request_error", message=f"Request error: {exc}")
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")
        except Exception as exc:  # noqa: BLE001 - chat() contract: ErrorEvent instead of raising
            log.exception(
                "provider.stream_internal_error",
                provider=self.provider_name,
                model=self._model,
            )
            trace.record_error(
                code="provider_internal",
                message=f"Provider response handling failed: {exc}",
            )
            yield ErrorEvent(
                message=f"Provider response handling failed: {exc}",
                code="provider_internal",
            )

    async def list_models(self, *, raise_on_error: bool = False) -> list[ModelInfo]:
        """List available models.

        By default any auth/transport failure degrades to an empty list (the
        historical contract every runtime caller relies on). Pass
        ``raise_on_error=True`` to surface the underlying exception instead,
        so callers that must distinguish an unreachable/secured host from an
        empty catalog (e.g. onboarding discovery) can classify it.
        """
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                resp = await client.get(
                    f"{self._base_url}/api/tags",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    ModelInfo(
                        provider=self.provider_name,
                        model_id=m["name"],
                        display_name=m.get("name", ""),
                        context_window=m.get("details", {}).get("context_length", 0),
                    )
                    for m in data.get("models", [])
                ]
        except Exception:
            if raise_on_error:
                raise
            return []
