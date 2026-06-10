from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from opensquilla.attachment_refs import write_transcript_material
from opensquilla.engine import Agent, AgentConfig
from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.steps.squilla_router import apply_squilla_router
from opensquilla.engine.steps.vision_followup_gate import apply_vision_followup_gate
from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider import ChatConfig, DoneEvent, Message, ModelCapabilities, TextDeltaEvent
from opensquilla.provider.types import ContentBlockImage


@dataclass
class _TranscriptEntry:
    role: str
    content: str
    tool_calls: list[Any] | None = None
    reasoning_content: str | None = None
    token_count: int | None = None


@dataclass
class _SessionNode:
    session_key: str
    session_id: str


class _FakeSessionManager:
    def __init__(self) -> None:
        self._nodes: dict[str, _SessionNode] = {}
        self._transcripts: dict[str, list[_TranscriptEntry]] = {}

    async def create(self, session_key: str) -> _SessionNode:
        node = _SessionNode(session_key=session_key, session_id=f"id-{len(self._nodes) + 1}")
        self._nodes[session_key] = node
        self._transcripts.setdefault(session_key, [])
        return node

    async def append_message(self, session_key: str, role: str, content: str) -> _TranscriptEntry:
        entry = _TranscriptEntry(role=role, content=content)
        self._transcripts.setdefault(session_key, []).append(entry)
        return entry

    async def get_transcript(self, session_key: str) -> list[_TranscriptEntry]:
        return list(self._transcripts.get(session_key, []))

    async def get_session(self, session_key: str) -> _SessionNode | None:
        return self._nodes.get(session_key)

    async def get_context_states(self, session_key: str) -> list[Any]:  # noqa: ARG002
        return []


class _CapturingProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append({"messages": messages, "tools": tools, "config": config})
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield TextDeltaEvent(text="ok")
        yield DoneEvent(stop_reason="end_turn", input_tokens=3, output_tokens=1)

    async def list_models(self) -> list[Any]:
        return []


class _GateThenCaptureProvider(_CapturingProvider):
    def __init__(self, gate_payload: str) -> None:
        super().__init__()
        self.gate_payload = gate_payload
        self.gate_calls = 0

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        if (
            config is not None
            and isinstance(config.system, str)
            and "requires reusing a previous image" in config.system
        ):
            self.gate_calls += 1
            return self._gate_stream()
        return super().chat(messages, tools=tools, config=config)

    async def _gate_stream(self) -> AsyncIterator[Any]:
        yield TextDeltaEvent(text=self.gate_payload)
        yield DoneEvent(stop_reason="end_turn", input_tokens=9, output_tokens=5)


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _inline_image_envelope(text: str, payload: bytes = b"\x89PNG\r\n\x1a\n") -> str:
    return json.dumps(
        {
            "text": text,
            "attachments": [
                {
                    "type": "image/png",
                    "name": "first.png",
                    "data": _b64(payload),
                }
            ],
        }
    )


def _message_has_image(message: Message) -> bool:
    return isinstance(message.content, list) and any(
        isinstance(block, ContentBlockImage) for block in message.content
    )


