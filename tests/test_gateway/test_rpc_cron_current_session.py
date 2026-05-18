import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.gateway import rpc_cron
from opensquilla.gateway.rpc import RpcContext
from opensquilla.gateway.rpc_cron import (
    _handle_cron_add,
    _handle_cron_subscribe,
    _handle_cron_unsubscribe,
    _handle_cron_update,
)
from opensquilla.scheduler.delivery import DeliveryChain
from opensquilla.scheduler.handlers import _resolve_session_key, make_agent_run_handler
from opensquilla.scheduler.payloads import AGENT_TURN_KIND, SYSTEM_EVENT_KIND
from opensquilla.scheduler.rpc_payload import (
    build_cron_payload,
    resolve_origin_session_key,
    resolve_session_target,
    resolve_target_session_key,
)
from opensquilla.scheduler.types import CronJob, DeliveryConfig, DeliveryMode, SessionTarget

SESSION_KEY = "agent:main:webchat:abc123"
CRON_SESSION_KEY = "cron:drink:run:def456"


class _FakeScheduler:
    def __init__(self, job: CronJob | None = None) -> None:
        self.added = None
        self.updated = None
        self.job = job

    async def add_job(self, **kwargs) -> CronJob:
        self.added = kwargs
        return CronJob(
            id="drink",
            name=kwargs["name"],
            cron_expr=kwargs["schedule_raw"],
            schedule_raw=kwargs["schedule_raw"],
            handler_key=kwargs["handler_key"],
            payload=kwargs["payload"],
            session_target=kwargs["session_target"],
            session_key=kwargs["session_key"],
            origin_session_key=kwargs["origin_session_key"],
            delivery=kwargs.get("delivery") or DeliveryConfig(),
            tool_policy=kwargs.get("tool_policy") or {},
        )

    async def update_job(self, job_id, **patch) -> CronJob:
        self.updated = patch
        if self.job is None:
            return CronJob(id=job_id, **patch)
        for key, value in patch.items():
            setattr(self.job, key, value)
        return self.job

    async def get_job(self, job_id) -> CronJob | None:
        if self.job is not None and self.job.id == job_id:
            return self.job
        return None


class _FakeSessionManager:
    def __init__(self) -> None:
        self.created = []
        self.rows = {}

    async def get_or_create(self, **kwargs):
        self.created.append(kwargs)
        return kwargs

    async def append_message(self, session_key, role, content):
        row = {"role": role, "content": content}
        self.rows.setdefault(session_key, []).append(row)
        return SimpleNamespace(role=role, content=content)

    async def read_transcript(self, session_key):
        return list(self.rows.get(session_key, []))


class _FakeTurnRunner:
    def __init__(self, session_manager: _FakeSessionManager) -> None:
        self.session_manager = session_manager
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)

        async def events():
            await self.session_manager.append_message(
                kwargs["session_key"],
                role="assistant",
                content="drink logged",
            )
            yield SimpleNamespace(kind="message", text="drink logged")
            yield SimpleNamespace(kind="done")

        return events()


class _FakeSubscriptionManager:
    def __init__(self) -> None:
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe_topic(self, conn_id, topic) -> None:
        self.subscriptions.append((conn_id, topic))

    def unsubscribe_topic(self, conn_id, topic) -> None:
        self.unsubscriptions.append((conn_id, topic))


def test_rpc_current_session_params_bind_target_and_origin_session() -> None:
    params = {
        "payloadKind": AGENT_TURN_KIND,
        "sessionTarget": "current",
        "sessionKey": SESSION_KEY,
        "text": "drink water",
        "agentId": "main",
    }

    session_target = resolve_session_target(params)
    kind, payload = build_cron_payload(params, session_target)

    assert session_target == SessionTarget.CURRENT
    assert resolve_target_session_key(params, session_target) == SESSION_KEY
    assert resolve_origin_session_key(params, session_target) == SESSION_KEY
    assert kind == AGENT_TURN_KIND
    assert payload == {
        "kind": AGENT_TURN_KIND,
        "task": "drink water",
        "agent_id": "main",
    }


