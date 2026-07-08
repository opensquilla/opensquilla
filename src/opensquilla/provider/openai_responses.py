"""OpenAI Responses API provider path.

This provider intentionally stays separate from the OpenAI-compatible Chat
Completions provider because Responses uses item-shaped input/output and native
state protocols that should evolve independently.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx

from opensquilla.env import trust_env as _trust_env
from opensquilla.secrets import clean_header_secret

from .failures import retry_after_from_headers
from .openai import _VERSIONED_BASE_URL_RE, _http_error_body_text, _resolve_llm_proxy
from .protocol import ProviderConnectionConfig, ProviderMetadata
from .stream_assembly import ToolStreamAccumulator
from .trace_recorder import LLMTraceRecorder
from .types import (
    ChatConfig,
    ContentBlockText,
    ContentBlockToolResult,
    ContentBlockToolUse,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelInfo,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolUseEndEvent,
)

_OPENAI_RESPONSES_BASE = "https://api.openai.com/v1"


def _responses_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": {
            "type": tool.input_schema.type,
            "properties": tool.input_schema.properties,
            "required": tool.input_schema.required,
        },
    }


def _responses_tool_output(content: str | list[Any]) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _responses_message_item(role: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "message", "role": role, "content": content}


def _responses_input(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message.content, str):
            items.append({"role": message.role, "content": message.content})
            continue

        pending_content: list[dict[str, Any]] = []

        def flush_pending_message() -> None:
            if pending_content:
                items.append(_responses_message_item(message.role, list(pending_content)))
                pending_content.clear()

        for block in message.content:
            if isinstance(block, ContentBlockText):
                content_type = "output_text" if message.role == "assistant" else "input_text"
                pending_content.append({"type": content_type, "text": block.text})
            elif isinstance(block, ContentBlockToolUse):
                flush_pending_message()
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block.id,
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    }
                )
            elif isinstance(block, ContentBlockToolResult):
                flush_pending_message()
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block.tool_use_id,
                        "output": _responses_tool_output(block.content),
                    }
                )
        flush_pending_message()
    return items


def _usage_fields(usage: Any) -> tuple[int, int, int, int]:
    if not isinstance(usage, dict):
        return 0, 0, 0, 0
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    input_details = usage.get("input_tokens_details")
    cached_tokens = (
        int(input_details.get("cached_tokens") or 0) if isinstance(input_details, dict) else 0
    )
    output_details = usage.get("output_tokens_details")
    reasoning_tokens = (
        int(output_details.get("reasoning_tokens") or 0) if isinstance(output_details, dict) else 0
    )
    return input_tokens, output_tokens, reasoning_tokens, cached_tokens


class OpenAIResponsesProvider:
    """OpenAI native Responses API provider.

    The initial implementation supports text and function-call event mapping
    with stateless requests (`store: false`). Provider-native compaction/item
    replay is added in later continuity work.
    """

    provider_name = "openai_responses"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4",
        base_url: str = _OPENAI_RESPONSES_BASE,
        org_id: str | None = None,
        proxy: str | None = None,
    ) -> None:
        self._api_key = clean_header_secret(api_key, label="LLM API key")
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._org_id = org_id
        self._proxy = _resolve_llm_proxy(proxy)

    @property
    def model(self) -> str:
        return self._model

    def provider_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_name=self.provider_name,
            provider_kind="openai_responses",
            model=self._model,
            base_url=self._base_url,
        )

    def provider_connection_config(self) -> ProviderConnectionConfig:
        return ProviderConnectionConfig(
            provider_kind="openai_responses",
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
        )

    def _api_url(self, path: str) -> str:
        if path.startswith("/v1/") and _VERSIONED_BASE_URL_RE.search(self._base_url):
            return f"{self._base_url}{path[3:]}"
        return f"{self._base_url}{path}"

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self.chat_items(
            _responses_input(messages),
            tools=tools,
            config=config or ChatConfig(),
        )

    def chat_items(
        self,
        input_items: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a Responses request from canonical Responses input items."""

        return self._complete_items(input_items, tools=tools, config=config or ChatConfig())

    async def _complete_items(
        self,
        input_items: list[dict[str, Any]],
        *,
        tools: list[ToolDefinition] | None,
        config: ChatConfig,
    ) -> AsyncIterator[StreamEvent]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._org_id:
            headers["OpenAI-Organization"] = self._org_id

        payload: dict[str, Any] = {
            "model": self._model,
            "input": input_items,
            "max_output_tokens": config.max_tokens,
            "store": False,
        }
        if config.system:
            payload["instructions"] = config.system
        if config.temperature is not None:
            payload["temperature"] = config.temperature
        if config.stop_sequences:
            payload["stop"] = config.stop_sequences
        if tools:
            payload["tools"] = [_responses_tool(tool) for tool in tools]
            payload["tool_choice"] = config.tool_choice or "auto"
        endpoint = self._api_url("/v1/responses")
        trace = LLMTraceRecorder(
            provider="openai_responses",
            model=self._model,
            base_url=self._base_url,
            endpoint=endpoint,
            stream=False,
        )
        trace.record_request(
            payload=payload,
            headers=headers,
            metadata={"timeout_seconds": config.timeout, "tools_count": len(tools or [])},
        )

        try:
            async with httpx.AsyncClient(
                timeout=config.timeout,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            trace.record_error(code="timeout", message=f"Request timed out: {exc}")
            yield ErrorEvent(message=f"Request timed out: {exc}", code="timeout")
            return
        except httpx.RequestError as exc:
            trace.record_error(code="request_error", message=f"Request error: {exc}")
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")
            return

        if response.status_code != 200:
            detail = _http_error_body_text(response.text)
            message = f"OpenAI Responses API error {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            trace.record_error(
                code=str(response.status_code),
                message=message,
                status_code=response.status_code,
                response_body=response.text,
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

        try:
            data = response.json()
        except json.JSONDecodeError:
            trace.record_error(
                code="invalid_json",
                message="Invalid JSON response from OpenAI Responses API",
                response_body=response.text,
            )
            yield ErrorEvent(
                message="Invalid JSON response from OpenAI Responses API",
                code="invalid_json",
            )
            return

        emitted_tool = False
        tools_acc = ToolStreamAccumulator()
        assistant_text_parts: list[str] = []
        trace_tool_calls: list[dict[str, Any]] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            assistant_text_parts.append(text)
                            yield TextDeltaEvent(text=text)
            elif item.get("type") == "function_call":
                emitted_tool = True
                call_id = item.get("call_id") or item.get("id") or f"call_{uuid4().hex[:12]}"
                # Responses output items are keyed by their item id, the
                # stream-local key the streaming variant of this API uses.
                key = item.get("id") or call_id
                for tool_event in tools_acc.start(
                    key,
                    tool_use_id=call_id,
                    tool_name=item.get("name") or "",
                ):
                    yield tool_event
                arguments_text = item.get("arguments") or ""
                if arguments_text:
                    for tool_event in tools_acc.append(key, arguments_text):
                        yield tool_event
                for tool_event in tools_acc.finish(key):
                    yield tool_event
                    if isinstance(tool_event, ToolUseEndEvent):
                        try:
                            if arguments_text:
                                json.loads(arguments_text)
                            arguments_valid = True
                        except json.JSONDecodeError:
                            arguments_valid = False
                        trace_tool_calls.append(
                            {
                                "id": tool_event.tool_use_id,
                                "name": tool_event.tool_name,
                                "arguments_raw": arguments_text,
                                "arguments_json_valid": arguments_valid,
                                "arguments": tool_event.arguments,
                            }
                        )

        input_tokens, output_tokens, reasoning_tokens, cached_tokens = _usage_fields(
            data.get("usage")
        )
        actual_model = data.get("model") or self._model
        trace.record_response(
            response=data,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "cached_tokens": cached_tokens,
            },
            stop_reason="tool_use" if emitted_tool else "end_turn",
            actual_model=actual_model,
            assistant_text="".join(assistant_text_parts),
            tool_calls=trace_tool_calls,
            response_ids=[str(data["id"])] if data.get("id") else [],
        )
        yield DoneEvent(
            stop_reason="tool_use" if emitted_tool else "end_turn",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
            model=actual_model,
        )

    async def list_models(self, *, raise_on_error: bool = False) -> list[ModelInfo]:
        """List available models.

        By default any auth/transport failure degrades to an empty list (the
        historical contract every runtime caller relies on). Pass
        ``raise_on_error=True`` to surface the underlying exception instead,
        so callers that must distinguish a wrong key from an empty catalog
        (e.g. onboarding discovery) can classify it.
        """
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(
                timeout=30,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                response = await client.get(self._api_url("/v1/models"), headers=headers)
        except httpx.HTTPError:
            if raise_on_error:
                raise
            return []

        if response.status_code != 200:
            if raise_on_error:
                # 4xx/5xx raise a classifiable HTTPStatusError; an unexpected
                # non-200 success shape still degrades to the empty list.
                response.raise_for_status()
            return []
        try:
            data = response.json()
        except json.JSONDecodeError:
            if raise_on_error:
                raise
            return []

        models: list[ModelInfo] = []
        for raw in data.get("data", []):
            model_id = raw.get("id") if isinstance(raw, dict) else None
            if isinstance(model_id, str):
                models.append(
                    ModelInfo(
                        provider=self.provider_name,
                        model_id=model_id,
                        display_name=raw.get("name") or model_id,
                    )
                )
        return models

    async def compact_window(
        self,
        input_items: list[dict[str, Any]],
        *,
        config: ChatConfig | None = None,
    ) -> dict[str, Any]:
        """Call `/responses/compact` and return the raw compact response.

        The returned `output` is an opaque canonical context window. Callers
        must store and later replay it without pruning or inspecting internals.
        """

        cfg = config or ChatConfig()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._org_id:
            headers["OpenAI-Organization"] = self._org_id
        endpoint = self._api_url("/v1/responses/compact")
        payload = {"model": self._model, "input": input_items}
        trace = LLMTraceRecorder(
            provider="openai_responses",
            model=self._model,
            base_url=self._base_url,
            endpoint=endpoint,
            stream=False,
        )
        trace.record_request(
            payload=payload,
            headers=headers,
            metadata={"timeout_seconds": cfg.timeout, "operation": "compact_window"},
        )

        async with httpx.AsyncClient(
            timeout=cfg.timeout,
            trust_env=_trust_env(),
            proxy=self._proxy,
        ) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json=payload,
            )

        if response.status_code != 200:
            detail = _http_error_body_text(response.text)
            message = f"OpenAI Responses compact API error {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            trace.record_error(
                code=str(response.status_code),
                message=message,
                status_code=response.status_code,
                response_body=response.text,
                metadata={"operation": "compact_window"},
            )
            raise RuntimeError(message)

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            trace.record_error(
                code="invalid_json",
                message="Invalid JSON response from OpenAI Responses compact API",
                response_body=response.text,
                metadata={"operation": "compact_window"},
            )
            raise RuntimeError("Invalid JSON response from OpenAI Responses compact API") from exc
        if not isinstance(data, dict):
            trace.record_error(
                code="invalid_shape",
                message="Invalid response shape from OpenAI Responses compact API",
                metadata={"operation": "compact_window"},
            )
            raise RuntimeError("Invalid response shape from OpenAI Responses compact API")
        trace.record_response(
            response=data,
            actual_model=data.get("model") or self._model,
            response_ids=[str(data["id"])] if data.get("id") else [],
            metadata={"operation": "compact_window"},
        )
        return data