@pytest.mark.asyncio
async def test_image_followup_routes_vision_and_replays_inline_history_image() -> None:
    manager = _FakeSessionManager()
    key = "agent:main:image-followup-inline"
    config = GatewayConfig()
    runner = TurnRunner(provider_selector=MagicMock(), session_manager=manager, config=config)
    await manager.create(key)
    await manager.append_message(key, "user", _inline_image_envelope("Describe this image."))
    await manager.append_message(key, "assistant", "It shows a small test image.")
    await manager.append_message(key, "user", "Continue from that image.")

    router_context = await runner._router_previous_assistant_context(
        key,
        exclude_last_user=True,
    )
    assert router_context["history_has_recent_image"] is True
    assert router_context["history_image_turn_count"] == 1
    assert router_context["vision_sticky_remaining"] == 3
    assert router_context["turns_since_last_image"] == 0
    assert router_context["last_image_turn_text"].startswith("Describe this image.")

    gate_provider = _GateThenCaptureProvider(
        '{"decision":"needs_image","confidence":0.92,"reason":"explicit continuation"}'
    )
    ctx = TurnContext(
        message="Continue from that image.",
        session_key=key,
        config=config,
        provider=gate_provider,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
        metadata={
            "router_history_user_texts": ["Describe this image."],
            "router_history_has_recent_image": True,
            "router_history_image_turn_count": 1,
            "router_vision_sticky_remaining": 3,
            "router_turns_since_last_image": 0,
            "router_last_image_turn_text": "Describe this image.",
            "router_vision_candidate_turns": 8,
        },
        raw_message="Continue from that image.",
    )
    gated = await apply_vision_followup_gate(ctx)
    routed = await apply_squilla_router(gated)
    assert gate_provider.gate_calls == 0
    assert routed.metadata["router_vision_followup_gate_decision"] == "needs_image"
    assert routed.metadata["router_vision_followup_gate_source"] == "explicit_image_reference"
    assert routed.metadata["router_vision_followup_needs_image"] is True
    assert routed.metadata["routing_source"] == "image_route"
    assert routed.metadata["image_route_reason"] == "gate_history"
    assert routed.metadata["route_max_history_turns"] == 8

    provider = _CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            model_id=routed.model,
            model_capabilities=ModelCapabilities(supports_vision=True),
            preserve_historical_images=True,
        ),
    )
    await runner._load_history(agent, key)
    events = [event async for event in agent.run_turn("Continue from that image.")]

    assert any(event.kind == "done" for event in events)
    sent_messages = provider.calls[0]["messages"]
    assert any(_message_has_image(message) for message in sent_messages)
    assert isinstance(sent_messages[-1].content, str)
    assert sent_messages[-1].content.startswith("Continue from that image.")


@pytest.mark.asyncio
async def test_gate_text_only_followup_does_not_image_route() -> None:
    key = "agent:main:image-followup-gate-text"
    config = GatewayConfig()
    provider = _GateThenCaptureProvider(
        '{"decision":"text_only","confidence":0.9,"reason":"new coding task"}'
    )
    ctx = TurnContext(
        message="Now write a Python script.",
        session_key=key,
        config=config,
        provider=provider,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
        metadata={
            "router_history_user_texts": ["Describe this image."],
            "router_history_has_recent_image": True,
            "router_history_image_turn_count": 1,
            "router_vision_sticky_remaining": 3,
            "router_turns_since_last_image": 0,
            "router_last_image_turn_text": "Describe this image.",
            "router_vision_candidate_turns": 8,
        },
        raw_message="Now write a Python script.",
    )

    gated = await apply_vision_followup_gate(ctx)
    turn = await apply_squilla_router(gated)

    assert provider.gate_calls == 1
    assert turn.metadata["router_vision_followup_gate_decision"] == "text_only"
    assert turn.metadata["router_vision_followup_needs_image"] is False
    assert turn.metadata.get("image_route_reason") is None


@pytest.mark.asyncio
async def test_gate_unknown_recent_fallback_routes_image() -> None:
    config = GatewayConfig()
    provider = _GateThenCaptureProvider(
        '{"decision":"unknown","confidence":0.2,"reason":"ambiguous pronoun"}'
    )
    ctx = TurnContext(
        message="What about this?",
        session_key="agent:main:image-followup-unknown-recent",
        config=config,
        provider=provider,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
        metadata={
            "router_history_has_recent_image": True,
            "router_history_image_turn_count": 1,
            "router_turns_since_last_image": 1,
            "router_last_image_turn_text": "Describe this image.",
            "router_vision_candidate_turns": 8,
        },
        raw_message="What about this?",
    )

    gated = await apply_vision_followup_gate(ctx)
    routed = await apply_squilla_router(gated)

    assert provider.gate_calls == 1
    assert routed.metadata["router_vision_followup_gate_decision"] == "unknown"
    assert routed.metadata["router_vision_followup_needs_image"] is True
    assert routed.metadata["router_vision_followup_fallback"] == "image_if_recent"
    assert routed.metadata["image_route_reason"] == "gate_history"


