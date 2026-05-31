"""Provider type definitions: stream events, model info, config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from opensquilla.execution_status import ExecutionStatus

# ---------------------------------------------------------------------------
# Stream event dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TextDeltaEvent:
    """A chunk of assistant text."""

    kind: Literal["text_delta"] = field(default="text_delta", init=False)
    text: str = ""


@dataclass
class ToolUseStartEvent:
    """LLM begins a tool call."""

    kind: Literal["tool_use_start"] = field(default="tool_use_start", init=False)
    tool_use_id: str = ""
    tool_name: str = ""
    synthetic_from_text: bool = False


@dataclass
class ToolUseDeltaEvent:
    """Streaming fragment of tool call arguments (JSON)."""

    kind: Literal["tool_use_delta"] = field(default="tool_use_delta", init=False)
    tool_use_id: str = ""
    json_fragment: str = ""


@dataclass
class ToolUseEndEvent:
    """Tool call argument stream complete."""

    kind: Literal["tool_use_end"] = field(default="tool_use_end", init=False)
    tool_use_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    synthetic_from_text: bool = False


@dataclass
class DoneEvent:
    """Stream finished successfully."""

    kind: Literal["done"] = field(default="done", init=False)
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_content: str | None = None
    thinking_signature: str | None = None
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    billed_cost: float = 0.0
    model: str = ""
    # New fields appended at the end so positional construction in callers and
    # tests does not silently shift earlier args.
    cache_write_tokens: int = 0
    cost_source: str = "none"

    @property
    def upstream_cost_usd(self) -> float:
        """Backward-compatible alias for earlier OpenRouter cost consumers."""
        return self.billed_cost


@dataclass
class ErrorEvent:
    """Stream error."""

    kind: Literal["error"] = field(default="error", init=False)
    message: str = ""
    code: str = ""


@dataclass
class ProviderHeartbeatEvent:
    """Provider-side liveness signal while no user-visible tokens are ready."""

    kind: Literal["provider_heartbeat"] = field(default="provider_heartbeat", init=False)
    phase: str = "provider"
    message: str = ""


@dataclass
class QuotaStatus:
    """Quota snapshot returned by ``quota_hook``.

    ``-1`` on either counter is the sentinel for "unlimited / not enforced";
    ``abort_reason`` is user-facing and surfaces verbatim in the graceful
    abort payload when the caller chooses to short-circuit the turn.
    """

    tokens_remaining: int = -1
    tool_calls_remaining: int = -1
    abort_reason: str | None = None


@dataclass(frozen=True)
class ModelCapabilities:
    """Per-model capability flags resolved from ModelCatalog."""

    supports_reasoning: bool = False
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    reasoning_format: str = "none"
    # "none" | "openrouter" | "deepseek" | "think_tags"


StreamEvent = (
    TextDeltaEvent
    | ToolUseStartEvent
    | ToolUseDeltaEvent
    | ToolUseEndEvent
    | DoneEvent
    | ErrorEvent
    | ProviderHeartbeatEvent
)


# ---------------------------------------------------------------------------
# Tool definition (Pydantic BaseModel — external API boundary)
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class ToolParam(BaseModel):
    """Single parameter in a tool schema."""

    type: str
    description: str = ""
    enum: list[str] | None = None


class ToolInputSchema(BaseModel):
    """JSON schema for tool inputs."""

    type: Literal["object"] = "object"
    properties: dict[str, Any] = {}
    required: list[str] = []


class ToolDefinition(BaseModel):
    """Tool definition passed to the LLM."""

    name: str
    description: str
    input_schema: ToolInputSchema
    execution_timeout_seconds: float | None = None
    execution_timeout_argument: str | None = None
    execution_timeout_padding: float = 0.0


# ---------------------------------------------------------------------------
# Model info (Pydantic BaseModel — registry / API responses)
# ---------------------------------------------------------------------------


class ModelInfo(BaseModel):
    """Metadata about an available model."""

    provider: str
    model_id: str
    display_name: str = ""
    context_window: int = 0
    max_output_tokens: int = 0
    supports_reasoning: bool = False
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0


# ---------------------------------------------------------------------------
# Chat config (Pydantic BaseModel — call-time settings)
# ---------------------------------------------------------------------------


class ChatConfig(BaseModel):
    """Runtime options for a single chat call."""

    max_tokens: int = 16384
    temperature: float | None = None
    system: str | None = None
    stop_sequences: list[str] = []
    thinking: bool = False
    thinking_budget_tokens: int = 5000
    timeout: float = 120.0
    # Prompt caching: when set, system prompt is split into cached/dynamic blocks
    cache_breakpoints: list[dict[str, str]] | None = None
    cache_mode: Literal["off", "auto", "on"] = "off"
    model_capabilities: ModelCapabilities | None = None
    thinking_level: Any | None = None
    provider_request_max_chars: int = 0
    tool_choice: Any | None = None


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------


class ContentBlockText(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ContentBlockToolUse(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class ContentBlockToolResult(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[Any]
    is_error: bool = False
    execution_status: ExecutionStatus | None = None


class ContentBlockImage(BaseModel):
    type: Literal["image"] = "image"
    source_type: Literal["base64", "url"] = "base64"
    media_type: str  # "image/png", "image/jpeg", etc.
    data: str  # base64 data or URL


class ContentBlockDocument(BaseModel):
    type: Literal["document"] = "document"
    source_type: Literal["base64"] = "base64"
    media_type: Literal["application/pdf"]
    data: str
    title: str | None = None


class ContentBlockThinking(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    signature: str | None = None


class ContentBlockCompaction(BaseModel):
    type: Literal["compaction"] = "compaction"
    content: str | None = None
    cache_control: dict[str, Any] | None = None


MessageContent = (
    str
    | list[
        ContentBlockText
        | ContentBlockToolUse
        | ContentBlockToolResult
        | ContentBlockImage
        | ContentBlockDocument
        | ContentBlockThinking
        | ContentBlockCompaction
    ]
)


class Message(BaseModel):
    """A single conversation message."""

    role: Literal["user", "assistant"]
    content: MessageContent
    reasoning_content: str | None = None
