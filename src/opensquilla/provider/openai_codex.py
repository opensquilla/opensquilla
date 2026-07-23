"""OpenAI Codex (ChatGPT-account OAuth) provider.

Speaks the ``chatgpt.com/backend-api/codex/responses`` protocol — an OpenAI
Responses-flavored SSE endpoint authenticated with the operator's ChatGPT
subscription (Bearer access token + ``chatgpt-account-id`` header) instead
of a platform API key. Credentials come from the Codex CLI's auth file via
``codex_auth``; a 401 triggers one token refresh + retry.

Wire facts mirror the reference implementation in codex-rs: flat function
tools (``{type, name, description, strict, parameters}``), Responses input
items, ``store: false`` + ``include: ["reasoning.encrypted_content"]``, and
``response.*`` SSE events.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env

from .codex_auth import (
    CodexAuthError,
    CodexCredentials,
    load_codex_credentials,
    refresh_codex_credentials,
)
from .error_redaction import redact_upstream_error_code, redact_upstream_error_text
from .openai import _http_error_body_text, _resolve_llm_proxy
from .openai_responses import _responses_input
from .protocol import ProviderConnectionConfig, ProviderMetadata
from .stream_assembly import (
    ReasoningAccumulator,
    ToolStreamAccumulator,
    ToolStreamProtocolError,
)
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

_CODEX_BACKEND_BASE = "https://chatgpt.com/backend-api"
# Matches the current Codex CLI default; older -codex suffixed slugs are
# rejected for ChatGPT-account requests on current backends.
_DEFAULT_CODEX_MODEL = "gpt-5.5"
# The stored tokens were minted for the Codex CLI application; requests carry
# its originator so the backend sees the client the credentials belong to.
_CODEX_ORIGINATOR = "codex_cli_rs"

_KNOWN_CODEX_MODELS: tuple[tuple[str, str], ...] = (
    ("gpt-5.5", "GPT-5.5"),
    ("gpt-5.4-mini", "GPT-5.4 Mini"),
    ("gpt-5", "GPT-5"),
)


def _is_finite_json_object(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        json.dumps(value, allow_nan=False)
    except (OverflowError, RecursionError, TypeError, ValueError):
        return False
    return True


def _codex_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "strict": False,
        "parameters": {
            "type": tool.input_schema.type,
            "properties": tool.input_schema.properties,
            "required": tool.input_schema.required,
        },
    }


def _reasoning_effort(cfg: ChatConfig) -> str:
    level = getattr(cfg.thinking_level, "value", None) or str(cfg.thinking_level or "")
    normalized = level.strip().lower()
    if normalized in {"minimal", "low"}:
        return "low"
    if normalized in {"high", "xhigh"}:
        return "high"
    return "medium"


class OpenAICodexProvider:
    """Streams from the ChatGPT backend-api Responses endpoint via OAuth."""

    provider_name = "openai_codex"

    def __init__(
        self,
        model: str = _DEFAULT_CODEX_MODEL,
        base_url: str = _CODEX_BACKEND_BASE,
        proxy: str | None = None,
        auth_path: str | None = None,
        api_key: str = "",  # accepted for constructor parity; OAuth ignores it
        provider_id: str | None = None,
    ) -> None:
        self._model = model
        self._base_url = self._normalize_base_url(base_url)
        self._proxy = _resolve_llm_proxy(proxy)
        self._auth_path = Path(auth_path).expanduser() if auth_path else None
        self.provider_id = (provider_id or self.provider_name).strip()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        base = (base_url or _CODEX_BACKEND_BASE).rstrip("/")
        host_only = base.lower()
        if (
            ("chatgpt.com" in host_only or "chat.openai.com" in host_only)
            and "/backend-api" not in host_only
        ):
            base = f"{base}/backend-api"
        return base

    @property
    def model(self) -> str:
        return self._model

    def provider_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_name=self.provider_name,
            provider_kind="openai_codex",
            model=self._model,
            base_url=self._base_url,
            provider_id=self.provider_id,
        )

    def provider_connection_config(self) -> ProviderConnectionConfig:
        # OAuth tokens are deliberately not exposed through this surface.
        return ProviderConnectionConfig(
            provider_kind="openai_codex",
            model=self._model,
            api_key="",
            base_url=self._base_url,
        )

    def _responses_url(self) -> str:
        return f"{self._base_url}/codex/responses"

    def _headers(self, credentials: CodexCredentials) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "originator": _CODEX_ORIGINATOR,
            "User-Agent": _CODEX_ORIGINATOR,
        }
        if credentials.account_id:
            headers["chatgpt-account-id"] = credentials.account_id
        return headers

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        cfg: ChatConfig,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "instructions": cfg.system or "",
            "input": _responses_input(messages),
            "tool_choice": cfg.tool_choice or "auto",
            "parallel_tool_calls": True,
            "store": False,
            "stream": True,
            "include": ["reasoning.encrypted_content"],
        }
        # The ChatGPT codex backend rejects max_output_tokens outright
        # ("Unsupported parameter", verified live 2026-07-02), matching
        # codex-rs which never sends it — subscription turns have no
        # client-set output cap. Surface the dropped budget for operators
        # instead of silently ignoring it.
        if cfg.max_tokens > 0:
            log.debug(
                "openai_codex.max_tokens_unsupported",
                requested_max_tokens=cfg.max_tokens,
                model=self._model,
            )
        if tools:
            payload["tools"] = [_codex_tool(tool) for tool in tools]
        if cfg.thinking:
            payload["reasoning"] = {"effort": _reasoning_effort(cfg), "summary": "auto"}
        return payload

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self._stream(messages, tools, config or ChatConfig())

    async def _stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        cfg: ChatConfig,
    ) -> AsyncIterator[StreamEvent]:
        try:
            credentials = load_codex_credentials(self._auth_path)
        except CodexAuthError as exc:
            yield ErrorEvent(message=str(exc), code="401")
            return

        payload = self._build_payload(messages, tools, cfg)

        try:
            async with httpx.AsyncClient(
                timeout=cfg.timeout,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                refreshed = False
                while True:
                    async with client.stream(
                        "POST",
                        self._responses_url(),
                        headers=self._headers(credentials),
                        json=payload,
                    ) as response:
                        if response.status_code == 401 and not refreshed:
                            refreshed = True
                            try:
                                credentials = await refresh_codex_credentials(
                                    credentials,
                                    path=self._auth_path,
                                    proxy=self._proxy,
                                )
                            except CodexAuthError as exc:
                                yield ErrorEvent(message=str(exc), code="401")
                                return
                            continue
                        if response.status_code != 200:
                            body = await response.aread()
                            yield ErrorEvent(
                                message=redact_upstream_error_text(
                                    "ChatGPT Codex request failed "
                                    f"(HTTP {response.status_code}): "
                                    f"{_http_error_body_text(body)}",
                                    api_key=credentials.access_token,
                                    max_len=2000,
                                ),
                                code=str(response.status_code),
                            )
                            return

                        async for event in self._parse_sse(
                            response,
                            cfg,
                            access_token=credentials.access_token,
                        ):
                            yield event
                        return
        except httpx.TimeoutException as exc:
            yield ErrorEvent(
                message=redact_upstream_error_text(
                    f"Request timed out: {exc}",
                    api_key=credentials.access_token,
                    max_len=2000,
                ),
                code="timeout",
            )
        except httpx.RequestError as exc:
            yield ErrorEvent(
                message=redact_upstream_error_text(
                    f"Request error: {exc}",
                    api_key=credentials.access_token,
                    max_len=2000,
                ),
                code="request_error",
            )
        except Exception as exc:  # noqa: BLE001 - chat() contract: ErrorEvent instead of raising
            log.exception(
                "provider.stream_internal_error",
                provider=self.provider_name,
                model=self._model,
            )
            yield ErrorEvent(
                message=redact_upstream_error_text(
                    f"Provider response handling failed: {exc}",
                    api_key=credentials.access_token,
                    max_len=2000,
                ),
                code="provider_internal",
            )

    async def _parse_sse(
        self,
        response: httpx.Response,
        cfg: ChatConfig,
        *,
        access_token: str = "",
    ) -> AsyncIterator[StreamEvent]:
        tools_acc = ToolStreamAccumulator()
        reasoning = ReasoningAccumulator()
        actual_model = self._model
        input_tokens = 0
        output_tokens = 0
        reasoning_tokens = 0
        cached_tokens = 0
        stop_reason: str | None = None
        response_completed = False
        deferred_tool_ends: list[StreamEvent] = []
        invalid_tool_call_keys: set[Any] = set()

        def _function_call_identity(item: Any) -> tuple[str, str] | None:
            if not isinstance(item, dict):
                return None
            raw_item_id = item.get("id")
            raw_call_id = item.get("call_id")
            if (
                raw_item_id is not None
                and (
                    not isinstance(raw_item_id, str)
                    or not raw_item_id.strip()
                )
            ) or (
                raw_call_id is not None
                and (
                    not isinstance(raw_call_id, str)
                    or not raw_call_id.strip()
                )
            ):
                return None
            public_id = raw_call_id or raw_item_id
            key = raw_item_id or raw_call_id
            if not isinstance(public_id, str) or not isinstance(key, str):
                return None
            return key, public_id

        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                yield ErrorEvent(
                    message="ChatGPT Codex stream contained an invalid data frame",
                    code="invalid_stream_frame",
                )
                return
            if not isinstance(event, dict):
                yield ErrorEvent(
                    message="ChatGPT Codex stream contained a non-object data frame",
                    code="invalid_stream_frame",
                )
                return
            etype = str(event.get("type") or "")

            if etype == "error":
                # Upstream error frames may echo request headers or account
                # identifiers; this adapter authenticates with an OAuth access
                # token, so route the text through the same redaction boundary
                # as the other adapters before it reaches transcripts and logs.
                error = event.get("error")
                message = (
                    str(error.get("message") or "ChatGPT Codex stream error")
                    if isinstance(error, dict)
                    else str(error or event.get("message") or "ChatGPT Codex stream error")
                )
                code = (
                    str(error.get("code") or error.get("type") or "stream_error")
                    if isinstance(error, dict)
                    else str(event.get("code") or "stream_error")
                )
                yield ErrorEvent(
                    message=redact_upstream_error_text(
                        message,
                        api_key=access_token,
                        max_len=2000,
                    ),
                    code=redact_upstream_error_code(code, api_key=access_token),
                )
                return

            if etype == "response.output_text.delta":
                delta = str(event.get("delta") or "")
                if delta:
                    yield TextDeltaEvent(text=delta)

            elif etype in (
                "response.reasoning_summary_text.delta",
                "response.reasoning_text.delta",
            ):
                reasoning_event = reasoning.emit(str(event.get("delta") or ""))
                if reasoning_event is not None:
                    yield reasoning_event

            elif etype == "response.output_item.added":
                item = event.get("item") or {}
                if isinstance(item, dict) and item.get("type") == "function_call":
                    identity = _function_call_identity(item)
                    raw_tool_name = item.get("name")
                    tool_name = raw_tool_name if isinstance(raw_tool_name, str) else ""
                    if identity is None:
                        invalid_tool_call_keys.add(f"invalid-{len(invalid_tool_call_keys)}")
                        continue
                    key, tool_use_id = identity
                    try:
                        tool_events = tools_acc.start(
                            key,
                            tool_use_id=tool_use_id,
                            tool_name=tool_name,
                        )
                    except ToolStreamProtocolError as exc:
                        invalid_tool_call_keys.add(exc.key)
                        log.warning(
                            "provider.tool_stream_protocol_error",
                            provider=self.provider_name,
                            model=self._model,
                            operation=exc.operation,
                            reason=exc.reason,
                        )
                        continue
                    for tool_event in tool_events:
                        yield tool_event

            elif etype == "response.function_call_arguments.delta":
                delta_key = event.get("item_id")
                fragment = str(event.get("delta") or "")
                if fragment:
                    try:
                        tool_events = tools_acc.append(delta_key, fragment)
                    except ToolStreamProtocolError as exc:
                        invalid_tool_call_keys.add(exc.key)
                        log.warning(
                            "provider.tool_stream_protocol_error",
                            provider=self.provider_name,
                            model=self._model,
                            operation=exc.operation,
                            reason=exc.reason,
                        )
                        continue
                    for tool_event in tool_events:
                        yield tool_event

            elif etype == "response.output_item.done":
                item = event.get("item") or {}
                if isinstance(item, dict) and item.get("type") == "function_call":
                    identity = _function_call_identity(item)
                    raw_tool_name = item.get("name")
                    tool_name = raw_tool_name if isinstance(raw_tool_name, str) else ""
                    if identity is None or not tool_name.strip():
                        invalid_tool_call_keys.add(f"invalid-{len(invalid_tool_call_keys)}")
                        continue
                    key, tool_use_id = identity
                    try:
                        tool_events = tools_acc.start(
                            key,
                            tool_use_id=tool_use_id,
                            tool_name=tool_name,
                        )
                    except ToolStreamProtocolError as exc:
                        invalid_tool_call_keys.add(exc.key)
                        log.warning(
                            "provider.tool_stream_protocol_error",
                            provider=self.provider_name,
                            model=self._model,
                            operation=exc.operation,
                            reason=exc.reason,
                        )
                        continue
                    for tool_event in tool_events:
                        yield tool_event
                    # The done item carries the authoritative full arguments.
                    raw_arguments_value = item.get("arguments")
                    if not isinstance(raw_arguments_value, str):
                        invalid_tool_call_keys.add(key)
                        continue
                    raw_arguments = raw_arguments_value
                    try:
                        arguments = (
                            json.loads(
                                raw_arguments,
                                parse_constant=lambda value: (_ for _ in ()).throw(
                                    ValueError(value)
                                ),
                            )
                            if raw_arguments.strip()
                            else {}
                        )
                        arguments_valid = _is_finite_json_object(arguments)
                    except (
                        json.JSONDecodeError,
                        RecursionError,
                        TypeError,
                        ValueError,
                    ):
                        arguments = {}
                        arguments_valid = False
                    identity_valid = bool(tool_name.strip())
                    if arguments_valid and identity_valid:
                        try:
                            deferred_tool_ends.extend(
                                tools_acc.finish_with_arguments(key, arguments)
                            )
                        except ToolStreamProtocolError as exc:
                            invalid_tool_call_keys.add(exc.key)
                            log.warning(
                                "provider.tool_stream_protocol_error",
                                provider=self.provider_name,
                                model=self._model,
                                operation=exc.operation,
                                reason=exc.reason,
                            )
                    else:
                        invalid_tool_call_keys.add(key)

            elif etype == "response.completed":
                body = event.get("response")
                if not isinstance(body, dict):
                    yield ErrorEvent(
                        message="ChatGPT Codex completed event was malformed",
                        code="invalid_response",
                    )
                    return
                completed_status = body.get("status")
                if completed_status is not None and completed_status != "completed":
                    yield ErrorEvent(
                        message=(
                            "ChatGPT Codex completed event carried non-completed "
                            f"status {completed_status!r}"
                        ),
                        code="invalid_response_status",
                    )
                    return
                actual_model = str(body.get("model") or self._model)
                usage = body.get("usage") or {}
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)
                input_details = usage.get("input_tokens_details") or {}
                cached_tokens = int(input_details.get("cached_tokens") or 0)
                output_details = usage.get("output_tokens_details") or {}
                reasoning_tokens = int(output_details.get("reasoning_tokens") or 0)
                stop_reason = "end_turn"
                response_completed = True
                break

            elif etype == "response.failed":
                body = event.get("response") or {}
                error = body.get("error") or {}
                yield ErrorEvent(
                    message=redact_upstream_error_text(
                        str(error.get("message") or "ChatGPT Codex response failed"),
                        api_key=access_token,
                        max_len=2000,
                    ),
                    code=redact_upstream_error_code(
                        str(error.get("code") or "response_failed"),
                        api_key=access_token,
                    ),
                )
                return

            elif etype in {"response.incomplete", "response.cancelled"}:
                body = event.get("response") or {}
                details = body.get("incomplete_details") or {}
                message = (
                    str(details.get("reason") or f"ChatGPT Codex {etype}")
                    if isinstance(details, dict)
                    else f"ChatGPT Codex {etype}"
                )
                yield ErrorEvent(
                    message=redact_upstream_error_text(
                        message,
                        api_key=access_token,
                        max_len=2000,
                    ),
                    code=etype.replace("response.", "response_"),
                )
                return

        if not response_completed:
            yield ErrorEvent(
                message="ChatGPT Codex stream ended before response.completed",
                code="incomplete_stream",
            )
            return

        if tools_acc.pending_raw_arguments() or invalid_tool_call_keys:
            yield ErrorEvent(
                message="ChatGPT Codex response ended with an incomplete tool call",
                code="incomplete_tool_call",
            )
            return

        # ``output_item.done`` confirms an item but does not commit the
        # response.  Release tool ends only after ``response.completed`` so a
        # later failure or transport drop cannot expose executable partials.
        for tool_event in deferred_tool_ends:
            yield tool_event
        emitted_tool = tools_acc.has_calls
        yield DoneEvent(
            stop_reason="tool_use" if emitted_tool else (stop_reason or "end_turn"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_content=reasoning.finalize(),
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
            model=actual_model,
            provider=self.provider_id,
        )

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                provider=self.provider_name,
                model_id=model_id,
                display_name=display_name,
                context_window=272_000,
                max_output_tokens=128_000,
            )
            for model_id, display_name in _KNOWN_CODEX_MODELS
        ]