@pytest.mark.asyncio
async def test_rpc_create_current_session_job_passes_session_binding_to_scheduler() -> None:
    scheduler = _FakeScheduler()

    result = await _handle_cron_add(
        {
            "name": "Drink",
            "expression": "*/5 * * * *",
            "payloadKind": AGENT_TURN_KIND,
            "sessionTarget": "current",
            "sessionKey": SESSION_KEY,
            "originSessionKey": SESSION_KEY,
            "text": "drink water",
            "agentId": "main",
        },
        RpcContext(conn_id="test", cron_scheduler=scheduler),
    )

    assert scheduler.added["session_target"] == SessionTarget.CURRENT
    assert scheduler.added["session_key"] == SESSION_KEY
    assert scheduler.added["origin_session_key"] == SESSION_KEY
    assert scheduler.added["handler_key"] == "agent_run"
    assert result["sessionTarget"] == "current"
    assert result["targetSessionKey"] == SESSION_KEY
    assert result["originSessionKey"] == SESSION_KEY


@pytest.mark.asyncio
async def test_rpc_create_job_round_trips_tool_policy() -> None:
    scheduler = _FakeScheduler()

    result = await _handle_cron_add(
        {
            "name": "Drink",
            "expression": "*/5 * * * *",
            "payloadKind": AGENT_TURN_KIND,
            "text": "drink water",
            "agentId": "main",
            "toolPolicy": {
                "profile": "minimal",
                "alsoAllow": ["memory_search"],
                "deny": ["web_fetch"],
            },
        },
        RpcContext(conn_id="test", cron_scheduler=scheduler),
    )

    assert scheduler.added["tool_policy"] == {
        "profile": "minimal",
        "also_allow": ["memory_search"],
        "deny": ["web_fetch"],
    }
    assert result["toolPolicy"] == {
        "profile": "minimal",
        "allow": [],
        "alsoAllow": ["memory_search"],
        "deny": ["web_fetch"],
    }


@pytest.mark.asyncio
async def test_rpc_update_current_session_job_preserves_existing_binding() -> None:
    current_job = CronJob(
        id="drink",
        name="Drink",
        handler_key="agent_run",
        payload={"kind": AGENT_TURN_KIND, "task": "drink water", "agent_id": "main"},
        session_target=SessionTarget.CURRENT,
        session_key=SESSION_KEY,
        origin_session_key=SESSION_KEY,
    )
    scheduler = _FakeScheduler(job=current_job)

    result = await _handle_cron_update(
        {
            "id": "drink",
            "text": "drink more water",
        },
        RpcContext(conn_id="test", cron_scheduler=scheduler),
    )

    assert scheduler.updated["session_target"] == SessionTarget.CURRENT
    assert scheduler.updated["session_key"] == SESSION_KEY
    assert scheduler.updated["origin_session_key"] == SESSION_KEY
    assert result["sessionTarget"] == "current"
    assert result["targetSessionKey"] == SESSION_KEY
    assert result["originSessionKey"] == SESSION_KEY
    assert result["prompt"] == "drink more water"


@pytest.mark.asyncio
async def test_rpc_update_job_round_trips_tool_policy() -> None:
    current_job = CronJob(
        id="drink",
        name="Drink",
        handler_key="agent_run",
        payload={"kind": AGENT_TURN_KIND, "task": "drink water", "agent_id": "main"},
    )
    scheduler = _FakeScheduler(job=current_job)

    result = await _handle_cron_update(
        {
            "id": "drink",
            "toolPolicy": {
                "profile": "minimal",
                "alsoAllow": ["memory_search"],
                "deny": ["web_fetch"],
            },
        },
        RpcContext(conn_id="test", cron_scheduler=scheduler),
    )

    assert scheduler.updated["tool_policy"] == {
        "profile": "minimal",
        "also_allow": ["memory_search"],
        "deny": ["web_fetch"],
    }
    assert current_job.tool_policy == scheduler.updated["tool_policy"]
    assert result["toolPolicy"]["alsoAllow"] == ["memory_search"]
    assert result["toolPolicy"]["deny"] == ["web_fetch"]


