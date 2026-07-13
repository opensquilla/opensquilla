from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from opensquilla.engine import Agent
from opensquilla.engine.guardian_session import (
    READ_ONLY_GUARDIAN_TOOLS,
    GuardianReviewSessionManager,
    build_read_only_guardian_registry,
)
from opensquilla.engine.types import AgentConfig, TextDeltaEvent
from opensquilla.provider.types import Message
from opensquilla.sandbox.integration import active_file_system_profile
from opensquilla.sandbox.permissions import (
    FileSystemAccess,
    FileSystemPermissionProfile,
)
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolSpec, current_tool_context


class _Provider:
    provider_name = "guardian-session-test"


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
    assert profile.resolve(Path("/tmp/guardian-probe")) is FileSystemAccess.READ
    token = current_tool_context.set(manager._context)
    try:
        assert active_file_system_profile(tmp_path) is profile
    finally:
        current_tool_context.reset(token)


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
