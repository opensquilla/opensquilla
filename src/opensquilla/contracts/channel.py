"""Channel adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class Attachment:
    name: str
    mime_type: str | None = None
    url: str | None = None
    data: bytes | None = None
    size: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IncomingMessage:
    sender_id: str
    channel_id: str
    content: str
    attachments: tuple[Attachment, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutgoingMessage:
    content: str
    attachments: tuple[Attachment, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    reply_to: str | None = None


@dataclass(frozen=True)
class ChannelHealth:
    connected: bool
    bot_user_id: str | None = None
    last_message_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChannelPort(Protocol):
    async def receive(self) -> IncomingMessage: ...

    async def send(self, message: OutgoingMessage) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def health_check(self) -> ChannelHealth: ...


class ChannelIngressPort(Protocol):
    async def handle_incoming(self, channel_name: str, message: IncomingMessage) -> None: ...


__all__ = [
    "Attachment",
    "ChannelHealth",
    "ChannelIngressPort",
    "ChannelPort",
    "IncomingMessage",
    "OutgoingMessage",
]