def test_rpc_keeps_system_event_main_only() -> None:
    params = {
        "payloadKind": SYSTEM_EVENT_KIND,
        "sessionTarget": "current",
        "sessionKey": SESSION_KEY,
        "text": "drink water",
    }

    with pytest.raises(ValueError, match="system_event.*main"):
        build_cron_payload(params, SessionTarget.CURRENT)


def test_rpc_rejects_agent_turn_on_main_session() -> None:
    params = {
        "payloadKind": AGENT_TURN_KIND,
        "sessionTarget": "main",
        "text": "drink water",
    }

    with pytest.raises(ValueError, match="agent_turn.*main"):
        build_cron_payload(params, SessionTarget.MAIN)


def test_gateway_rpc_cron_delegates_wire_payloads_to_scheduler_boundary() -> None:
    source = Path(rpc_cron.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }

    assert ("opensquilla.scheduler.rpc_payload", "cron_job_to_wire") in imports
    assert ("opensquilla.scheduler.rpc_payload", "manual_run_to_wire") in imports
    assert ("opensquilla.scheduler.rpc_payload", "cron_run_to_wire") in imports
    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_job_to_wire" not in top_level_functions
    assert "_manual_run_to_wire" not in top_level_functions
    assert "_tool_policy_to_wire" not in top_level_functions