@pytest.mark.asyncio
async def test_gate_unknown_old_fallback_uses_text_router() -> None:
    config = GatewayConfig()
    provider = _GateThenCaptureProvider(
        '{"decision":"unknown","confidence":0.2,"reason":"ambiguous but old"}'
    )
    ctx = TurnContext(
        message="What about this?",
        session_key="agent:main:image-followup-unknown-old",
        config=config,
        provider=provider,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
        metadata={
            "router_history_has_recent_image": True,
            "router_history_image_turn_count": 1,
            "router_turns_since_last_image": 3,
            "router_last_image_turn_text": "Describe this image.",
            "router_vision_candidate_turns": 8,
        },
        raw_message="What about this?",
    )

    gated = await apply_vision_followup_gate(ctx)
    routed = await apply_squilla_router(gated)

    assert provider.gate_calls == 1
    assert routed.metadata["router_vision_followup_gate_decision"] == "unknown"
    assert routed.metadata["router_vision_followup_needs_image"] is False
    assert routed.metadata.get("image_route_reason") is None


@pytest.mark.asyncio
async def test_historical_image_ref_replays_from_real_material_store(tmp_path: Path) -> None:
    manager = _FakeSessionManager()
    key = "agent:main:image-followup-ref"
    config = GatewayConfig()
    config.attachments.media_root = str(tmp_path / "media")
    runner = TurnRunner(provider_selector=MagicMock(), session_manager=manager, config=config)
    node = await manager.create(key)
    payload = b"\x89PNG\r\n\x1a\nreal-material"
    sha, _, _ = write_transcript_material(
        media_root=Path(config.attachments.media_root),
        session_id=node.session_id,
        payload=payload,
    )
    envelope = json.dumps(
        {
            "text": "Describe the stored image.",
            "attachments": [
                {
                    "mime": "image/png",
                    "name": "stored.png",
                    "sha256_ref": sha,
                }
            ],
        }
    )
    await manager.append_message(key, "user", envelope)
    await manager.append_message(key, "assistant", "It is stored on disk.")
    await manager.append_message(key, "user", "Use that stored image again.")

    router_context = await runner._router_previous_assistant_context(
        key,
        exclude_last_user=True,
    )
    assert router_context["history_has_recent_image"] is True
    assert router_context["vision_sticky_remaining"] == 3

    provider = _CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            model_capabilities=ModelCapabilities(supports_vision=True),
            preserve_historical_images=True,
        ),
    )
    await runner._load_history(agent, key)
    events = [event async for event in agent.run_turn("Use that stored image again.")]

    assert any(event.kind == "done" for event in events)
    image_blocks = [
        block
        for message in provider.calls[0]["messages"]
        if isinstance(message.content, list)
        for block in message.content
        if isinstance(block, ContentBlockImage)
    ]
    assert len(image_blocks) == 1
    assert base64.b64decode(image_blocks[0].data) == payload


@pytest.mark.asyncio
async def test_default_sticky_window_keeps_third_followup_active() -> None:
    manager = _FakeSessionManager()
    key = "agent:main:image-followup-third"
    config = GatewayConfig()
    runner = TurnRunner(provider_selector=MagicMock(), session_manager=manager, config=config)

    await manager.create(key)
    await manager.append_message(key, "user", _inline_image_envelope("Describe this image."))
    await manager.append_message(key, "assistant", "It shows a small test image.")
    await manager.append_message(key, "user", "First follow-up.")
    await manager.append_message(key, "assistant", "First answer.")
    await manager.append_message(key, "user", "Second follow-up.")
    await manager.append_message(key, "assistant", "Second answer.")
    await manager.append_message(key, "user", "Third follow-up.")

    router_context = await runner._router_previous_assistant_context(
        key,
        exclude_last_user=True,
    )

    assert router_context["history_has_recent_image"] is True
    assert router_context["history_image_turn_count"] == 1
    assert router_context["vision_sticky_remaining"] == 1


