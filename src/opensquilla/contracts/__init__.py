"""Stable ports and DTOs for the architecture refactor.

This package is the inward-facing contract layer. It must remain lightweight:
no gateway, engine, provider, tool, channel, memory, session, sandbox, or MCP
implementation imports belong here.
"""

from __future__ import annotations

from .approval import ApprovalDecision, ApprovalPort, ApprovalRequest, ApprovalStatus
from .attachments import (
    ALLOWED_MEDIA_TYPES,
    IMAGE_ATTACHMENT_BYTES,
    IMAGE_ATTACHMENT_MIMES,
    INLINE_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_STAGED_PDF_BYTES,
    MAX_TOTAL_ATTACHMENT_BYTES,
    PDF_MAGIC,
    SNIFF_PEEK_BYTES,
    TEXT_ATTACHMENT_BYTES,
    TEXT_ATTACHMENT_MIMES,
    attachment_size_limit_for_mime,
    can_stage_attachment_mime,
    normalize_attachment_mime,
)
from .channel import (
    Attachment,
    ChannelHealth,
    ChannelIngressPort,
    ChannelPort,
    IncomingMessage,
    OutgoingMessage,
)
from .errors import CapabilityUnavailableError, ContractError, ContractPermissionError
from .events import (
    EventPublisherPort,
    EventSink,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    TurnEvent,
    TurnFailed,
    TurnFinished,
)
from .memory import MemoryPort, MemoryQuery, MemoryResult
from .provider import (
    ProviderChatOptions,
    ProviderFactoryPort,
    ProviderMessage,
    ProviderModelInfo,
    ProviderPort,
    ProviderToolDefinition,
)
from .sandbox import SandboxPort, SandboxRequest, SandboxResult
from .session import SessionRecord, SessionStatus, SessionStorePort, TranscriptEntry
from .task import TaskEnvelope, TaskHandle, TaskRuntimePort, TaskStatus
from .tool import (
    CallerKind,
    InteractionMode,
    ToolCall,
    ToolContext,
    ToolHandler,
    ToolPolicyPort,
    ToolRegistryPort,
    ToolResult,
    ToolSpec,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalPort",
    "ApprovalRequest",
    "ApprovalStatus",
    "ALLOWED_MEDIA_TYPES",
    "Attachment",
    "CallerKind",
    "CapabilityUnavailableError",
    "ChannelHealth",
    "ChannelIngressPort",
    "ChannelPort",
    "ContractError",
    "ContractPermissionError",
    "EventPublisherPort",
    "EventSink",
    "IMAGE_ATTACHMENT_BYTES",
    "IMAGE_ATTACHMENT_MIMES",
    "INLINE_ATTACHMENT_BYTES",
    "IncomingMessage",
    "InteractionMode",
    "MAX_ATTACHMENT_BYTES",
    "MAX_ATTACHMENTS",
    "MAX_STAGED_PDF_BYTES",
    "MAX_TOTAL_ATTACHMENT_BYTES",
    "MemoryPort",
    "MemoryQuery",
    "MemoryResult",
    "OutgoingMessage",
    "PDF_MAGIC",
    "ProviderChatOptions",
    "ProviderFactoryPort",
    "ProviderMessage",
    "ProviderModelInfo",
    "ProviderPort",
    "ProviderToolDefinition",
    "SandboxPort",
    "SandboxRequest",
    "SandboxResult",
    "SessionRecord",
    "SessionStatus",
    "SNIFF_PEEK_BYTES",
    "SessionStorePort",
    "TaskEnvelope",
    "TaskHandle",
    "TaskRuntimePort",
    "TaskStatus",
    "TEXT_ATTACHMENT_BYTES",
    "TEXT_ATTACHMENT_MIMES",
    "TextDelta",
    "ToolCall",
    "ToolCallFinished",
    "ToolCallStarted",
    "ToolContext",
    "ToolHandler",
    "ToolPolicyPort",
    "ToolRegistryPort",
    "ToolResult",
    "ToolSpec",
    "TranscriptEntry",
    "TurnEvent",
    "TurnFailed",
    "TurnFinished",
    "attachment_size_limit_for_mime",
    "can_stage_attachment_mime",
    "normalize_attachment_mime",
]
