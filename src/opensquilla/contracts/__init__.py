"""Stable ports and DTOs for the architecture refactor.

This package is the inward-facing contract layer. It must remain lightweight:
no gateway, engine, provider, tool, channel, memory, session, sandbox, or MCP
implementation imports belong here.
"""

from __future__ import annotations

from .approval import ApprovalDecision, ApprovalPort, ApprovalRequest, ApprovalStatus
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
    "IncomingMessage",
    "InteractionMode",
    "MemoryPort",
    "MemoryQuery",
    "MemoryResult",
    "OutgoingMessage",
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
    "SessionStorePort",
    "TaskEnvelope",
    "TaskHandle",
    "TaskRuntimePort",
    "TaskStatus",
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
]
