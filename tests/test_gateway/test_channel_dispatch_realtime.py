from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.artifacts import ArtifactStore
from opensquilla.channels.stream_policy import resolve_channel_stream_policy
from opensquilla.channels.types import Attachment, IncomingMessage, OutgoingMessage
from opensquilla.engine.types import ArtifactEvent, DoneEvent, TextDeltaEvent
from opensquilla.gateway.attachment_ingest import (
    MAX_STAGED_PDF_BYTES,
    MAX_TOTAL_ATTACHMENT_BYTES,
    AttachmentTotalTooLargeError,
)
from opensquilla.gateway.channel_dispatch import (
    _artifact_fallback_lines,
    _deliver_runtime_channel_reply,
    _dispatch_combined_message_after_debounce,
    _ingest_channel_message_attachments,
    _run_turn_batch_path,
    _run_turn_with_streaming,
    _RuntimeChannelStreamRelay,
)
from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig
from opensquilla.gateway.routing import build_channel_route_envelope
from opensquilla.safety.permission_matrix import Principal, is_tool_allowed
from opensquilla.tools.types import CallerKind


class _FakeChannel:
    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)


class _FakeEventBridge:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    async def emit(self, session_key: str, event_name: str, payload: dict) -> None:
        self.events.append((session_key, event_name, payload))


def _message() -> IncomingMessage:
    return IncomingMessage(sender_id="u1", channel_id="c1", content="hello")


def _tool_ctx(agent_id: str = "main") -> SimpleNamespace:
    return SimpleNamespace(agent_id=agent_id)


def _exact_pdf(size: int) -> bytes:
    header = b"%PDF-1.4\n"
    return header + b"a" * (size - len(header))


def test_channel_stream_policy_prefers_adapter_stream_updates() -> None:
    class StreamingChannel:
        async def send_streaming(self, chunks):
            async for _ in chunks:
                pass

    policy = resolve_channel_stream_policy(StreamingChannel())

    assert policy.mode == "adapter_stream"
    assert policy.relay_stream is True
    assert policy.typing_keepalive is False


def test_channel_stream_policy_uses_typing_placeholder_without_stream_editing() -> None:
    class TypingOnlyChannel:
        async def send_typing(self) -> None:
            pass

        async def send(self, message: OutgoingMessage) -> None:
            pass

    policy = resolve_channel_stream_policy(TypingOnlyChannel())

    assert policy.mode == "typing_final"
    assert policy.relay_stream is False
    assert policy.typing_keepalive is True


def test_channel_stream_policy_allows_adapter_final_only_override() -> None:
    class FinalOnlyChannel:
        stream_update_strategy = "final_only"

        async def send_streaming(self, chunks):
            async for _ in chunks:
                pass

    policy = resolve_channel_stream_policy(FinalOnlyChannel())

    assert policy.mode == "final_only"
    assert policy.relay_stream is False
    assert policy.typing_keepalive is False


