from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from opensquilla.engine import Agent
from opensquilla.engine.guardian_prompt import guardian_output_schema
from opensquilla.engine.guardian_session import (
    READ_ONLY_GUARDIAN_TOOLS,
    GuardianReviewSessionManager,
    build_read_only_guardian_registry,
)
from opensquilla.engine.types import AgentConfig, TextDeltaEvent
from opensquilla.provider.types import (
    ChatConfig,
    Message,
    StreamEvent,
    ToolDefinition,
)
from opensquilla.provider.types import (
    DoneEvent as ProviderDoneEvent,
)
from opensquilla.provider.types import (
    TextDeltaEvent as ProviderTextDeltaEvent,
)
from opensquilla.sandbox.integration import active_file_system_profile
from opensquilla.sandbox.permissions import (
    FileSystemAccess,
    FileSystemPermissionProfile,
)
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolSpec, current_tool_context


class _Provider:
    provider_name = "guardian-session-test"


class _RecordingProvider:
    provider_name = "guardian-session-recording-test"

    def __init__(self) -> None:
        self.calls = 0
        self.tools: list[list[ToolDefinition] | None] = []
        self.configs: list[ChatConfig | None] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        del messages
        self.calls += 1
        self.tools.append(tools)
        self.configs.append(config)

        async def _stream() -> AsyncIterator[StreamEvent]:
            yield ProviderTextDeltaEvent(text='{"outcome":"allow"}')
            yield ProviderDoneEvent(stop_reason="stop", input_tokens=1, output_tokens=1)

        return _stream()


def _registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def _handler(**kwargs: Any) -> str:
        return str(kwargs)

    for name in (*READ_ONLY_GUARDIAN_TOOLS, "write_file", "exec_command"):
        registry.register(ToolSpec(name=name, description=name, parameters={}), _handler)
    return registry


class _FakeAgent:
    def __init__(
        self,
        history: list[Message],
        *,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.history = list(history)
        self.prompts: list[str] = []
        self.started = started
        self.release = release

    def set_history(self, messages: list[Message]) -> None:
        self.history = list(messages)

    def history_snapshot(self) -> list[Message]:
        return list(self.history)

    async def run_turn(self, message: str) -> AsyncIterator[TextDeltaEvent]:
        self.prompts.append(message)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        answer = (
            '{"risk_level":"low","user_authorization":"high",'
            '"outcome":"allow","rationale":"ok"}'
        )
        self.history.extend(
            [Message(role="user", content=message), Message(role="assistant", content=answer)]
        )
        yield TextDeltaEvent(text=answer, presentation="answer")


def test_read_only_registry_contains_exactly_codex_guardian_tools() -> None:
    registry = build_read_only_guardian_registry(_registry())

    assert frozenset(registry.list_names()) == READ_ONLY_GUARDIAN_TOOLS
    assert "write_file" not in registry.list_names()
    assert "exec_command" not in registry.list_names()


def test_read_only_registry_fails_closed_when_a_required_tool_is_missing() -> None:
    registry = _registry()
    registry.unregister("git_log")

    with pytest.raises(ValueError, match="guardian_read_only_tools_missing:git_log"):
        build_read_only_guardian_registry(registry)


def test_guardian_context_installs_read_only_filesystem_profile(tmp_path: Path) -> None:
    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
    )

    profile = manager._context.sandbox_file_system_profile

    assert profile is not None
    assert profile.resolve(tmp_path / "repo.py") is FileSystemAccess.READ
    readable_root = profile.readable_roots[0]
    assert profile.resolve(readable_root / "guardian-probe") is FileSystemAccess.READ
    token = current_tool_context.set(manager._context)
    try:
        assert active_file_system_profile(tmp_path) is profile
    finally:
        current_tool_context.reset(token)


def test_guardian_config_uses_stable_policy_cache_and_codex_output_schema(
    tmp_path: Path,
) -> None:
    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(cache_mode="auto"),
    )

    assert manager._config.cache_mode == "auto"
    assert manager._config.cache_breakpoints == [
        {"text": manager._config.system_prompt, "cache": "true"}
    ]
    schema = guardian_output_schema()
    assert manager._config.output_json_schema == schema
    assert manager._config.output_json_schema_strict is False
    assert schema["required"] == ["outcome"]


def test_agent_rebuilds_guardian_session_when_review_config_changes(tmp_path: Path) -> None:
    config = AgentConfig(workspace_dir=str(tmp_path), model_id="model-a")
    agent = Agent(
        _Provider(),  # type: ignore[arg-type]
        config=config,
        tool_registry=_registry(),
    )

    first = agent._guardian_session_for_approval()
    agent.config.model_id = "model-b"
    second = agent._guardian_session_for_approval()

    assert first is not None
    assert second is not None
    assert second is not first


def test_guardian_read_only_profile_preserves_parent_denied_reads(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
        file_system_profile=FileSystemPermissionProfile.workspace(
            workspace=tmp_path,
            denied_read_roots=(secret,),
        ),
    )

    profile = manager._context.sandbox_file_system_profile

    assert profile.resolve(tmp_path / "repo.py") is FileSystemAccess.READ
    assert profile.resolve(secret / "token") is FileSystemAccess.DENY
    assert not any(
        entry.access is FileSystemAccess.WRITE for entry in profile.entries
    )


