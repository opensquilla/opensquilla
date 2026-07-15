"""Shared channel-plugin contract assertions.

Every shipped adapter's ``tests/test_channels/test_<name>_contract.py``
imports ``run_channel_contract`` and hands it the adapter module so the
shared invariants — capability tier, DM safety posture, error-class
taxonomy — are verified the same way for every channel.

The contract surface is intentionally narrow: only invariants that ALL
DM/group adapters honor live here. Per-adapter routing-key shapes,
mention parsing, and webhook-specific tests stay in the adapter's own
contract test file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import ModuleType
from typing import Any

# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

PUBLIC_VENDOR_ADAPTERS: tuple[str, ...] = (
    "slack",
    "discord",
    "feishu",
    "dingtalk",
    "wecom",
    "qq",
    "matrix",
    "telegram",
)

#: Capability tier values declared by adapters via ``CAPABILITY_TIER``.
ALLOWED_CAPABILITY_TIERS: frozenset[str] = frozenset(
    {
        "GREEN-shipping",
        "YELLOW-experimental",
        "RED-blocked",
    }
)

#: ``DM_SAFETY_TIERS`` values that are valid for DM/group adapters.
ALLOWED_DM_SAFETY_TIERS: frozenset[str] = frozenset({"safe", "confirm"})

#: Canonical retryable-error taxonomy. Every adapter declares this verbatim.
REQUIRED_RETRYABLE_ERROR_CLASSES: tuple[str, ...] = (
    "transport_transient",
    "rate_limited",
    "channel_degraded",
)

#: Canonical fatal-error taxonomy.
REQUIRED_FATAL_ERROR_CLASSES: tuple[str, ...] = (
    "auth_invalid",
    "payload_rejected",
    "target_missing",
    "contract_violation",
)


class ChannelCapabilities:
    """Capability tags an adapter may declare on its module.

    Tests can branch on these to skip irrelevant assertions (e.g. an adapter
    without webhook surface skips signature-verification checks).
    """

    STREAMING = "streaming"
    GROUP_CHAT = "group_chat"
    MENTIONS = "mentions"
    TYPING_INDICATOR = "typing_indicator"
    WEBHOOK = "webhook"
    WEBSOCKET = "websocket"
    ARTIFACT_DELIVERY = "artifact_delivery"
    NATIVE_FILE_UPLOAD = "native_file_upload"
    MEDIA = "media"
    REACTIONS = "reactions"
    INBOUND_REACTIONS = "inbound_reactions"
    OUTBOUND_STATUS_REACTIONS = "outbound_status_reactions"
    THREADS = "threads"
    THREAD_MESSAGES = "thread_messages"
    THREAD_LIFECYCLE = "thread_lifecycle"
    REPLY = "reply"
    THREAD_REPLY = "thread_reply"
    EDIT = "edit"
    DELETE = "delete"
    CARDS = "cards"
    INTERACTIVE_CARDS = "interactive_cards"
    CARD_ACTIONS = "card_actions"
    MEMBER_EVENTS = "member_events"
    GROUP_DM = "group_dm"
    DOCUMENT_IMPORT = "document_import"
    SCOPE_DIAGNOSTICS = "scope_diagnostics"


class ChannelSendStatus(StrEnum):
    """Structured outbound delivery status for channel operations."""

    SENT = "sent"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ChannelSendResult:
    """Normalized result for optional channel delivery operations."""

    status: ChannelSendStatus
    capability: str
    target_id: str = ""
    provider_message_id: str = ""
    provider_file_id: str = ""
    retryable: bool = False
    reason: str = ""

    @classmethod
    def sent(
        cls,
        *,
        capability: str,
        target_id: str = "",
        provider_message_id: str = "",
        provider_file_id: str = "",
    ) -> ChannelSendResult:
        return cls(
            status=ChannelSendStatus.SENT,
            capability=capability,
            target_id=target_id,
            provider_message_id=provider_message_id,
            provider_file_id=provider_file_id,
        )

    @classmethod
    def unsupported(
        cls,
        *,
        capability: str,
        target_id: str = "",
        reason: str = "",
    ) -> ChannelSendResult:
        return cls(
            status=ChannelSendStatus.UNSUPPORTED,
            capability=capability,
            target_id=target_id,
            reason=reason,
        )

    @classmethod
    def failed(
        cls,
        *,
        capability: str,
        target_id: str = "",
        reason: str = "",
        retryable: bool = False,
    ) -> ChannelSendResult:
        return cls(
            status=ChannelSendStatus.FAILED,
            capability=capability,
            target_id=target_id,
            reason=reason,
            retryable=retryable,
        )

    def is_delivered(self) -> bool:
        return self.status == ChannelSendStatus.SENT


@dataclass(frozen=True)
class ChannelCapabilityProfile:
    """Minimal typed capability declaration for channel adapters."""

    channel_type: str
    group_chat: bool = False
    mentions: bool = False
    typing_indicator: bool = False
    native_file_upload: bool = False
    media: bool = False
    reactions: bool = False
    inbound_reactions: bool = False
    outbound_status_reactions: bool = False
    threads: bool = False
    thread_messages: bool = False
    thread_lifecycle: bool = False
    reply: bool = False
    thread_reply: bool = False
    edit: bool = False
    delete: bool = False
    cards: bool = False
    interactive_cards: bool = False
    card_actions: bool = False
    member_events: bool = False
    group_dm: bool = False
    document_import: bool = False
    scope_diagnostics: bool = False
    artifact_delivery: bool = False
    transports: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def capability_tags(self) -> frozenset[str]:
        tags: set[str] = set()
        if self.group_chat:
            tags.add(ChannelCapabilities.GROUP_CHAT)
        if self.mentions:
            tags.add(ChannelCapabilities.MENTIONS)
        if self.typing_indicator:
            tags.add(ChannelCapabilities.TYPING_INDICATOR)
        if self.artifact_delivery or self.native_file_upload or self.media:
            tags.add(ChannelCapabilities.ARTIFACT_DELIVERY)
        if self.native_file_upload:
            tags.add(ChannelCapabilities.NATIVE_FILE_UPLOAD)
        if self.media:
            tags.add(ChannelCapabilities.MEDIA)
        if self.reactions:
            tags.add(ChannelCapabilities.REACTIONS)
        if self.inbound_reactions:
            tags.add(ChannelCapabilities.INBOUND_REACTIONS)
        if self.outbound_status_reactions:
            tags.add(ChannelCapabilities.OUTBOUND_STATUS_REACTIONS)
        if self.threads:
            tags.add(ChannelCapabilities.THREADS)
        if self.thread_messages:
            tags.add(ChannelCapabilities.THREAD_MESSAGES)
        if self.thread_lifecycle:
            tags.add(ChannelCapabilities.THREAD_LIFECYCLE)
        if self.reply:
            tags.add(ChannelCapabilities.REPLY)
        if self.thread_reply:
            tags.add(ChannelCapabilities.THREAD_REPLY)
        if self.edit:
            tags.add(ChannelCapabilities.EDIT)
        if self.delete:
            tags.add(ChannelCapabilities.DELETE)
        if self.cards:
            tags.add(ChannelCapabilities.CARDS)
        if self.interactive_cards:
            tags.add(ChannelCapabilities.INTERACTIVE_CARDS)
        if self.card_actions:
            tags.add(ChannelCapabilities.CARD_ACTIONS)
        if self.member_events:
            tags.add(ChannelCapabilities.MEMBER_EVENTS)
        if self.group_dm:
            tags.add(ChannelCapabilities.GROUP_DM)
        if self.document_import:
            tags.add(ChannelCapabilities.DOCUMENT_IMPORT)
        if self.scope_diagnostics:
            tags.add(ChannelCapabilities.SCOPE_DIAGNOSTICS)
        for transport in self.transports:
            normalized = transport.strip().lower().replace("-", "_")
            if normalized == "webhook":
                tags.add(ChannelCapabilities.WEBHOOK)
            elif normalized == "websocket":
                tags.add(ChannelCapabilities.WEBSOCKET)
            elif normalized == "streaming":
                tags.add(ChannelCapabilities.STREAMING)
        return frozenset(tags)

    def supports(self, capability: str) -> bool:
        return capability in self.capability_tags()


class ChannelPlatformCapabilityStatus(StrEnum):
    """Support state for a provider-level platform capability."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONFIG_REQUIRED = "config_required"