@pytest.mark.asyncio
async def test_direct_channel_turn_emits_run_heartbeat_while_stream_is_quiet() -> None:
    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            await asyncio.sleep(0.03)
            yield TextDeltaEvent(text="ok")
            yield DoneEvent()

    channel = _FakeChannel()
    bridge = _FakeEventBridge()
    config = SimpleNamespace(
        agent_stream_heartbeat_interval_seconds=0.01,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_batch_path(
        channel,
        FakeTurnRunner(),
        _message(),
        "agent:main:channel-test",
        _tool_ctx(),
        bridge,
        None,
        config,
    )

    assert any(event_name == "session.event.run_heartbeat" for _, event_name, _ in bridge.events)
    assert channel.sent[-1].content == "ok"


@pytest.mark.asyncio
async def test_direct_channel_batch_turn_sends_artifact_fallback() -> None:
    artifact = {
        "id": "art-channel",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 4,
        "sha256": "f" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:channel-test",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-channel?sessionKey=agent%3Amain%3Achannel-test",
        "store": "artifacts",
    }

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            yield ArtifactEvent(**artifact)
            yield DoneEvent()

    channel = _FakeChannel()
    bridge = _FakeEventBridge()
    config = SimpleNamespace(
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_batch_path(
        channel,
        FakeTurnRunner(),
        _message(),
        "agent:main:channel-test",
        _tool_ctx(),
        bridge,
        None,
        config,
    )

    assert channel.sent[-1].content == "Generated file: report.txt -> available in WebUI"
    assert "/api/v1/artifacts" not in channel.sent[-1].content
    assert "sessionKey" not in channel.sent[-1].content
    event_artifact = bridge.events[-1][2]
    assert bridge.events[-1] == (
        "agent:main:channel-test",
        "session.event.artifact",
        event_artifact,
    )
    assert event_artifact["download_url"] == "/api/v1/artifacts/art-channel"
    assert "session_key" not in event_artifact
    assert "sessionKey" not in json.dumps(event_artifact)


@pytest.mark.asyncio
async def test_direct_channel_batch_turn_sends_artifact_with_adapter_file_upload(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"deck bytes",
        session_id="session-1",
        session_key="agent:main:channel-test",
        name="report.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source="publish_artifact",
    )
    artifact = ref.to_dict()

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            yield TextDeltaEvent(text="done")
            yield ArtifactEvent(**artifact)
            yield DoneEvent()

    class FileUploadingChannel(_FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.files: list[tuple[str, str]] = []

        async def send_file(self, chat_id: str, file_path: str) -> None:
            assert Path(file_path).is_file()
            self.files.append((chat_id, Path(file_path).name))

    channel = FileUploadingChannel()
    bridge = _FakeEventBridge()
    config = SimpleNamespace(
        attachments=SimpleNamespace(media_root=str(tmp_path)),
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_batch_path(
        channel,
        FakeTurnRunner(),
        _message(),
        "agent:main:channel-test",
        _tool_ctx(),
        bridge,
        None,
        config,
    )

    assert channel.sent[-1].content == "done"
    assert channel.files == [("c1", "report.pptx")]


@pytest.mark.asyncio
async def test_direct_channel_batch_turn_sends_artifact_with_original_filename(
    tmp_path,
) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"\x89PNG\r\n\x1a\nimage bytes",
        session_id="session-1",
        session_key="agent:main:channel-test",
        name="思考快与慢_信息图.png",
        mime="image/png",
        source="publish_artifact",
    )

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            yield TextDeltaEvent(text="done")
            yield ArtifactEvent(**ref.to_dict())
            yield DoneEvent()

    class FileUploadingChannel(_FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.files: list[tuple[str, str]] = []

        async def send_file(self, chat_id: str, file_path: str) -> None:
            assert Path(file_path).is_file()
            self.files.append((chat_id, Path(file_path).name))

    channel = FileUploadingChannel()
    config = SimpleNamespace(
        attachments=SimpleNamespace(media_root=str(tmp_path)),
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_batch_path(
        channel,
        FakeTurnRunner(),
        _message(),
        "agent:main:channel-test",
        _tool_ctx(),
        _FakeEventBridge(),
        None,
        config,
    )

    assert channel.sent[-1].content == "done"
    assert channel.files == [("c1", "思考快与慢_信息图.png")]


@pytest.mark.asyncio
async def test_direct_channel_batch_turn_removes_delivered_markdown_image_reference(
    tmp_path,
) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"\x89PNG\r\n\x1a\nimage bytes",
        session_id="session-1",
        session_key="agent:main:channel-test",
        name="thinking_fast_slow_v3.png",
        mime="image/png",
        source="publish_artifact",
    )

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            yield TextDeltaEvent(
                text=(
                    "新版改进：\n\n"
                    "![Thinking, Fast and Slow Infographic v3](thinking_fast_slow_v3.png)\n\n"
                    "点击附件保存原图。"
                )
            )
            yield ArtifactEvent(**ref.to_dict())
            yield DoneEvent()

    class FileUploadingChannel(_FakeChannel):
        async def send_file(self, chat_id: str, file_path: str) -> None:
            return None

    channel = FileUploadingChannel()
    config = SimpleNamespace(
        attachments=SimpleNamespace(media_root=str(tmp_path)),
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_batch_path(
        channel,
        FakeTurnRunner(),
        _message(),
        "agent:main:channel-test",
        _tool_ctx(),
        _FakeEventBridge(),
        None,
        config,
    )

    assert channel.sent[-1].content == "新版改进：\n\n点击附件保存原图。"
    assert "![Thinking" not in channel.sent[-1].content


@pytest.mark.asyncio
async def test_direct_channel_batch_turn_removes_artifact_markers_from_channel_text(
    tmp_path,
) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"image bytes",
        session_id="session-1",
        session_key="agent:main:channel-test",
        name="chart.png",
        mime="image/png",
        source="publish_artifact",
    )
    marker = "[generated artifact omitted: chart.png (image/png)]"
    artifact = ref.to_dict()

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            yield TextDeltaEvent(text=f"ready\n\n{marker}")
            yield ArtifactEvent(**artifact)
            yield DoneEvent()

    class FileUploadingChannel(_FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.files: list[tuple[str, str]] = []

        async def send_file(self, chat_id: str, file_path: str) -> None:
            assert Path(file_path).is_file()
            self.files.append((chat_id, Path(file_path).name))

    channel = FileUploadingChannel()
    config = SimpleNamespace(
        attachments=SimpleNamespace(media_root=str(tmp_path)),
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_batch_path(
        channel,
        FakeTurnRunner(),
        _message(),
        "agent:main:channel-test",
        _tool_ctx(),
        _FakeEventBridge(),
        None,
        config,
    )

    assert channel.sent[-1].content == "ready"
    assert marker not in channel.sent[-1].content
    assert channel.files == [("c1", "chart.png")]


@pytest.mark.asyncio
async def test_channel_admin_sender_gets_owner_tool_context_for_agent_turn(tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            captured["tool_context"] = kwargs["tool_context"]
            yield TextDeltaEvent(text="ok")
            yield DoneEvent()

    msg = _message()
    envelope = build_channel_route_envelope(
        msg,
        session_key="agent:main:feishu:u1",
        session_prefix="feishu",
        agent_id="main",
    )
    config = SimpleNamespace(
        channel_admin_senders={"feishu": ["u1"]},
        workspace_dir=str(tmp_path),
        workspace_strict=True,
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_with_streaming(
        _FakeChannel(),
        FakeTurnRunner(),
        msg,
        "agent:main:feishu:u1",
        config=config,
        route_envelope=envelope,
    )

    tool_context = captured["tool_context"]
    assert tool_context.is_owner is True
    assert tool_context.caller_kind is CallerKind.CHANNEL
    assert tool_context.channel_kind == "feishu"
    assert tool_context.sender_id == "u1"
    decision = is_tool_allowed(
        "write_file",
        "dm",
        Principal(role="operator", channel_id=tool_context.session_key),
    )
    assert decision.allowed is True
    assert decision.reason == "operator_override"


@pytest.mark.asyncio
async def test_unlisted_channel_sender_keeps_restricted_tool_context_for_agent_turn(
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            captured["tool_context"] = kwargs["tool_context"]
            yield TextDeltaEvent(text="ok")
            yield DoneEvent()

    msg = _message()
    envelope = build_channel_route_envelope(
        msg,
        session_key="agent:main:feishu:u1",
        session_prefix="feishu",
        agent_id="main",
    )
    config = SimpleNamespace(
        channel_admin_senders={"feishu": ["other-user"]},
        workspace_dir=str(tmp_path),
        workspace_strict=True,
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_with_streaming(
        _FakeChannel(),
        FakeTurnRunner(),
        msg,
        "agent:main:feishu:u1",
        config=config,
        route_envelope=envelope,
    )

    tool_context = captured["tool_context"]
    assert tool_context.is_owner is False
    assert tool_context.caller_kind is CallerKind.CHANNEL
    assert tool_context.channel_kind == "feishu"
    assert tool_context.sender_id == "u1"


def test_channel_artifact_fallback_uses_only_channel_safe_absolute_links() -> None:
    assert _artifact_fallback_lines(
        [
            {
                "id": "art-1",
                "name": "report.txt",
                "download_url": "/api/v1/artifacts/art-1?sessionKey=secret",
            }
        ]
    ) == ["Generated file: report.txt -> available in WebUI"]

    assert _artifact_fallback_lines(
        [
            {
                "id": "art-2",
                "name": "signed.txt",
                "signed_download_url": "https://gateway.example/artifacts/art-2?sig=short",
            }
        ]
    ) == [
        "Generated file: signed.txt -> "
        "https://gateway.example/artifacts/art-2?sig=short"
    ]

    assert _artifact_fallback_lines(
        [
            {
                "id": "art-3",
                "name": "bad.txt",
                "channel_download_url": "/api/v1/artifacts/art-3?token=long",
            }
        ]
    ) == ["Generated file: bad.txt -> available in WebUI"]


@pytest.mark.asyncio
async def test_runtime_channel_stream_relay_emits_artifact_fallback() -> None:
    class StreamingChannel:
        def __init__(self) -> None:
            self.chunks: list[str] = []

        async def send_streaming(self, chunks, **kwargs):
            async for chunk in chunks:
                self.chunks.append(chunk)

    class FakeTaskRuntime:
        async def enqueue(self, envelope, message: str, *, stream_event_sink=None):
            return None

    channel = StreamingChannel()
    relay = _RuntimeChannelStreamRelay.maybe_start(channel, _message(), FakeTaskRuntime())

    assert relay is not None

    await relay.emit(
        {
            "kind": "artifact",
            "id": "art-stream",
            "name": "stream.txt",
            "download_url": "/api/v1/artifacts/art-stream?sessionKey=secret",
        }
    )
    await relay.close()

    assert channel.chunks == ["Generated file: stream.txt -> available in WebUI"]
    assert relay.text_emitted is True


@pytest.mark.asyncio
async def test_runtime_channel_stream_relay_appends_artifact_fallback_to_text() -> None:
    class StreamingChannel:
        def __init__(self) -> None:
            self.chunks: list[str] = []

        async def send_streaming(self, chunks, **kwargs):
            async for chunk in chunks:
                self.chunks.append(chunk)

    class FakeTaskRuntime:
        async def enqueue(self, envelope, message: str, *, stream_event_sink=None):
            return None

    channel = StreamingChannel()
    relay = _RuntimeChannelStreamRelay.maybe_start(channel, _message(), FakeTaskRuntime())

    assert relay is not None

    await relay.emit(TextDeltaEvent(text="done"))
    await relay.emit(
        {
            "kind": "artifact",
            "id": "art-stream",
            "name": "stream.txt",
            "download_url": "/api/v1/artifacts/art-stream?sessionKey=secret",
        }
    )
    await relay.close()

    assert channel.chunks == [
        "done",
        "\n\nGenerated file: stream.txt -> available in WebUI",
    ]


@pytest.mark.asyncio
async def test_runtime_channel_stream_relay_sends_artifact_with_adapter_upload(
    tmp_path,
) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"deck bytes",
        session_id="session-1",
        session_key="agent:main:channel-test",
        name="report.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source="publish_artifact",
    )

    class StreamingFileChannel(_FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.chunks: list[str] = []
            self.files: list[tuple[str, str]] = []

        async def send_streaming(self, chunks, **kwargs):
            async for chunk in chunks:
                self.chunks.append(chunk)

        async def send_file(self, chat_id: str, file_path: str) -> None:
            assert Path(file_path).is_file()
            self.files.append((chat_id, Path(file_path).name))

    class FakeTaskRuntime:
        async def enqueue(self, envelope, message: str, *, stream_event_sink=None):
            return None

    config = SimpleNamespace(attachments=SimpleNamespace(media_root=str(tmp_path)))
    channel = StreamingFileChannel()
    relay = _RuntimeChannelStreamRelay.maybe_start(
        channel,
        _message(),
        FakeTaskRuntime(),
        config,
    )

    assert relay is not None

    await relay.emit(TextDeltaEvent(text="done"))
    await relay.emit(ArtifactEvent(**ref.to_dict()))
    await relay.close()

    assert channel.chunks == ["done"]
    assert channel.files == [("c1", "report.pptx")]
    assert channel.sent == []


@pytest.mark.asyncio
async def test_direct_channel_turn_idle_timeout_sends_error_reply() -> None:
    class SlowTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            await asyncio.sleep(1.0)
            yield TextDeltaEvent(text="late")

    channel = _FakeChannel()
    config = SimpleNamespace(
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=0.01,
    )

    await _run_turn_batch_path(
        channel,
        SlowTurnRunner(),
        _message(),
        "agent:main:channel-timeout",
        _tool_ctx(),
        _FakeEventBridge(),
        None,
        config,
    )

    assert channel.sent
    assert channel.sent[-1].content == "The task timed out before it could finish."
    assert "Stream idle" not in channel.sent[-1].content


@pytest.mark.asyncio
async def test_direct_channel_turn_honors_final_only_stream_policy() -> None:
    class FinalOnlyStreamingChannel(_FakeChannel):
        stream_update_strategy = "final_only"

        def __init__(self) -> None:
            super().__init__()
            self.streamed = False

        async def send_streaming(self, chunks):
            self.streamed = True
            text = ""
            async for chunk in chunks:
                text += chunk
            self.sent.append(OutgoingMessage(content=text))

    class FakeTurnRunner:
        async def run(self, message: str, session_key: str, **kwargs):
            yield TextDeltaEvent(text="final only")
            yield DoneEvent()

    channel = FinalOnlyStreamingChannel()
    config = SimpleNamespace(
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_with_streaming(
        channel,
        FakeTurnRunner(),
        _message(),
        "agent:main:final-only",
        _FakeEventBridge(),
        None,
        config,
    )

    assert channel.streamed is False
    assert channel.sent[-1].content == "final only"


@pytest.mark.asyncio
async def test_channel_batch_turn_uses_agent_registry_model() -> None:
    class RecordingTurnRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def run(self, message: str, session_key: str, **kwargs):
            self.calls.append(kwargs)
            yield DoneEvent()

    runner = RecordingTurnRunner()
    config = GatewayConfig(
        agents=[AgentEntryConfig(id="ops", model="agent/default")],
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_batch_path(
        _FakeChannel(),
        runner,
        _message(),
        "agent:ops:channel-test",
        _tool_ctx("ops"),
        _FakeEventBridge(),
        None,
        config,
    )

    assert runner.calls[0]["model"] == "agent/default"


@pytest.mark.asyncio
async def test_channel_ingest_resolves_adapter_bytes_to_engine_attachment() -> None:
    class ResolvingChannel(_FakeChannel):
        channel_id = "test"

        async def resolve_inbound_attachment(self, attachment: Attachment) -> Attachment:
            return Attachment(
                name=attachment.name,
                mime_type=attachment.mime_type,
                data=b"hello",
                size=5,
            )

    msg = IncomingMessage(
        sender_id="u1",
        channel_id="c1",
        content="read",
        attachments=[
            Attachment(
                name="note.txt",
                mime_type="text/plain",
                url="https://example.test/note.txt",
            )
        ],
    )

    result = await _ingest_channel_message_attachments(channel=ResolvingChannel(), msg=msg)

    assert result.text == "read"
    assert result.failures == []
    assert result.attachments == [
        {
            "name": "note.txt",
            "type": "text/plain",
            "data": base64.b64encode(b"hello").decode("ascii"),
            "_was_staged": True,
        }
    ]


@pytest.mark.asyncio
async def test_channel_ingest_hard_rejects_aggregate_attachment_cap() -> None:
    one_pdf = _exact_pdf(MAX_TOTAL_ATTACHMENT_BYTES // 3 + 1)
    assert len(one_pdf) < MAX_STAGED_PDF_BYTES

    class ResolvingChannel(_FakeChannel):
        channel_id = "test"

        async def resolve_inbound_attachment(self, attachment: Attachment) -> Attachment:
            return Attachment(
                name=attachment.name,
                mime_type="application/pdf",
                data=one_pdf,
                size=len(one_pdf),
            )

    msg = IncomingMessage(
        sender_id="u1",
        channel_id="c1",
        content="read",
        attachments=[
            Attachment(
                name=f"{index}.pdf",
                mime_type="application/pdf",
                url=f"https://example.test/{index}.pdf",
            )
            for index in range(3)
        ],
    )

    with pytest.raises(AttachmentTotalTooLargeError, match="total raw bytes"):
        await _ingest_channel_message_attachments(channel=ResolvingChannel(), msg=msg)


@pytest.mark.asyncio
async def test_channel_batch_turn_passes_normalized_attachments() -> None:
    class RecordingTurnRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def run(self, message: str, session_key: str, **kwargs):
            self.calls.append(kwargs)
            yield DoneEvent()

    runner = RecordingTurnRunner()
    attachment = {
        "type": "text/plain",
        "name": "note.txt",
        "data": base64.b64encode(b"hello").decode("ascii"),
    }

    await _run_turn_batch_path(
        _FakeChannel(),
        runner,
        _message(),
        "agent:main:channel-attachment",
        _tool_ctx(),
        _FakeEventBridge(),
        None,
        SimpleNamespace(
            agent_stream_heartbeat_interval_seconds=0.0,
            agent_stream_idle_timeout_seconds=1.0,
        ),
        [attachment],
    )

    assert runner.calls[0]["attachments"] == [attachment]


@pytest.mark.asyncio
async def test_debounce_channel_turn_rejects_aggregate_cap_before_runtime_start() -> None:
    one_pdf = _exact_pdf(MAX_TOTAL_ATTACHMENT_BYTES // 3 + 1)
    assert len(one_pdf) < MAX_STAGED_PDF_BYTES

    class ResolvingChannel(_FakeChannel):
        channel_id = "test"

        async def resolve_inbound_attachment(self, attachment: Attachment) -> Attachment:
            return Attachment(
                name=attachment.name,
                mime_type="application/pdf",
                data=one_pdf,
                size=len(one_pdf),
            )

    class FakeSessionManager:
        def __init__(self) -> None:
            self.delivery_contexts: list[tuple[str, str]] = []
            self.entries: list[dict[str, str]] = []

        async def get_or_create(self, key: str, **kwargs):
            return SimpleNamespace(session_key=key, **kwargs), True

        async def update(self, key: str, **kwargs) -> None:
            self.delivery_contexts.append((key, kwargs.get("last_channel") or ""))

        async def append_message(self, key: str, role: str, content: str):
            self.entries.append({"role": role, "content": content})
            return SimpleNamespace(content=content)

        async def read_transcript(self, key: str):
            return list(self.entries)

    class FakeTaskRuntime:
        def __init__(self) -> None:
            self.enqueue_calls: list[dict] = []

        async def enqueue(self, envelope, message: str, **kwargs):
            self.enqueue_calls.append({"message": message, **kwargs})
            return SimpleNamespace(task_id="t1")

    msg = IncomingMessage(
        sender_id="u1",
        channel_id="c1",
        content="read",
        attachments=[
            Attachment(
                name=f"{index}.pdf",
                mime_type="application/pdf",
                url=f"https://example.test/{index}.pdf",
            )
            for index in range(3)
        ],
    )
    runtime = FakeTaskRuntime()
    manager = FakeSessionManager()

    with pytest.raises(AttachmentTotalTooLargeError):
        await _dispatch_combined_message_after_debounce(
            ResolvingChannel(),
            SimpleNamespace(message=msg, raw_content="read", coalesced_count=1),
            SimpleNamespace(),
            manager,
            "agent:main:matrix:direct:u1",
            "matrix",
            runtime,
            SimpleNamespace(),
        )

    assert runtime.enqueue_calls == []
    assert manager.entries == []


@pytest.mark.asyncio
async def test_channel_streaming_turn_uses_agent_registry_model() -> None:
    class StreamingChannel(_FakeChannel):
        async def send_streaming(self, chunks, **kwargs):
            async for _ in chunks:
                pass

    class RecordingTurnRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def run(self, message: str, session_key: str, **kwargs):
            self.calls.append(kwargs)
            yield DoneEvent()

    runner = RecordingTurnRunner()
    config = GatewayConfig(
        agents=[AgentEntryConfig(id="ops", model="agent/default")],
        agent_stream_heartbeat_interval_seconds=0.0,
        agent_stream_idle_timeout_seconds=1.0,
    )

    await _run_turn_with_streaming(
        StreamingChannel(),
        runner,
        _message(),
        "agent:ops:channel-test",
        _FakeEventBridge(),
        None,
        config,
    )

    assert runner.calls[0]["model"] == "agent/default"


@pytest.mark.asyncio
async def test_channel_streaming_turn_passes_normalized_attachments() -> None:
    class StreamingChannel(_FakeChannel):
        async def send_streaming(self, chunks, **kwargs):
            async for _ in chunks:
                pass

    class RecordingTurnRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def run(self, message: str, session_key: str, **kwargs):
            self.calls.append(kwargs)
            yield DoneEvent()

    runner = RecordingTurnRunner()
    attachment = {
        "type": "text/plain",
        "name": "note.txt",
        "data": base64.b64encode(b"hello").decode("ascii"),
    }

    await _run_turn_with_streaming(
        StreamingChannel(),
        runner,
        _message(),
        "agent:main:channel-stream-attachment",
        _FakeEventBridge(),
        None,
        SimpleNamespace(
            agent_stream_heartbeat_interval_seconds=0.0,
            agent_stream_idle_timeout_seconds=1.0,
        ),
        attachments=[attachment],
    )

    assert runner.calls[0]["attachments"] == [attachment]


@pytest.mark.asyncio
async def test_debounce_channel_turn_honors_attachment_persistence_config(tmp_path) -> None:
    class RecordingLock:
        def __init__(self) -> None:
            self.in_lock = False

        def locked(self) -> bool:
            return self.in_lock

        async def __aenter__(self):
            self.in_lock = True

        async def __aexit__(self, exc_type, exc, tb) -> None:
            self.in_lock = False

    lock = RecordingLock()

    class ResolvingChannel(_FakeChannel):
        channel_id = "test"

        async def resolve_inbound_attachment(self, attachment: Attachment) -> Attachment:
            assert lock.in_lock is False
            return Attachment(
                name=attachment.name,
                mime_type=attachment.mime_type,
                data=b"%PDF-1.4\nbody\n",
            )

    class FakeSessionManager:
        def __init__(self) -> None:
            self.entries: list[dict[str, str]] = []

        async def get_or_create(self, key: str, **kwargs):
            return SimpleNamespace(session_key=key, **kwargs), True

        async def update(self, key: str, **kwargs) -> None:
            pass

        async def append_message(self, key: str, role: str, content: str):
            entry = {"role": role, "content": content}
            self.entries.append(entry)
            return SimpleNamespace(content=content)

        async def read_transcript(self, key: str):
            return list(self.entries)

    class FakeTaskRuntime:
        def __init__(self) -> None:
            self.enqueue_calls: list[dict] = []

        async def enqueue(self, envelope, message: str, **kwargs):
            self.enqueue_calls.append({"message": message, **kwargs})
            return SimpleNamespace(task_id="t1")

        async def wait(self, task_id: str):
            return SimpleNamespace(status="succeeded")

    class FakeTurnRunner:
        def _get_session_lock(self, key: str):
            return lock

    msg = IncomingMessage(
        sender_id="u1",
        channel_id="c1",
        content="read this",
        attachments=[Attachment(name="doc.pdf", mime_type="application/pdf", url="mxc://doc")],
    )
    runtime = FakeTaskRuntime()
    session_manager = FakeSessionManager()
    config = SimpleNamespace(
        attachments=SimpleNamespace(
            persist_transcripts=False,
            media_root=str(tmp_path),
            transcript_disk_budget_bytes=1024,
        )
    )

    await _dispatch_combined_message_after_debounce(
        ResolvingChannel(),
        SimpleNamespace(message=msg, raw_content="read this", coalesced_count=1),
        FakeTurnRunner(),
        session_manager,
        "agent:main:matrix:direct:u1",
        "matrix",
        runtime,
        config,
    )

    persisted = json.loads(session_manager.entries[-1]["content"])
    assert persisted["attachments"][0] == {
        "name": "doc.pdf",
        "mime": "application/pdf",
        "size": len(b"%PDF-1.4\nbody\n"),
        "missing_reason": "attachment persistence disabled",
    }
    assert "sha256_ref" not in persisted["attachments"][0]
    assert not (tmp_path / "transcripts").exists()
    assert runtime.enqueue_calls[0]["attachments"][0]["_was_staged"] is True


@pytest.mark.asyncio
async def test_runtime_reply_delivers_transcript_artifact_with_adapter_upload(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"\x89PNG\r\n\x1a\nimage bytes",
        session_id="session-1",
        session_key="agent:main:feishu:direct:u1",
        name="思考快与慢_信息图.png",
        mime="image/png",
        source="publish_artifact",
    )

    class FileUploadingChannel(_FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.files: list[tuple[str, str]] = []

        async def send_file(self, chat_id: str, file_path: str) -> None:
            assert Path(file_path).is_file()
            self.files.append((chat_id, Path(file_path).name))

    class FakeTaskRuntime:
        async def wait(self, task_id: str):
            return SimpleNamespace(status="succeeded")

    class FakeSessionManager:
        async def read_transcript(self, key: str):
            return [
                {"role": "user", "content": "create image"},
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "text": "做好了，点击上方按钮下载。",
                            "artifacts": [ref.to_dict()],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]

    channel = FileUploadingChannel()
    config = SimpleNamespace(attachments=SimpleNamespace(media_root=str(tmp_path)))

    await _deliver_runtime_channel_reply(
        channel=channel,
        task_runtime=FakeTaskRuntime(),
        session_manager=FakeSessionManager(),
        session_key="agent:main:feishu:direct:u1",
        task_id="task-1",
        route_envelope=SimpleNamespace(reply_target=None),
        inbound=_message(),
        transcript_watermark=1,
        config=config,
    )

    assert channel.sent[-1].content == "做好了，点击上方按钮下载。"
    assert channel.files == [("c1", "思考快与慢_信息图.png")]


@pytest.mark.asyncio
async def test_runtime_reply_delivers_file_artifact_with_adapter_upload(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    ref = store.publish_bytes(
        b"%PDF-1.4\nreport",
        session_id="session-1",
        session_key="agent:main:feishu:direct:u1",
        name="report.pdf",
        mime="application/pdf",
        source="publish_artifact",
    )

    class FileUploadingChannel(_FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.files: list[tuple[str, str]] = []

        async def send_file(self, chat_id: str, file_path: str) -> None:
            assert Path(file_path).is_file()
            self.files.append((chat_id, Path(file_path).name))

    class FakeTaskRuntime:
        async def wait(self, task_id: str):
            return SimpleNamespace(status="succeeded")

    class FakeSessionManager:
        async def read_transcript(self, key: str):
            return [
                {"role": "user", "content": "make report"},
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "text": "报告已生成。",
                            "artifacts": [ref.to_dict()],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]

    channel = FileUploadingChannel()
    config = SimpleNamespace(attachments=SimpleNamespace(media_root=str(tmp_path)))

    await _deliver_runtime_channel_reply(
        channel=channel,
        task_runtime=FakeTaskRuntime(),
        session_manager=FakeSessionManager(),
        session_key="agent:main:feishu:direct:u1",
        task_id="task-1",
        route_envelope=SimpleNamespace(reply_target=None),
        inbound=_message(),
        transcript_watermark=1,
        config=config,
    )

    assert channel.sent[-1].content == "报告已生成。"
    assert channel.files == [("c1", "report.pdf")]
