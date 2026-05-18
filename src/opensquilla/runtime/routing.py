"""Neutral structural route-envelope helpers.

This module is intentionally outside the gateway package so scheduler and
session-owned route DTOs can share behavior without importing gateway routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RouteSourceKind(StrEnum):
    """Route source values shared by gateway, scheduler, and session DTOs."""

    WEB = "web"
    CLI = "cli"
    CHANNEL = "channel"
    CRON = "cron"
    SUBAGENT = "subagent"
    SYSTEM = "system"


@dataclass(frozen=True)
class ReplyTarget:
    """External or subscriber target that can receive a reply/announce."""

    kind: str
    channel_name: str | None = None
    channel_type: str | None = None
    to: str | None = None
    account_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def source_kind_value(source_kind: object) -> str:
    """Return a stable route source string from enum-like or string values."""
    return str(getattr(source_kind, "value", source_kind))


def interaction_mode_value(value: object) -> str:
    """Normalize interaction-mode values from domain-specific envelopes."""
    return str(getattr(value, "value", value))


def _dict_attr(value: object, name: str) -> dict[str, Any]:
    raw = getattr(value, name, {}) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def reply_target_from_route(target: object | None) -> ReplyTarget | None:
    """Copy a structural reply target into the neutral value type."""
    if target is None:
        return None
    return ReplyTarget(
        kind=str(getattr(target, "kind", "")),
        channel_name=_str_or_none(getattr(target, "channel_name", None)),
        channel_type=_str_or_none(getattr(target, "channel_type", None)),
        to=_str_or_none(getattr(target, "to", None)),
        account_id=_str_or_none(getattr(target, "account_id", None)),
        thread_id=_str_or_none(getattr(target, "thread_id", None)),
        metadata=_dict_attr(target, "metadata"),
    )


def delivery_fields_from_route(envelope: object) -> dict[str, Any]:
    """Translate a channel-capable route into SessionNode delivery fields."""
    target = reply_target_from_route(getattr(envelope, "reply_target", None))
    if target is None or target.kind != "channel":
        return {}
    return {
        "last_channel": target.channel_name,
        "last_to": target.to,
        "last_account_id": target.account_id,
        "last_thread_id": target.thread_id,
        "delivery_context": _dict_attr(envelope, "delivery_context"),
    }


__all__ = [
    "ReplyTarget",
    "RouteSourceKind",
    "delivery_fields_from_route",
    "interaction_mode_value",
    "reply_target_from_route",
    "source_kind_value",
]
