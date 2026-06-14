"""LLMProvider Protocol and provider-plugin extension contract."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .types import ChatConfig, Message, ModelInfo, QuotaStatus, StreamEvent, ToolDefinition

if TYPE_CHECKING:
    from .selector import ProviderConfig, SelectorConfig


@dataclass(frozen=True)
class ProviderMetadata:
    """Read-only non-secret identity metadata exposed by provider implementations."""

    provider_name: str = ""
    provider_kind: str = ""
    model: str = ""
    base_url: str = ""


@dataclass(frozen=True)
class ProviderConnectionConfig:
    """Provider connection fields for internal runtime calls."""

    provider_kind: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    base_url: str = ""


@runtime_checkable
class ProviderMetadataProvider(Protocol):
    def provider_metadata(self) -> ProviderMetadata:
        """Return read-only provider metadata without exposing secrets."""
        ...


@runtime_checkable
class ProviderConnectionConfigProvider(Protocol):
    def provider_connection_config(self) -> ProviderConnectionConfig:
        """Return internal connection fields for provider-owned runtime calls."""
        ...


def _string_value(value: object) -> str:
    if value is None:
        return ""
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        value = get_secret_value()
    return str(value).strip()


def provider_metadata(provider: object | None) -> ProviderMetadata:
    """Return provider identity metadata, preferring the public protocol."""
    if provider is None:
        return ProviderMetadata()
    metadata_fn = getattr(provider, "provider_metadata", None)
    if callable(metadata_fn):
        metadata = metadata_fn()
        if isinstance(metadata, ProviderMetadata):
            return metadata

    provider_name = _string_value(getattr(provider, "provider_name", ""))
    provider_kind = _string_value(getattr(provider, "provider_kind", ""))
    model = _string_value(getattr(provider, "model", ""))
    base_url = _string_value(getattr(provider, "base_url", ""))

    # Metadata-provider migration path: new code should expose provider_metadata().
    provider_kind = provider_kind or _string_value(getattr(provider, "_provider_kind", ""))
    model = model or _string_value(getattr(provider, "_model", ""))
    base_url = base_url or _string_value(getattr(provider, "_base_url", ""))
    return ProviderMetadata(
        provider_name=provider_name,
        provider_kind=provider_kind,
        model=model,
        base_url=base_url,
    )


def provider_connection_config(provider: object | None) -> ProviderConnectionConfig:
    """Return internal provider connection fields without broadening metadata."""
    if provider is None:
        return ProviderConnectionConfig()
    config_fn = getattr(provider, "provider_connection_config", None)
    if callable(config_fn):
        config = config_fn()
        if isinstance(config, ProviderConnectionConfig):
            return config

    metadata = provider_metadata(provider)
    api_key = _string_value(getattr(provider, "api_key", ""))
    api_key = api_key or _string_value(getattr(provider, "_api_key", ""))
    return ProviderConnectionConfig(
        provider_kind=metadata.provider_kind,
        model=metadata.model,
        api_key=api_key,
        base_url=metadata.base_url,
    )


@runtime_checkable
class LLMProvider(Protocol):
    """Unified async streaming interface for any LLM backend.

    Implementors must provide:
    - chat(): streams events for a conversation turn
    - list_models(): returns available models for this provider
    - provider_name: str identifier (e.g. "anthropic", "openai", "ollama")
    """

    provider_name: str

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a conversation turn.

        Yields StreamEvent instances in order:
        - TextDeltaEvent for text chunks
        - ToolUseStartEvent / ToolUseDeltaEvent / ToolUseEndEvent for tool calls
        - DoneEvent when the turn completes
        - ErrorEvent on failure (instead of raising)
        """
        ...

    async def list_models(self) -> list[ModelInfo]:
        """Return all models available from this provider."""
        ...


class ProviderFailure(Exception):  # noqa: N818 - public compatibility name
    """Raised / wrapped when a primary provider turn fails.

    The selector passes instances of this exception (or any ``Exception``
    subclass) to ``failover_hook`` so plugin authors can inspect the
    underlying cause and decide which fallback chain to return.
    """


@runtime_checkable
class ProviderPlugin(Protocol):
    """Extension contract for provider-adjacent plugins.

    Plugins may implement any subset of these hooks. Selector/runtime callers
    consult them directly or through the helpers below, which return the
    documented defaults when no hook is registered.
    """

    def failover_hook(self, primary_failure: Exception) -> list[ProviderConfig]:
        """Return the ordered fallback chain for a primary failure.

        The returned list excludes the primary. An empty list signals
        "no fallback available" and forces the caller to surface the
        original failure to the user.
        """
        ...

    def quota_hook(self, session_id: str) -> QuotaStatus:
        """Return the remaining quota for ``session_id``.

        Unlimited / not-enforced is signaled via the default
        ``QuotaStatus`` (sentinel ``-1`` on both counters, ``None`` abort
        reason). A non-None ``abort_reason`` is surfaced verbatim in the
        user-facing graceful-abort payload.
        """
        ...


def resolve_failover_chain(
    primary_failure: Exception,
    config: SelectorConfig,
    plugin: ProviderPlugin | None = None,
) -> list[ProviderConfig]:
    """Return the fallback chain honoring a plugin ``failover_hook`` if set.

    Default (no plugin, or plugin raising) returns the static
    ``config.fallbacks`` chain declared on ``SelectorConfig``.
    """
    if plugin is not None and hasattr(plugin, "failover_hook"):
        try:
            chain = plugin.failover_hook(primary_failure)
        except Exception:
            chain = None
        if chain is not None:
            return list(chain)
    return list(config.fallbacks)


def resolve_quota_status(
    session_id: str,
    plugin: ProviderPlugin | None = None,
) -> QuotaStatus:
    """Return the quota status honoring a plugin ``quota_hook`` if set.

    Default (no plugin, or plugin raising) returns an unlimited sentinel
    ``QuotaStatus`` with ``abort_reason=None``.
    """
    if plugin is not None and hasattr(plugin, "quota_hook"):
        try:
            status = plugin.quota_hook(session_id)
        except Exception:
            return QuotaStatus()
        if status is not None:
            return status
    return QuotaStatus()
