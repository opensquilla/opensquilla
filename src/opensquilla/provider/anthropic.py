"""AnthropicProvider — streams via Anthropic Messages API using httpx."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env
from opensquilla.execution_status import derive_is_error

from .failures import retry_after_from_headers
from .model_catalog import shared_catalog
from .registry import AuthHeaderStyle
from .request_proof import (
    ProviderRequestBudgetExceededError,
    prove_provider_payload_from_env,
)
from .stream_assembly import ReasoningAccumulator, ToolStreamAccumulator
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
    ToolUseEndEvent,
)

log = structlog.get_logger(__name__)

_ANTHROPIC_API_BASE = "https://api.anthropic.com"
_ANTHROPIC_VERSION = "2023-06-01"


# The SKUs this adapter advertises from list_models. The LISTING SET is
# adapter knowledge — which models the provider surface offers — while the
# per-model metadata (windows, display names, pricing) resolves through the
# shared layered catalog, whose packaged corrections rows
# (catalog_overrides.toml) are the canonical source for these ids.
_LISTING_MODEL_IDS: tuple[str, ...] = (
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
)


def _build_tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema.model_dump(exclude_none=True),
    }


def _supports_document_blocks(model: str) -> bool:
    """Return True if the SKU supports Anthropic's native ``document`` block.

    Claude 3.5 Sonnet+ and the Claude 4.x Sonnet/Opus families support
    documents. Haiku — including Haiku 4.5 — does not. Older Claude 3 SKUs are
    likewise excluded; we keep the gate conservative so a regression here
    surfaces as a graceful skip rather than a 400 from the API.
    """
    m = model.lower()
    if "haiku" in m:
        return False
    return True


def _increment_document_block_rejected(code: str) -> None:
    """Hook called when Anthropic returns a non-200 for a request that carried
    a document block. The default is a no-op; observability backends and
    tests monkeypatch this.
    """
    return None


def _increment_document_block_unsupported() -> None:
    """Hook called when the adapter substitutes a fallback text block because
    the active model does not support ``document`` blocks. Default no-op.
    """
    return None


def _document_unsupported_fallback_text(title: str | None) -> str:
    label = title or "untitled document"
    return f"[document attached but not consumable by this model] ({label})"


def _has_document_block(messages: list[Message]) -> bool:
    for msg in messages:
        if isinstance(msg.content, str):
            continue
        for block in msg.content:
            if getattr(block, "type", None) == "document":
                return True
    return False


def _build_message_payload(
    msg: Message,
    model: str | None = None,
    *,
    replay_provider_state: bool = True,
) -> dict[str, Any]:
    if isinstance(msg.content, str):
        return {"role": msg.role, "content": msg.content}
    parts: list[dict[str, Any]] = []
    tool_result_parts: list[dict[str, Any]] = []
    for block in msg.content:
        if block.type == "text":
            parts.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            parts.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
        elif block.type == "image":
            if block.source_type == "url":
                parts.append({"type": "image", "source": {"type": "url", "url": block.data}})
            else:
                parts.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": block.media_type,
                            "data": block.data,
                        },
                    }
                )
        elif block.type == "document":
            if model is not None and not _supports_document_blocks(model):
                parts.append(
                    {
                        "type": "text",
                        "text": _document_unsupported_fallback_text(block.title),
                    }
                )
                _increment_document_block_unsupported()
                continue
            doc_block: dict[str, Any] = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": block.media_type,
                    "data": block.data,
                },
            }
            if block.title is not None:
                doc_block["title"] = block.title
            parts.append(doc_block)
        elif block.type == "thinking":
            if not replay_provider_state:
                # Cross-provider execution: signatures are validated against
                # the exact minting turn; a foreign signature is a hard 400.
                # Unsigned thinking replay is likewise rejected with tools,
                # so the whole block is dropped rather than degraded.
                continue
            thinking_block: dict[str, Any] = {
                "type": "thinking",
                "thinking": block.thinking,
            }
            if block.signature:
                thinking_block["signature"] = block.signature
            parts.append(thinking_block)
        elif block.type == "compaction":
            compaction_block: dict[str, Any] = {"type": "compaction"}
            if block.content is not None:
                compaction_block["content"] = block.content
            if block.cache_control:
                compaction_block["cache_control"] = block.cache_control
            parts.append(compaction_block)
        elif block.type == "tool_result":
            is_error = (
                derive_is_error(block.execution_status)
                if block.execution_status is not None
                else block.is_error
            )
            tool_result_parts.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                    "is_error": is_error,
                }
            )
    if tool_result_parts:
        parts = tool_result_parts + parts
    return {"role": msg.role, "content": parts}


def _build_system_payload(cfg: ChatConfig) -> str | list[dict[str, Any]] | None:
    if not cfg.system:
        return None
    if not cfg.cache_breakpoints:
        return cfg.system

    blocks: list[dict[str, Any]] = []
    for bp in cfg.cache_breakpoints:
        text = bp.get("text", "")
        if not text:
            continue
        block: dict[str, Any] = {"type": "text", "text": text}
        if bp.get("cache"):
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks or cfg.system


def _uses_adaptive_thinking(model: str) -> bool:
    model_lower = model.lower()
    return "claude-sonnet-4-6" in model_lower or "claude-opus-4-6" in model_lower


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cache_creation_input_tokens(usage: dict[str, Any]) -> int:
    direct = _coerce_int(usage.get("cache_creation_input_tokens"))
    if direct:
        return direct

    creation = usage.get("cache_creation")
    if not isinstance(creation, dict):
        return 0
    return sum(_coerce_int(value) for value in creation.values())


def _anthropic_input_token_counts(usage: dict[str, Any]) -> tuple[int, int, int]:
    base_input_tokens = _coerce_int(usage.get("input_tokens"))
    cache_read_tokens = _coerce_int(usage.get("cache_read_input_tokens"))
    cache_creation_tokens = _cache_creation_input_tokens(usage)
    total_input_tokens = base_input_tokens + cache_read_tokens + cache_creation_tokens
    return total_input_tokens, cache_read_tokens, cache_creation_tokens


def _anthropic_iteration_token_counts(usage: dict[str, Any]) -> tuple[int, int]:
    iterations = usage.get("iterations")
    if not isinstance(iterations, list):
        return _coerce_int(usage.get("input_tokens")), _coerce_int(usage.get("output_tokens"))

    input_tokens = 0
    output_tokens = 0
    for iteration in iterations:
        if not isinstance(iteration, dict):
            continue
        input_tokens += _coerce_int(iteration.get("input_tokens"))
        output_tokens += _coerce_int(iteration.get("output_tokens"))
    return input_tokens, output_tokens


class AnthropicProvider:
    """Streams from Anthropic Messages API with SSE parsing."""

    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        base_url: str = _ANTHROPIC_API_BASE,
        proxy: str | None = None,
        replay_provider_state: bool = True,
        auth_header_style: AuthHeaderStyle = "x-api-key",
    ) -> None:
        # The default auth style matches Anthropic proper so direct
        # construction (tests, embedding) against the default host behaves
        # unchanged; registry-built providers receive the spec's style
        # (MiniMax's Anthropic-compatible endpoints need a Bearer header).
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._proxy = proxy or None
        self._replay_provider_state = replay_provider_state
        self._auth_header_style = auth_header_style

    @property
    def model(self) -> str:
        """Model id this provider was configured with.

        Public so callers (e.g. derived-cache key construction) can identify
        the underlying model without prying at private state.
        """
        return self._model

    def _api_url(self, path: str) -> str:
        """Build an API URL without duplicating the version prefix."""
        if self._base_url.endswith("/v1") and path.startswith("/v1/"):
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
        max_tokens = max(1, cfg.max_tokens)
        thinking_payload: dict[str, Any] | None = None
        if cfg.thinking:
            if _uses_adaptive_thinking(self._model):
                thinking_payload = {"type": "adaptive"}
            else:
                budget_tokens = max(1, cfg.thinking_budget_tokens)
                if budget_tokens >= max_tokens:
                    max_tokens = budget_tokens + 4096
                thinking_payload = {
                    "type": "enabled",
                    "budget_tokens": budget_tokens,
                }

        built_messages = [
            _build_message_payload(
                m,
                model=self._model,
                replay_provider_state=self._replay_provider_state,
            )
            for m in messages
        ]
        request_has_document = any(
            isinstance(m.get("content"), list)
            and any(isinstance(p, dict) and p.get("type") == "document" for p in m["content"])
            for m in built_messages
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": built_messages,
            "stream": True,
        }
        system_payload = _build_system_payload(cfg)
        if system_payload:
            payload["system"] = system_payload
        if cfg.temperature is not None and not cfg.thinking:
            payload["temperature"] = cfg.temperature
        if cfg.stop_sequences:
            payload["stop_sequences"] = cfg.stop_sequences
        if tools:
            payload["tools"] = [_build_tool_payload(t) for t in tools]
        if thinking_payload:
            payload["thinking"] = thinking_payload

        from opensquilla.engine.context_budget import coordinate_provider_context_budget

        budget_decision = coordinate_provider_context_budget(
            payload,
            projection_adapter="anthropic",
            proof_budget=cfg.provider_request_max_chars,
            status_projection_mode="native_is_error",
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
                projection_adapter="anthropic",
                status_projection_mode="native_is_error",
            )
        except ProviderRequestBudgetExceededError as exc:
            log.warning("provider.request_budget_exhausted", **exc.proof)
            yield ErrorEvent(
                message=json.dumps(exc.proof, ensure_ascii=False, sort_keys=True),
                code="provider_request_budget_exhausted",
            )
            return

        headers = {
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        if self._auth_header_style == "bearer":
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            headers["x-api-key"] = self._api_key
        endpoint = self._api_url("/v1/messages")
        trace = LLMTraceRecorder(
            provider="anthropic",
            model=self._model,
            base_url=self._base_url,
            endpoint=endpoint,
            stream=True,
        )
        trace.record_request(
            payload=payload,
            headers=headers,
            metadata={
                "timeout_seconds": cfg.timeout,
                "tools_count": len(tools or []),
                "request_has_document": request_has_document,
                "request_proof": budget_decision.proof,
            },
        )

        # Tool calls keyed by Anthropic's global content-block index.
        tools_acc = ToolStreamAccumulator()
        text_parts: list[str] = []
        trace_tool_calls: list[dict[str, Any]] = []
        response_ids: set[str] = set()

        def _trace_tool_call(end_event: ToolUseEndEvent, raw: str) -> None:
            # The trace mirrors the emitted ToolUseEndEvent; the raw fragment
            # text is kept alongside so a trace reader can distinguish
            # repaired arguments from wire-valid JSON.
            try:
                if raw:
                    json.loads(raw)
                arguments_valid = True
            except json.JSONDecodeError:
                arguments_valid = False
            trace_tool_calls.append(
                {
                    "id": end_event.tool_use_id,
                    "name": end_event.tool_name,
                    "arguments_raw": raw,
                    "arguments_json_valid": arguments_valid,
                    "arguments": end_event.arguments,
                }
            )

        base_input_tokens = 0
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        cache_creation_tokens = 0
        reasoning = ReasoningAccumulator()
        thinking_signature: str | None = None
        stop_reason = "end_turn"

        try:
            async with httpx.AsyncClient(
                timeout=cfg.timeout,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        body_text = body.decode("utf-8", errors="replace")
                        if request_has_document:
                            _increment_document_block_rejected(str(response.status_code))
                        trace.record_error(
                            code=str(response.status_code),
                            message=f"HTTP {response.status_code}: {body_text}",
                            status_code=response.status_code,
                            response_body=body_text,
                        )
                        yield ErrorEvent(
                            message=(
                                f"HTTP {response.status_code}: " f"{body_text}"
                            ),
                            code=str(response.status_code),
                            retry_after_s=retry_after_from_headers(
                                response.status_code,
                                getattr(response, "headers", None),
                            ),
                        )
                        return

                    async for line in response.aiter_lines():
                        # SSE spec: a single optional space after the colon
                        # is part of the field syntax. Some gateways emit
                        # "data:{...}" without the space — accept both.
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:]
                        if data_str.startswith(" "):
                            data_str = data_str[1:]
                        if data_str == "[DONE]":
                            break
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        trace.record_chunk(event)
                        etype = event.get("type", "")

                        if etype == "message_start":
                            message_id = event.get("message", {}).get("id")
                            if isinstance(message_id, str) and message_id:
                                response_ids.add(message_id)
                            usage = event.get("message", {}).get("usage", {})
                            base_input_tokens = _coerce_int(usage.get("input_tokens"))
                            (
                                input_tokens,
                                cached_tokens,
                                cache_creation_tokens,
                            ) = _anthropic_input_token_counts(usage)

                        elif etype == "content_block_start":
                            index = event.get("index", -1)
                            block = event.get("content_block", {})
                            btype = block.get("type")
                            if btype == "tool_use":
                                for tool_event in tools_acc.start(
                                    index,
                                    tool_use_id=block["id"],
                                    tool_name=block["name"],
                                ):
                                    yield tool_event

                        elif etype == "content_block_delta":
                            delta = event.get("delta", {})
                            dtype = delta.get("type")
                            if dtype == "text_delta":
                                text = delta.get("text", "")
                                text_parts.append(text)
                                yield TextDeltaEvent(text=text)
                            elif dtype == "input_json_delta":
                                index = event.get("index", 0)
                                fragment = delta.get("partial_json", "")
                                tool_events = tools_acc.append(index, fragment)
                                if not tool_events:
                                    # Not a tool block at this index (e.g. a
                                    # server-tool result) — never a tool call.
                                    log.debug("anthropic.unknown_delta_index", index=index)
                                for tool_event in tool_events:
                                    yield tool_event
                            elif dtype == "thinking_delta":
                                reasoning_event = reasoning.emit(delta.get("thinking", ""))
                                if reasoning_event is not None:
                                    yield reasoning_event
                            elif dtype == "signature_delta":
                                thinking_signature = delta.get("signature") or thinking_signature

                        elif etype == "content_block_stop":
                            index = event.get("index", -1)
                            raw = next(
                                (
                                    text
                                    for key, _tid, _name, text in (
                                        tools_acc.pending_raw_arguments()
                                    )
                                    if key == index
                                ),
                                "",
                            )
                            for tool_event in tools_acc.finish(index):
                                if isinstance(tool_event, ToolUseEndEvent):
                                    _trace_tool_call(tool_event, raw)
                                yield tool_event

                        elif etype == "message_delta":
                            usage = event.get("usage", {})
                            (
                                iteration_input_tokens,
                                iteration_output_tokens,
                            ) = _anthropic_iteration_token_counts(usage)
                            output_tokens = iteration_output_tokens
                            cached_tokens = max(
                                cached_tokens,
                                usage.get("cache_read_input_tokens", 0),
                            )
                            cache_creation_tokens = max(
                                cache_creation_tokens,
                                _cache_creation_input_tokens(usage),
                            )
                            if "input_tokens" in usage:
                                base_input_tokens = _coerce_int(usage.get("input_tokens"))
                            if isinstance(usage.get("iterations"), list):
                                input_tokens = iteration_input_tokens
                            else:
                                input_tokens = (
                                    base_input_tokens + cached_tokens + cache_creation_tokens
                                )
                            stop_reason = event.get("delta", {}).get("stop_reason", "end_turn")

                        elif etype == "message_stop":
                            break

                    # Termination contract: a stream that ends without
                    # message_stop (upstream close, gateway drop) must still
                    # close open tool calls and yield DoneEvent — the
                    # generator never falls off the end silently.
                    pending_raw = {
                        tool_use_id: text
                        for _key, tool_use_id, _name, text in tools_acc.pending_raw_arguments()
                    }
                    for tool_event in tools_acc.finish_all():
                        if isinstance(tool_event, ToolUseEndEvent):
                            _trace_tool_call(
                                tool_event,
                                pending_raw.get(tool_event.tool_use_id, ""),
                            )
                        yield tool_event
                    reasoning_content = reasoning.finalize()
                    trace.record_response(
                        usage={
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "reasoning_tokens": 0,
                            "cached_tokens": cached_tokens,
                            "cache_write_tokens": cache_creation_tokens,
                        },
                        stop_reason=stop_reason,
                        actual_model=self._model,
                        assistant_text="".join(text_parts),
                        reasoning_content=reasoning_content,
                        tool_calls=trace_tool_calls,
                        response_ids=sorted(response_ids),
                    )
                    yield DoneEvent(
                        stop_reason=stop_reason,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_content=reasoning_content,
                        thinking_signature=thinking_signature,
                        cached_tokens=cached_tokens,
                        cache_write_tokens=cache_creation_tokens,
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

    async def list_models(self) -> list[ModelInfo]:
        """Build listing rows for the adapter's SKUs from the shared catalog.

        The catalog's canonical costs are USD per million tokens; the
        ``ModelInfo`` wire contract carries per-1k floats (rpc_models
        renders per-1k), so entry costs are converted back (÷1000).
        Capability flags stay at ``ModelInfo`` defaults — the listing has
        only ever advertised identity, windows, and pricing.
        """
        rows: list[ModelInfo] = []
        for model_id in _LISTING_MODEL_IDS:
            entry = shared_catalog().resolve_entry(model_id, provider=self.provider_name)
            rows.append(
                ModelInfo(
                    provider=self.provider_name,
                    model_id=model_id,
                    display_name=entry.display_name or model_id,
                    context_window=entry.context_window,
                    max_output_tokens=entry.max_output_tokens,
                    input_cost_per_1k=(entry.input_cost_per_mtok or 0.0) / 1000.0,
                    output_cost_per_1k=(entry.output_cost_per_mtok or 0.0) / 1000.0,
                )
            )
        return rows
