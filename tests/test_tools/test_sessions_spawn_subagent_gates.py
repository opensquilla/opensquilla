"""sessions_spawn enforces per-agent subagent policy gates from PR 4.

Covers four gates:
  - allow_agents (None=skip, []=self-only, ["*"]=any, list=exact)
  - max_children_per_session (None=skip; reject when active >= cap)
  - model fallback chain (explicit > target.subagents.model > caller's None)
  - enforce_disabled_agents flag (off=skip; on=reject enabled=False targets)
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from opensquilla.tools.builtin import sessions as sessions_tool
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@dataclass
class _StubGatewayConfig:
    agents_defaults: object | None = None

    class _Subagents:
        enforce_disabled_agents = False

    subagents = _Subagents()


class _ConfigurableConfig:
    """Standalone config object that can flip enforce_disabled_agents."""

    class _SubagentsBlock:
        def __init__(self, enforce: bool) -> None:
            self.enforce_disabled_agents = enforce

    def __init__(self, *, enforce_disabled: bool = False) -> None:
        self.subagents = self._SubagentsBlock(enforce_disabled)
        self.agents_defaults = None


class _StubSessionManager:
    """Minimal session manager: drives get_agent_config + list_sessions
    + get_current_session + create + append_message.
    """

    def __init__(
        self,
        agents: dict[str, dict],
        active_children_count: int = 0,
    ) -> None:
        self._agents = agents
        self._active_children = active_children_count
        self.created: list[dict] = []

    async def get_agent_config(self, agent_id: str) -> dict | None:
        return self._agents.get(agent_id)

    async def get_current_session(self):
        return None

    async def list_sessions(self, agent_id=None, status=None, limit=100, offset=0):
        # Return ``self._active_children`` rows that look like running children
        # of ``agent:caller:main``.
        return [
            {"spawned_by": "agent:caller:main", "status": "running"}
            for _ in range(self._active_children)
        ]

    async def create(self, **kwargs):
        self.created.append(kwargs)

    async def append_message(self, *args, **kwargs):
        return True


class _StubTaskRuntime:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    async def enqueue(self, envelope, message, mode="followup", run_kind="default"):
        self.enqueued.append(
            {"envelope": envelope, "message": message, "mode": mode, "run_kind": run_kind}
        )

        @dataclass
        class _Handle:
            task_id: str = "task-stub"

        return _Handle()


def _ctx(session_key: str = "agent:caller:main", agent_id: str = "caller") -> ToolContext:
    return ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        subagent_depth=0,
        agent_id=agent_id,
        session_key=session_key,
        task_id="task-parent",
    )


@pytest.fixture(autouse=True)
def _wire_stubs(request):
    # Default no-op config; tests overwrite as needed.
    sessions_tool.set_gateway_config(_ConfigurableConfig())
    sessions_tool.set_spawn_group_closer(None)

    yield

    sessions_tool.set_session_manager(None)
    sessions_tool.set_task_runtime(None)
    sessions_tool.set_gateway_config(None)
    sessions_tool.set_spawn_group_closer(None)


# ── allow_agents ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allow_agents_unset_permits_cross_agent_spawn() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {"id": "caller", "name": "Caller", "enabled": True},
            "worker": {"id": "worker", "name": "Worker", "enabled": True},
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        await sessions_tool.sessions_spawn(agent_id="worker", task="hi")
    finally:
        current_tool_context.reset(token)

    assert len(rt.enqueued) == 1


@pytest.mark.asyncio
async def test_allow_agents_self_only_blocks_other_target() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {
                "id": "caller",
                "enabled": True,
                "subagents": {"allow_agents": []},
            },
            "worker": {"id": "worker", "enabled": True},
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        with pytest.raises(Exception, match="Cross-agent spawn not allowed"):
            await sessions_tool.sessions_spawn(agent_id="worker", task="hi")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_allow_agents_self_only_permits_self_target() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {
                "id": "caller",
                "enabled": True,
                "subagents": {"allow_agents": []},
            },
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        await sessions_tool.sessions_spawn(agent_id="caller", task="hi")
    finally:
        current_tool_context.reset(token)
    assert len(rt.enqueued) == 1


@pytest.mark.asyncio
async def test_allow_agents_wildcard_permits_any() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {
                "id": "caller",
                "enabled": True,
                "subagents": {"allow_agents": ["*"]},
            },
            "worker": {"id": "worker", "enabled": True},
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        await sessions_tool.sessions_spawn(agent_id="worker", task="hi")
    finally:
        current_tool_context.reset(token)
    assert len(rt.enqueued) == 1


# ── max_children_per_session ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_children_rejects_when_at_cap() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {
                "id": "caller",
                "enabled": True,
                "subagents": {"max_children_per_session": 2},
            },
        },
        active_children_count=2,
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        with pytest.raises(Exception, match="Max active children"):
            await sessions_tool.sessions_spawn(task="hi")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_max_children_permits_below_cap() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {
                "id": "caller",
                "enabled": True,
                "subagents": {"max_children_per_session": 5},
            },
        },
        active_children_count=2,
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        await sessions_tool.sessions_spawn(task="hi")
    finally:
        current_tool_context.reset(token)
    assert len(rt.enqueued) == 1


# ── model fallback chain ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_fallback_uses_target_subagents_model() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {"id": "caller", "enabled": True},
            "worker": {
                "id": "worker",
                "enabled": True,
                "subagents": {"model": "haiku"},
            },
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        await sessions_tool.sessions_spawn(agent_id="worker", task="hi")
    finally:
        current_tool_context.reset(token)

    assert mgr.created
    assert mgr.created[0]["model"] == "haiku"


@pytest.mark.asyncio
async def test_explicit_model_wins_over_fallback() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {"id": "caller", "enabled": True},
            "worker": {
                "id": "worker",
                "enabled": True,
                "subagents": {"model": "haiku"},
            },
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)

    token = current_tool_context.set(_ctx())
    try:
        await sessions_tool.sessions_spawn(agent_id="worker", task="hi", model="opus")
    finally:
        current_tool_context.reset(token)

    assert mgr.created[0]["model"] == "opus"


# ── enforce_disabled_agents flag ────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_target_allowed_when_flag_off() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {"id": "caller", "enabled": True},
            "worker": {"id": "worker", "enabled": False},
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)
    sessions_tool.set_gateway_config(_ConfigurableConfig(enforce_disabled=False))

    token = current_tool_context.set(_ctx())
    try:
        await sessions_tool.sessions_spawn(agent_id="worker", task="hi")
    finally:
        current_tool_context.reset(token)
    assert len(rt.enqueued) == 1


@pytest.mark.asyncio
async def test_disabled_target_rejected_when_flag_on() -> None:
    mgr = _StubSessionManager(
        {
            "caller": {"id": "caller", "enabled": True},
            "worker": {"id": "worker", "enabled": False},
        }
    )
    rt = _StubTaskRuntime()
    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(rt)
    sessions_tool.set_gateway_config(_ConfigurableConfig(enforce_disabled=True))

    token = current_tool_context.set(_ctx())
    try:
        with pytest.raises(Exception, match="is disabled"):
            await sessions_tool.sessions_spawn(agent_id="worker", task="hi")
    finally:
        current_tool_context.reset(token)