@pytest.mark.asyncio
async def test_sequential_reviews_reuse_one_committed_trunk(tmp_path: Path) -> None:
    agents: list[_FakeAgent] = []

    def factory(history: list[Message]) -> _FakeAgent:
        agent = _FakeAgent(history)
        agents.append(agent)
        return agent

    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
        agent_factory=factory,
    )

    await manager.review("first review")
    await manager.review("second review")

    assert len(agents) == 1
    assert agents[0].prompts == ["first review", "second review"]
    assert len(agents[0].history_snapshot()) == 4


@pytest.mark.asyncio
async def test_low_risk_review_uses_one_provider_call_with_structured_output(
    tmp_path: Path,
) -> None:
    provider = _RecordingProvider()
    manager = GuardianReviewSessionManager(
        provider,  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(cache_mode="auto"),
    )

    response = await manager.review("Review this narrow user-requested local write")

    assert response == '{"outcome":"allow"}'
    assert provider.calls == 1
    assert provider.tools[0] is not None
    assert {tool.name for tool in provider.tools[0] or []} == READ_ONLY_GUARDIAN_TOOLS
    assert provider.configs[0] is not None
    assert provider.configs[0].output_json_schema == guardian_output_schema()
    assert provider.configs[0].output_json_schema_strict is False


def test_prewarm_is_idempotent_and_first_review_reuses_trunk(tmp_path: Path) -> None:
    agents: list[_FakeAgent] = []

    def factory(history: list[Message]) -> _FakeAgent:
        agent = _FakeAgent(history)
        agents.append(agent)
        return agent

    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
        agent_factory=factory,
    )

    assert manager.prewarm() is True
    assert manager.prewarm() is False
    assert len(agents) == 1

    asyncio.run(manager.review("first review"))

    assert len(agents) == 1
    assert agents[0].prompts == ["first review"]


@pytest.mark.asyncio
async def test_main_agent_prewarms_guardian_before_turn_body(tmp_path: Path) -> None:
    agent = Agent(
        _Provider(),  # type: ignore[arg-type]
        config=AgentConfig(workspace_dir=str(tmp_path)),
        tool_registry=_registry(),
    )

    turn = agent.run_turn("hello")
    await anext(turn)
    manager = agent._guardian_review_session
    await turn.aclose()

    assert manager is not None
    assert manager._trunk is not None


@pytest.mark.asyncio
async def test_guardian_agent_does_not_recursively_prewarm(tmp_path: Path) -> None:
    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
    )
    assert manager.prewarm() is True
    guardian = manager._trunk
    assert isinstance(guardian, Agent)

    turn = guardian.run_turn("review")
    await anext(turn)
    await turn.aclose()

    assert guardian._guardian_review_session is None


@pytest.mark.asyncio
async def test_followup_review_uses_parent_transcript_delta_on_reused_trunk(
    tmp_path: Path,
) -> None:
    agents: list[_FakeAgent] = []

    def factory(history: list[Message]) -> _FakeAgent:
        agent = _FakeAgent(history)
        agents.append(agent)
        return agent

    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
        agent_factory=factory,
    )
    first = [Message(role="user", content="first request")]
    await manager.review_action(first, {"kind": "shell", "command": "pwd"})
    followup = [*first, Message(role="user", content="follow-up approval")]
    await manager.review_action(followup, {"kind": "shell", "command": "touch /tmp/x"})

    assert len(agents) == 1
    assert "TRANSCRIPT START" in agents[0].prompts[0]
    assert "TRANSCRIPT DELTA START" in agents[0].prompts[1]
    assert "follow-up approval" in agents[0].prompts[1]
    assert "first request" not in agents[0].prompts[1]


@pytest.mark.asyncio
async def test_invalid_review_does_not_commit_trunk_or_parent_cursor(
    tmp_path: Path,
) -> None:
    agents: list[_FakeAgent] = []

    def factory(history: list[Message]) -> _FakeAgent:
        agent = _FakeAgent(history)
        agents.append(agent)
        return agent

    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
        agent_factory=factory,
    )
    transcript = [Message(role="user", content="first request")]

    def reject_response(_response: str) -> None:
        raise ValueError("invalid review")

    with pytest.raises(ValueError, match="invalid review"):
        await manager.review_action(
            transcript,
            {"kind": "shell", "command": "pwd"},
            response_validator=reject_response,
        )
    await manager.review_action(
        transcript,
        {"kind": "shell", "command": "pwd"},
    )

    assert len(agents) == 2
    assert agents[1].history_snapshot()[0].content.startswith(
        "The following is the agent history whose request action"
    )
    assert "TRANSCRIPT START" in agents[1].prompts[0]
    assert "TRANSCRIPT DELTA START" not in agents[1].prompts[0]


@pytest.mark.asyncio
async def test_parallel_review_forks_last_committed_snapshot_without_mutating_trunk(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    agents: list[_FakeAgent] = []

    def factory(history: list[Message]) -> _FakeAgent:
        agent = _FakeAgent(
            history,
            started=started if not agents else None,
            release=release if not agents else None,
        )
        agents.append(agent)
        return agent

    manager = GuardianReviewSessionManager(
        _Provider(),  # type: ignore[arg-type]
        tool_registry=_registry(),
        workspace=tmp_path,
        parent_config=AgentConfig(),
        agent_factory=factory,
    )

    trunk_task = asyncio.create_task(manager.review("trunk review"))
    await started.wait()
    fork_result = await manager.review("parallel fork review")
    release.set()
    await trunk_task
    await manager.review("after trunk")

    assert "\"outcome\":\"allow\"" in fork_result
    assert len(agents) == 2
    assert agents[1].history_snapshot()[0].content == "parallel fork review"
    assert agents[0].prompts == ["trunk review", "after trunk"]
    assert all("parallel fork review" not in str(message.content) for message in agents[0].history)