class ChannelPlatformCategories:
    """Provider-level capability categories used in support matrices."""

    CHAT = "chat"
    FILES = "files"
    MEDIA = "media"
    ATTACHMENTS = "attachments"
    THREADS = "threads"
    CARDS = "cards"
    DOCS = "docs"
    DRIVE = "drive"
    WIKI = "wiki"
    PERMISSIONS = "permissions"
    SCOPES = "scopes"


CHANNEL_PLATFORM_CATEGORIES: tuple[str, ...] = (
    ChannelPlatformCategories.CHAT,
    ChannelPlatformCategories.FILES,
    ChannelPlatformCategories.MEDIA,
    ChannelPlatformCategories.ATTACHMENTS,
    ChannelPlatformCategories.THREADS,
    ChannelPlatformCategories.CARDS,
    ChannelPlatformCategories.DOCS,
    ChannelPlatformCategories.DRIVE,
    ChannelPlatformCategories.WIKI,
    ChannelPlatformCategories.PERMISSIONS,
    ChannelPlatformCategories.SCOPES,
)


@dataclass(frozen=True)
class ChannelPlatformCapability:
    """One provider-level platform capability row.

    This is intentionally broader than low-level transport capabilities:
    channels can be honest about docs/drive/wiki/scope support without forcing
    every provider into Feishu's exact product model.
    """

    category: str
    status: ChannelPlatformCapabilityStatus
    tools: tuple[str, ...] = ()
    required_scopes: tuple[str, ...] = ()
    mutates: bool = False
    dry_run_supported: bool = False
    default_channel_visible: bool = False
    notes: tuple[str, ...] = ()

    def is_supported(self) -> bool:
        return self.status == ChannelPlatformCapabilityStatus.SUPPORTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "status": self.status.value,
            "tools": list(self.tools),
            "required_scopes": list(self.required_scopes),
            "mutates": self.mutates,
            "dry_run_supported": self.dry_run_supported,
            "default_channel_visible": self.default_channel_visible,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ChannelPlatformManifest:
    """Provider-level platform boundary for a channel adapter."""

    channel_type: str
    capabilities: tuple[ChannelPlatformCapability, ...]

    @classmethod
    def from_channel_profile(
        cls,
        profile: ChannelCapabilityProfile,
        *,
        has_send_file: bool = False,
        has_inbound_attachment_resolver: bool = False,
    ) -> ChannelPlatformManifest:
        def row(
            category: str,
            supported: bool,
            *,
            config_required: bool = False,
            notes: tuple[str, ...] = (),
        ) -> ChannelPlatformCapability:
            if supported:
                status = ChannelPlatformCapabilityStatus.SUPPORTED
            elif config_required:
                status = ChannelPlatformCapabilityStatus.CONFIG_REQUIRED
            else:
                status = ChannelPlatformCapabilityStatus.UNSUPPORTED
            return ChannelPlatformCapability(category=category, status=status, notes=notes)

        file_capable = profile.native_file_upload or profile.artifact_delivery or profile.media
        thread_capable = profile.threads or profile.thread_reply or profile.thread_messages
        card_capable = profile.cards or profile.interactive_cards or profile.card_actions
        chat_capable = bool(
            profile.group_chat
            or profile.reply
            or profile.edit
            or profile.delete
            or profile.transports
        )

        return cls(
            channel_type=profile.channel_type,
            capabilities=(
                row(ChannelPlatformCategories.CHAT, chat_capable),
                row(
                    ChannelPlatformCategories.FILES,
                    file_capable and has_send_file,
                    config_required=file_capable and not has_send_file,
                ),
                row(ChannelPlatformCategories.MEDIA, profile.media),
                row(
                    ChannelPlatformCategories.ATTACHMENTS,
                    has_inbound_attachment_resolver,
                ),
                row(ChannelPlatformCategories.THREADS, thread_capable),
                row(ChannelPlatformCategories.CARDS, card_capable),
                row(ChannelPlatformCategories.DOCS, profile.document_import),
                row(ChannelPlatformCategories.DRIVE, False),
                row(ChannelPlatformCategories.WIKI, False),
                row(ChannelPlatformCategories.PERMISSIONS, False),
                row(ChannelPlatformCategories.SCOPES, profile.scope_diagnostics),
            ),
        )

    def get(self, category: str) -> ChannelPlatformCapability:
        for capability in self.capabilities:
            if capability.category == category:
                return capability
        return ChannelPlatformCapability(
            category=category,
            status=ChannelPlatformCapabilityStatus.UNSUPPORTED,
        )

    def supports(self, category: str) -> bool:
        return self.get(category).is_supported()

    def with_capabilities(
        self,
        *overrides: ChannelPlatformCapability,
    ) -> ChannelPlatformManifest:
        """Return a copy with category rows replaced by provider-specific rows."""

        by_category = {capability.category: capability for capability in self.capabilities}
        for override in overrides:
            by_category[override.category] = override
        return ChannelPlatformManifest(
            channel_type=self.channel_type,
            capabilities=tuple(
                by_category.get(
                    category,
                    ChannelPlatformCapability(
                        category=category,
                        status=ChannelPlatformCapabilityStatus.UNSUPPORTED,
                    ),
                )
                for category in CHANNEL_PLATFORM_CATEGORIES
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_type": self.channel_type,
            "capabilities": {
                category: self.get(category).to_dict()
                for category in CHANNEL_PLATFORM_CATEGORIES
            },
        }


def channel_capability_profile(channel: Any) -> ChannelCapabilityProfile | None:
    """Return a channel's typed capability profile, if it exposes one."""

    raw = getattr(channel, "capability_profile", None)
    if callable(raw):
        raw = raw()
    if isinstance(raw, ChannelCapabilityProfile):
        return raw
    return None


def channel_platform_manifest(channel: Any) -> ChannelPlatformManifest | None:
    """Return or derive a channel's provider-level platform manifest."""

    raw = getattr(channel, "platform_capability_manifest", None)
    if callable(raw):
        raw = raw()
    if isinstance(raw, ChannelPlatformManifest):
        return raw
    profile = channel_capability_profile(channel)
    if profile is None:
        return None
    return ChannelPlatformManifest.from_channel_profile(
        profile,
        has_send_file=callable(getattr(channel, "send_file", None)),
        has_inbound_attachment_resolver=callable(
            getattr(channel, "resolve_inbound_attachment", None)
        ),
    )


def normalize_channel_send_result(
    result: Any,
    *,
    capability: str,
    target_id: str = "",
) -> ChannelSendResult:
    """Normalize legacy outbound return values to a structured result."""

    if isinstance(result, ChannelSendResult):
        return result
    if result is None:
        return ChannelSendResult.sent(capability=capability, target_id=target_id)
    if isinstance(result, dict):
        try:
            status = ChannelSendStatus(str(result.get("status", ChannelSendStatus.SENT.value)))
        except ValueError:
            status = ChannelSendStatus.FAILED
        return ChannelSendResult(
            status=status,
            capability=str(result.get("capability", capability)),
            target_id=str(result.get("target_id", target_id)),
            provider_message_id=str(result.get("provider_message_id", "")),
            provider_file_id=str(result.get("provider_file_id", "")),
            retryable=bool(result.get("retryable", False)),
            reason=str(result.get("reason", "")),
        )
    return ChannelSendResult.sent(capability=capability, target_id=target_id)


# ---------------------------------------------------------------------------
# Shared assertions
# ---------------------------------------------------------------------------


def assert_capability_tier(module: ModuleType) -> None:
    """``CAPABILITY_TIER`` must be one of the allowed values.

    Uses an explicit ``raise`` (not ``assert``) so shared contract
    validation remains active when Python runs with optimization enabled.
    """
    tier = getattr(module, "CAPABILITY_TIER", None)
    if tier not in ALLOWED_CAPABILITY_TIERS:
        raise ValueError(
            f"{module.__name__}.CAPABILITY_TIER={tier!r} must be one of "
            f"{sorted(ALLOWED_CAPABILITY_TIERS)}"
        )


def assert_dm_safety_tiers(module: ModuleType) -> None:
    """DM/group adapters must declare a non-empty safety-tier tuple without admin-only.

    Uses explicit ``raise`` checks so the invariants survive ``python -O``.
    """
    tiers = getattr(module, "DM_SAFETY_TIERS", None)
    if not isinstance(tiers, tuple):
        raise ValueError(f"{module.__name__}.DM_SAFETY_TIERS must be a tuple")
    if not tiers:
        raise ValueError(f"{module.__name__}.DM_SAFETY_TIERS must be non-empty")
    if "admin-only" in tiers:
        raise ValueError(
            f"{module.__name__}.DM_SAFETY_TIERS must not include 'admin-only' "
            "(DM/group adapters must not declare admin scope)."
        )
    for tier in tiers:
        if tier not in ALLOWED_DM_SAFETY_TIERS:
            raise ValueError(
                f"unknown safety tier {tier!r} in {module.__name__}.DM_SAFETY_TIERS"
            )


def assert_error_class_taxonomy(module: ModuleType) -> None:
    """Retryable + fatal error class tuples must match the canonical taxonomy.

    Uses explicit ``raise`` checks (not ``assert``) so a misconfigured
    adapter is still rejected when Python runs with optimization enabled.
    """
    retryable = getattr(module, "RETRYABLE_ERROR_CLASSES", None)
    fatal = getattr(module, "FATAL_ERROR_CLASSES", None)
    if retryable != REQUIRED_RETRYABLE_ERROR_CLASSES:
        raise ValueError(
            f"{module.__name__}.RETRYABLE_ERROR_CLASSES diverges from canonical "
            f"taxonomy; got {retryable!r}"
        )
    if fatal != REQUIRED_FATAL_ERROR_CLASSES:
        raise ValueError(
            f"{module.__name__}.FATAL_ERROR_CLASSES diverges from canonical taxonomy; got {fatal!r}"
        )


def run_channel_contract(module: ModuleType) -> None:
    """Run every shared invariant against an adapter module.

    Per-adapter contract tests call this once and then add adapter-specific
    assertions (routing-key shape, mention parsing) below the call site.
    """
    assert_capability_tier(module)
    assert_dm_safety_tiers(module)
    assert_error_class_taxonomy(module)


__all__ = [
    "ALLOWED_CAPABILITY_TIERS",
    "ALLOWED_DM_SAFETY_TIERS",
    "PUBLIC_VENDOR_ADAPTERS",
    "REQUIRED_FATAL_ERROR_CLASSES",
    "REQUIRED_RETRYABLE_ERROR_CLASSES",
    "ChannelCapabilities",
    "ChannelCapabilityProfile",
    "ChannelPlatformCapability",
    "ChannelPlatformCapabilityStatus",
    "ChannelPlatformCategories",
    "ChannelPlatformManifest",
    "ChannelSendResult",
    "ChannelSendStatus",
    "assert_capability_tier",
    "assert_dm_safety_tiers",
    "assert_error_class_taxonomy",
    "channel_capability_profile",
    "channel_platform_manifest",
    "normalize_channel_send_result",
    "run_channel_contract",
]