@pytest.mark.asyncio
async def test_image_history_outside_sticky_window_does_not_route_or_replay() -> None:
    manager = _FakeSessionManager()
    key = "agent:main:image-followup-sticky-expired"
    config = GatewayConfig()
    config.squilla_router.vision_history_lookback_turns = 4
    config.squilla_router.vision_sticky_followup_turns = 1
    runner = TurnRunner(provider_selector=MagicMock(), session_manager=manager, config=config)
    await manager.create(key)
    await manager.append_message(key, "user", _inline_image_envelope("Old image."))
    await manager.append_message(key, "assistant", "Old answer.")
    await manager.append_message(key, "user", "Plain intervening question.")
    await manager.append_message(key, "assistant", "Plain answer.")
    await manager.append_message(key, "user", "Current follow-up.")

    router_context = await runner._router_previous_assistant_context(
        key,
        exclude_last_user=True,
    )
    assert router_context["history_has_recent_image"] is True
    assert router_context["history_image_turn_count"] == 1
    assert "vision_sticky_remaining" not in router_context

    ctx = TurnContext(
        message="Current follow-up.",
        session_key=key,
        config=config,
        provider=None,
        model=config.llm.model,
        tool_defs=[],
        system_prompt="system",
        metadata={
            "router_history_has_recent_image": True,
            "router_history_image_turn_count": 1,
        },
    )
    routed = await apply_squilla_router(ctx)
    assert routed.metadata["routing_source"] != "image_route"

    provider = _CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            model_id=routed.model,
            model_capabilities=ModelCapabilities(supports_vision=False),
        ),
    )
    await runner._load_history(agent, key)
    events = [event async for event in agent.run_turn("Current follow-up.")]

    assert any(event.kind == "done" for event in events)
    assert not any(_message_has_image(message) for message in provider.calls[0]["messages"])


@pytest.mark.asyncio
async def test_text_model_history_keeps_image_as_marker_not_provider_image() -> None:
    manager = _FakeSessionManager()
    key = "agent:main:image-followup-text-model"
    config = GatewayConfig()
    runner = TurnRunner(provider_selector=MagicMock(), session_manager=manager, config=config)
    await manager.create(key)
    await manager.append_message(key, "user", _inline_image_envelope("Describe this image."))
    await manager.append_message(key, "assistant", "It shows a small test image.")
    await manager.append_message(key, "user", "Continue as text.")

    provider = _CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            model_capabilities=ModelCapabilities(supports_vision=False),
        ),
    )
    await runner._load_history(agent, key)
    events = [event async for event in agent.run_turn("Continue as text.")]

    assert any(event.kind == "done" for event in events)
    sent_messages = provider.calls[0]["messages"]
    assert not any(_message_has_image(message) for message in sent_messages)
    assert "historical attachment omitted" in str(sent_messages[0].content)


@pytest.mark.asyncio
async def test_text_only_followup_does_not_replay_history_image_on_vision_model() -> None:
    manager = _FakeSessionManager()
    key = "agent:main:image-followup-text-only-vision-model"
    config = GatewayConfig()
    runner = TurnRunner(provider_selector=MagicMock(), session_manager=manager, config=config)
    await manager.create(key)
    await manager.append_message(key, "user", _inline_image_envelope("Describe this image."))
    await manager.append_message(key, "assistant", "It shows a small test image.")
    await manager.append_message(key, "user", "Now write a Python script.")

    provider = _CapturingProvider()
    agent = Agent(
        provider=provider,
        config=AgentConfig(
            max_iterations=1,
            model_capabilities=ModelCapabilities(supports_vision=True),
        ),
    )
    await runner._load_history(agent, key)
    events = [event async for event in agent.run_turn("Now write a Python script.")]

    assert any(event.kind == "done" for event in events)
    sent_messages = provider.calls[0]["messages"]
    assert not any(_message_has_image(message) for message in sent_messages)
    assert "historical attachment omitted" in str(sent_messages[0].content)