def test_gateway_rpc_cron_delegates_request_assembly_to_scheduler_boundary() -> None:
    source = Path(rpc_cron.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert {
        ("opensquilla.scheduler.rpc_payload", "build_cron_add_job_kwargs"),
        ("opensquilla.scheduler.rpc_payload", "build_cron_update_patch"),
        ("opensquilla.scheduler.rpc_payload", "reply_target_snapshot_from_envelope"),
    }.issubset(imports)
    assert ("opensquilla.scheduler.types", "DeliveryConfig") not in imports
    assert ("opensquilla.scheduler.rpc_payload", "build_cron_payload") not in imports
    assert "DeliveryConfig" not in call_names


@pytest.mark.asyncio
async def test_rpc_cron_subscribe_and_unsubscribe_topic_responses() -> None:
    subscription_manager = _FakeSubscriptionManager()
    ctx = RpcContext(conn_id="conn-1", subscription_manager=subscription_manager)

    subscribe_result = await _handle_cron_subscribe({"jobId": "drink"}, ctx)
    unsubscribe_result = await _handle_cron_unsubscribe({}, ctx)

    assert subscribe_result == {"ok": True, "topic": "cron:drink"}
    assert unsubscribe_result == {"ok": True, "topic": "cron:*"}
    assert subscription_manager.subscriptions == [("conn-1", "cron:drink")]
    assert subscription_manager.unsubscriptions == [("conn-1", "cron:*")]


def test_gateway_rpc_cron_subscription_envelopes_delegate_to_scheduler_boundary() -> None:
    source = Path(rpc_cron.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    handlers = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in {"_handle_cron_subscribe", "_handle_cron_unsubscribe"}
    }
    handler_names = {
        node.id
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    helper_names = {
        "cron_subscription_error_response",
        "cron_subscription_response",
    }

    assert {
        ("opensquilla.scheduler.rpc_payload", helper_name)
        for helper_name in helper_names
    }.issubset(imports)
    assert helper_names.issubset(handler_names)
    assert ("ok", "error") not in direct_key_sets
    assert ("ok", "topic") not in direct_key_sets


def test_scheduler_current_session_resolves_bound_session_key() -> None:
    job = CronJob(
        id="drink",
        name="Drink",
        session_target=SessionTarget.CURRENT,
        session_key=SESSION_KEY,
    )

    assert _resolve_session_key(job) == SESSION_KEY


def test_scheduler_current_session_falls_back_to_origin_session_key() -> None:
    job = CronJob(
        id="drink",
        name="Drink",
        session_target=SessionTarget.CURRENT,
        origin_session_key=SESSION_KEY,
    )

    assert _resolve_session_key(job) == SESSION_KEY


def test_scheduler_current_session_requires_a_bound_key() -> None:
    job = CronJob(id="drink", name="Drink", session_target=SessionTarget.CURRENT)

    with pytest.raises(ValueError, match="CURRENT target requires"):
        _resolve_session_key(job)


def test_delivery_skips_same_session_forward_for_current_session_jobs() -> None:
    calls = []

    async def forwarder(**kwargs) -> None:
        calls.append(kwargs)

    job = CronJob(
        id="drink",
        name="Drink",
        session_target=SessionTarget.CURRENT,
        session_key=SESSION_KEY,
        origin_session_key=SESSION_KEY,
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    status = asyncio.run(chain._forward_to_session(job, "done", SESSION_KEY))

    assert status == "skipped"
    assert calls == []


def test_delivery_forwards_isolated_job_results_to_origin_session() -> None:
    calls = []

    async def forwarder(**kwargs) -> None:
        calls.append(kwargs)

    job = CronJob(
        id="drink",
        name="Drink",
        session_target=SessionTarget.ISOLATED,
        session_key=CRON_SESSION_KEY,
        origin_session_key=SESSION_KEY,
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    status = asyncio.run(chain._forward_to_session(job, "done", CRON_SESSION_KEY))

    assert status == "delivered"
    assert calls == [
        {
            "origin_session_key": SESSION_KEY,
            "text": "done",
            "provenance": {
                "kind": "cron",
                "source_session_key": CRON_SESSION_KEY,
                "source_tool": "cron:drink",
            },
        }
    ]
    assert job.delivery.mode == DeliveryMode.NONE


@pytest.mark.asyncio
async def test_current_session_agent_run_uses_bound_session_transcript_without_forwarding() -> None:
    session_manager = _FakeSessionManager()
    turn_runner = _FakeTurnRunner(session_manager)
    forward_calls = []

    async def forwarder(**kwargs) -> None:
        forward_calls.append(kwargs)

    job = CronJob(
        id="drink",
        name="Drink",
        handler_key="agent_run",
        payload={"kind": AGENT_TURN_KIND, "task": "drink water", "agent_id": "main"},
        session_target=SessionTarget.CURRENT,
        session_key=SESSION_KEY,
        origin_session_key=SESSION_KEY,
        tool_policy={
            "profile": "minimal",
            "also_allow": ["memory_search", "exec_command"],
            "deny": ["web_fetch"],
        },
    )
    handler = make_agent_run_handler(
        DeliveryChain(session_forwarder=forwarder),
        turn_runner_ref=lambda: turn_runner,
        session_manager_ref=lambda: session_manager,
    )

    result = await handler(job)

    assert result.session_key == SESSION_KEY
    assert result.summary == "drink logged"
    assert result.delivery_status == "skipped|ws:skipped|fwd:skipped"
    assert session_manager.created == [
        {
            "session_key": SESSION_KEY,
            "agent_id": "main",
            "display_name": "Cron: Drink",
        }
    ]
    assert turn_runner.calls[0]["session_key"] == SESSION_KEY
    assert turn_runner.calls[0]["run_kind"] == "cron_turn"
    assert turn_runner.calls[0]["input_provenance"] == {
        "kind": "cron_job",
        "job_id": "drink",
    }
    tool_context = turn_runner.calls[0]["tool_context"]
    assert tool_context.allowed_tools == {"session_status", "memory_search"}
    assert "exec_command" in tool_context.denied_tools
    assert "web_fetch" in tool_context.denied_tools
    assert await session_manager.read_transcript(SESSION_KEY) == [
        {"role": "user", "content": "drink water"},
        {"role": "assistant", "content": "drink logged"},
    ]
    assert forward_calls == []
