from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from opensquilla.tools.types import InteractionMode


class FakeSourceKind(StrEnum):
    CRON = "cron"
    SUBAGENT = "subagent"


@dataclass(frozen=True)
class FakeReplyTarget:
    kind: str
    channel_name: str | None = None
    channel_type: str | None = None
    to: str | None = None
    account_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FakeEnvelope:
    source_kind: FakeSourceKind | str
    source_name: str
    agent_id: str
    session_key: str
    sender_id: str | None = None
    channel_type: str | None = None
    channel_name: str | None = None
    channel_id: str | None = None
    reply_target: FakeReplyTarget | None = None
    input_provenance: dict[str, Any] = field(default_factory=dict)
    delivery_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    interaction_mode: InteractionMode | str = InteractionMode.UNATTENDED


def test_structural_delivery_fields_copy_reply_target_and_context() -> None:
    from opensquilla.runtime.routing import delivery_fields_from_route

    envelope = FakeEnvelope(
        source_kind=FakeSourceKind.CRON,
        source_name="cron",
        agent_id="ops",
        session_key="cron:job:run",
        reply_target=FakeReplyTarget(
            kind="channel",
            channel_name="telegram",
            to="chat-1",
            account_id="acct-1",
            thread_id="thread-1",
        ),
        delivery_context={"sender_id": "cron-job-1", "channel_id": "chat-1"},
    )

    assert delivery_fields_from_route(envelope) == {
        "last_channel": "telegram",
        "last_to": "chat-1",
        "last_account_id": "acct-1",
        "last_thread_id": "thread-1",
        "delivery_context": {"sender_id": "cron-job-1", "channel_id": "chat-1"},
    }


def test_structural_source_and_interaction_values_accept_enum_like_inputs() -> None:
    from opensquilla.runtime.routing import interaction_mode_value, source_kind_value

    assert source_kind_value(FakeSourceKind.CRON) == "cron"
    assert source_kind_value("subagent") == "subagent"
    assert interaction_mode_value(InteractionMode.UNATTENDED) == "unattended"
    assert interaction_mode_value("interactive") == "interactive"


def test_neutral_route_contract_does_not_import_tools_package() -> None:
    source = Path("src/opensquilla/runtime/routing.py").read_text(encoding="utf-8")

    assert "opensquilla.tools" not in source
