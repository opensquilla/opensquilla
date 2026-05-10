from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.types import ArtifactEvent, DoneEvent, TextDeltaEvent
from opensquilla.gateway.config import AttachmentsConfig, GatewayConfig
from opensquilla.provider import DoneEvent as ProviderDone
from opensquilla.provider import Message, ModelInfo
from opensquilla.provider import TextDeltaEvent as ProviderText
from opensquilla.provider import ToolUseEndEvent as ProviderToolUseEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolUseStart
from opensquilla.session.manager import SessionManager
from opensquilla.session.storage import SessionStorage
from opensquilla.tools.registry import ToolRegistry, ToolSpec
from opensquilla.tools.types import CallerKind, ToolContext, ToolError, current_tool_context


class _ArtifactProvider:
    provider_name = "test"

    def __init__(self) -> None:
        self.calls = 0
        self.model = "test/model"

    def chat(self, messages: list[Message], tools=None, config=None) -> AsyncIterator[Any]:
        self.calls += 1
        return self._stream(self.calls)

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderToolUseStart(tool_use_id="tool-1", tool_name="make_file")
            yield ProviderToolUseEnd(
                tool_use_id="tool-1",
                tool_name="make_file",
                arguments={},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)
            return
        yield ProviderText(text="done")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[ModelInfo]:
        return []


class _SelectorClone:
    current_config = SimpleNamespace(model="test/model")

    def __init__(self, provider: _ArtifactProvider) -> None:
        self.provider = provider

    def override_model(self, model: str) -> None:
        self.current_config = SimpleNamespace(model=model)
        self.provider.model = model

    def resolve(self) -> _ArtifactProvider:
        return self.provider


class _ProviderSelector:
    def __init__(self, provider: _ArtifactProvider) -> None:
        self.provider = provider

    def clone(self) -> _SelectorClone:
        return _SelectorClone(self.provider)


class _FailedPublishProvider:
    provider_name = "test"

    def __init__(self) -> None:
        self.calls = 0
        self.model = "test/model"

    def chat(self, messages: list[Message], tools=None, config=None) -> AsyncIterator[Any]:
        self.calls += 1
        return self._stream(self.calls)

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderToolUseStart(
                tool_use_id="publish-1",
                tool_name="publish_artifact",
            )
            yield ProviderToolUseEnd(
                tool_use_id="publish-1",
                tool_name="publish_artifact",
                arguments={"path": "missing-report.pptx"},
            )
            yield ProviderDone(stop_reason="tool_use", input_tokens=1, output_tokens=1)
            return
        yield ProviderText(text="Report file is ready for download.")
        yield ProviderDone(stop_reason="stop", input_tokens=1, output_tokens=1)

    async def list_models(self) -> list[ModelInfo]:
        return []


def _registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def make_file() -> str:
        ctx = current_tool_context.get()
        assert ctx is not None
        ctx.published_artifacts.append(
            {
                "id": "art-runtime",
                "kind": "artifact_ref",
                "name": "runtime.txt",
                "mime": "text/plain",
                "size": 4,
                "sha256": "b" * 64,
                "session_id": ctx.artifact_session_id,
                "session_key": ctx.session_key,
                "source": "make_file",
                "created_at": "2026-05-06T12:00:00Z",
                "download_url": (
                    "/api/v1/artifacts/art-runtime"
                    "?sessionKey=agent%3Amain%3Awebchat%3Aartifact-runtime"
                ),
            }
        )
        return "published"

    registry.register(
        ToolSpec(name="make_file", description="Make a file", parameters={}),
        make_file,
    )
    return registry


def _failed_publish_registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def publish_artifact(path: str) -> str:
        raise ToolError(f"artifact file not found: {path}")

    registry.register(
        ToolSpec(
            name="publish_artifact",
            description="Publish a generated artifact",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        publish_artifact,
    )
    return registry


@pytest.mark.asyncio
async def test_turn_runner_streams_artifact_event_and_persists_history(tmp_path) -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    manager = SessionManager(storage)
    session_key = "agent:main:webchat:artifact-runtime"
    session = await manager.create(session_key)
    runner = TurnRunner(
        provider_selector=_ProviderSelector(_ArtifactProvider()),
        tool_registry=_registry(),
        session_manager=manager,
        config=GatewayConfig(
            attachments=AttachmentsConfig(media_root=str(tmp_path / "media")),
        ),
    )
    tool_context = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.WEB,
        workspace_dir=str(tmp_path),
    )

    try:
        events = [
            event
            async for event in runner.run(
                "make it",
                session_key,
                tool_context=tool_context,
                history_has_persisted_user=False,
                no_memory_capture=True,
            )
        ]
        artifact_events = [event for event in events if isinstance(event, ArtifactEvent)]
        assert len(artifact_events) == 1
        assert artifact_events[0].id == "art-runtime"
        assert artifact_events[0].session_id == session.session_id
        assert artifact_events[0].session_key == ""
        assert artifact_events[0].download_url == "/api/v1/artifacts/art-runtime"

        transcript = await manager.get_transcript(session_key)
        assistant = [entry for entry in transcript if entry.role == "assistant"][-1]
        payload = json.loads(assistant.content)
        assert payload["text"] == "done"
        assert payload["artifacts"][0]["id"] == "art-runtime"
        assert payload["artifacts"][0]["session_id"] == session.session_id
        assert "session_key" not in payload["artifacts"][0]
        assert "sessionKey" not in assistant.content

        class _HistoryCapture:
            def __init__(self) -> None:
                self.history = []

            def set_history(self, history) -> None:
                self.history = history

        history_capture = _HistoryCapture()
        await runner._load_history(agent=history_capture, session_key=session_key)
        assert "[generated artifact omitted: runtime.txt (text/plain)]" in str(
            history_capture.history[-1].content
        )
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_turn_runner_marks_failed_artifact_delivery_in_final_text(tmp_path) -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    manager = SessionManager(storage)
    session_key = "agent:main:webchat:artifact-failed"
    await manager.create(session_key)
    runner = TurnRunner(
        provider_selector=_ProviderSelector(_FailedPublishProvider()),
        tool_registry=_failed_publish_registry(),
        session_manager=manager,
        config=GatewayConfig(
            attachments=AttachmentsConfig(media_root=str(tmp_path / "media")),
        ),
    )
    tool_context = ToolContext(
        is_owner=True,
        caller_kind=CallerKind.WEB,
        workspace_dir=str(tmp_path),
    )

    try:
        events = [
            event
            async for event in runner.run(
                "make report",
                session_key,
                tool_context=tool_context,
                history_has_persisted_user=False,
                no_memory_capture=True,
            )
        ]

        text_deltas = [event.text for event in events if isinstance(event, TextDeltaEvent)]
        done = next(event for event in events if isinstance(event, DoneEvent))
        assert any("File delivery failed:" in text for text in text_deltas)
        assert "File delivery failed:" in done.text
        assert "Ask me to resend the file after I correct the generated file path." in done.text
        assert "publish_artifact" not in done.text
        assert "active workspace" not in done.text
        assert "missing-report.pptx" not in done.text

        transcript = await manager.get_transcript(session_key)
        assistant = [entry for entry in transcript if entry.role == "assistant"][-1]
        assert "Report file is ready for download." in assistant.content
        assert "File delivery failed:" in assistant.content
        assert "artifacts" not in assistant.content
    finally:
        await storage.close()
