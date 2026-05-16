"""opensquilla.provider — unified LLM provider abstraction layer."""

from .anthropic import AnthropicProvider
from .credentials import Credential, CredentialPool, NoCredentialsAvailable
from .factory import ProviderFactory, ProviderFactoryPort, build_provider_from_config
from .failures import (
    ProviderFailureKind,
    ProviderRecoveryAction,
    classify_provider_error,
    decide_recovery_action,
)
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .protocol import (
    LLMProvider,
    ProviderFailure,
    ProviderMetadata,
    ProviderMetadataProvider,
    ProviderPlugin,
    provider_metadata,
    resolve_failover_chain,
    resolve_quota_status,
)
from .registry import (
    ProviderSpec,
    ProviderSupportLevel,
    UnknownProviderError,
    get_provider_spec,
    list_provider_names,
    list_provider_specs,
)
from .selector import (
    ModelSelector,
    ProviderBuildError,
    ProviderConfig,
    SelectorConfig,
    build_provider,
)
from .smart_routing import RefusalDecision, should_refuse
from .thinking import THINKING_BUDGETS, ThinkingLevel
from .types import (
    ChatConfig,
    ContentBlockDocument,
    ContentBlockText,
    ContentBlockThinking,
    ContentBlockToolResult,
    ContentBlockToolUse,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelCapabilities,
    ModelInfo,
    ProviderHeartbeatEvent,
    QuotaStatus,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolInputSchema,
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)

__all__ = [
    # Protocol
    "LLMProvider",
    "ProviderPlugin",
    "ProviderFailure",
    "ProviderMetadata",
    "ProviderMetadataProvider",
    "provider_metadata",
    "ProviderFailureKind",
    "resolve_failover_chain",
    "resolve_quota_status",
    "ProviderRecoveryAction",
    "classify_provider_error",
    "decide_recovery_action",
    # Providers
    "AnthropicProvider",
    "OpenAIProvider",
    "OllamaProvider",
    # Registry
    "ProviderSpec",
    "ProviderSupportLevel",
    "UnknownProviderError",
    "get_provider_spec",
    "list_provider_names",
    "list_provider_specs",
    # Selector
    "ModelSelector",
    "SelectorConfig",
    "ProviderConfig",
    "ProviderBuildError",
    "build_provider",
    "ProviderFactory",
    "ProviderFactoryPort",
    "build_provider_from_config",
    # Credentials
    "Credential",
    "CredentialPool",
    "NoCredentialsAvailable",
    # Smart routing
    "RefusalDecision",
    "should_refuse",
    "ThinkingLevel",
    "THINKING_BUDGETS",
    # Types
    "StreamEvent",
    "TextDeltaEvent",
    "ToolUseStartEvent",
    "ToolUseDeltaEvent",
    "ToolUseEndEvent",
    "DoneEvent",
    "ErrorEvent",
    "ProviderHeartbeatEvent",
    "ModelCapabilities",
    "ModelInfo",
    "ChatConfig",
    "Message",
    "QuotaStatus",
    "ToolDefinition",
    "ToolInputSchema",
    "ContentBlockText",
    "ContentBlockThinking",
    "ContentBlockToolUse",
    "ContentBlockToolResult",
    "ContentBlockDocument",
]
