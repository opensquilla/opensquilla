from __future__ import annotations

from types import SimpleNamespace

from opensquilla.channels.types import IncomingMessage
from opensquilla.gateway import routing as gateway_routing
from opensquilla.gateway.routing import (
    build_channel_route_envelope,
    build_cli_route_envelope,
    build_cron_route_envelope,
    build_subagent_route_envelope,
    build_web_route_envelope,
    tool_context_from_envelope,
)
from opensquilla.scheduler import routing as scheduler_routing
from opensquilla.session import subagent_routing as session_routing
from opensquilla.tools.policy import ToolSurfaceCapabilities, resolve_runtime_tool_surface
from opensquilla.tools.types import CallerKind, InteractionMode


def test_route_envelopes_assign_expected_interaction_modes() -> None:
    channel_msg = IncomingMessage(sender_id="u1", channel_id="c1", content="hi")
    cron_job = SimpleNamespace(id="job-1", name="demo")

    cases = [
        (
            build_cli_route_envelope(session_key="agent:main:cli"),
            CallerKind.CLI,
            InteractionMode.INTERACTIVE,
        ),
        (
            build_cli_route_envelope(
                session_key="agent:main:auto",
                interaction_mode=InteractionMode.UNATTENDED,
            ),
            CallerKind.CLI,
            InteractionMode.UNATTENDED,
        ),
        (
            build_web_route_envelope(session_key="agent:main:web"),
            CallerKind.WEB,
            InteractionMode.INTERACTIVE,
        ),
        (
            build_channel_route_envelope(
                channel_msg,
                session_key="telegram:dm:u1",
                session_prefix="telegram",
            ),
            CallerKind.CHANNEL,
            InteractionMode.UNATTENDED,
        ),
        (
            build_cron_route_envelope(cron_job, session_key="cron:job-1"),
            CallerKind.CRON,
            InteractionMode.UNATTENDED,
        ),
        (
            build_subagent_route_envelope(
                session_key="subagent:parent:child",
                parent_session_key="agent:main:parent",
            ),
            CallerKind.SUBAGENT,
            InteractionMode.UNATTENDED,
        ),
    ]

    for envelope, expected_kind, expected_mode in cases:
        ctx = tool_context_from_envelope(envelope)
        assert ctx.caller_kind is expected_kind
        assert ctx.interaction_mode is expected_mode


def test_unattended_cli_denies_runtime_dependent_tools_but_keeps_session_reads() -> None:
    envelope = build_cli_route_envelope(
        session_key="agent:main:auto",
        interaction_mode=InteractionMode.UNATTENDED,
    )

    ctx = resolve_runtime_tool_surface(
        tool_context_from_envelope(envelope, is_owner=True),
        capabilities=ToolSurfaceCapabilities(session_manager=True),
    )

    assert "sessions_spawn" in ctx.denied_tools
    assert "gateway" in ctx.denied_tools
    assert "sessions_list" not in ctx.denied_tools
    assert "sessions_history" not in ctx.denied_tools
    assert "session_status" not in ctx.denied_tools


def test_tool_context_from_route_envelope_uses_gateway_config_for_channel_owner_and_workspace(
    tmp_path,
) -> None:
    channel_msg = IncomingMessage(sender_id="u1", channel_id="c1", content="hi")
    envelope = build_channel_route_envelope(
        channel_msg,
        session_key="agent:main:feishu:u1",
        session_prefix="feishu",
        agent_id="main",
    )
    helper = getattr(gateway_routing, "tool_context_from_route_envelope", None)

    assert callable(helper)

    ctx = helper(
        envelope,
        SimpleNamespace(
            channel_admin_senders={"feishu": ("u1",)},
            workspace_dir=str(tmp_path),
            workspace_strict="legacy-truthy-value",
        ),
        task_id="task-1",
    )

    assert ctx.is_owner is True
    assert ctx.caller_kind is CallerKind.CHANNEL
    assert ctx.session_key == "agent:main:feishu:u1"
    assert ctx.workspace_dir == str(tmp_path)
    assert ctx.workspace_strict is True
    assert ctx.task_id == "task-1"


def test_gateway_normalizes_scheduler_cron_envelope_into_gateway_route_envelope() -> None:
    job = SimpleNamespace(
        id="job-7",
        name="nightly",
        delivery=SimpleNamespace(
            mode="reply",
            channel_name="telegram",
            channel_id="chat-7",
            account_id="acct-7",
            thread_id="thread-7",
        ),
        tool_policy={
            "profile": "minimal",
            "also_allow": ["memory_search", "exec_command"],
            "deny": ["web_fetch"],
        },
    )
    cron_envelope = scheduler_routing.build_cron_route_envelope(
        job,
        session_key="cron:job-7:run:1",
        agent_id="main",
    )
    normalize_route_envelope = getattr(gateway_routing, "normalize_route_envelope", None)

    assert callable(normalize_route_envelope)

    normalized = normalize_route_envelope(cron_envelope)

    assert isinstance(normalized, gateway_routing.RouteEnvelope)
    assert normalized.source_kind is gateway_routing.SourceKind.CRON
    assert normalized.interaction_mode is InteractionMode.UNATTENDED
    assert normalized.session_key == "cron:job-7:run:1"
    assert normalized.agent_id == "main"
    assert normalized.metadata["job_id"] == "job-7"
    assert normalized.metadata["job_name"] == "nightly"
    assert normalized.metadata["tool_policy"] == job.tool_policy
    assert normalized.reply_target is not None
    assert normalized.reply_target.channel_name == "telegram"
    assert normalized.reply_target.to == "chat-7"
    assert normalized.reply_target.account_id == "acct-7"
    assert normalized.reply_target.thread_id == "thread-7"
    assert normalized.delivery_fields() == {
        "last_channel": "telegram",
        "last_to": "chat-7",
        "last_account_id": "acct-7",
        "last_thread_id": "thread-7",
        "delivery_context": {
            "sender_id": "cron-job-job-7",
            "channel_id": "chat-7",
            "job_id": "job-7",
            "job_name": "nightly",
        },
    }

    ctx = tool_context_from_envelope(normalized)

    assert ctx.caller_kind is CallerKind.CRON
    assert ctx.interaction_mode is InteractionMode.UNATTENDED
    assert ctx.session_key == "cron:job-7:run:1"
    assert ctx.agent_id == "main"
    assert ctx.allowed_tools == {"session_status", "memory_search"}
    assert "web_fetch" in ctx.denied_tools
    assert "exec_command" in ctx.denied_tools


def test_gateway_normalizes_session_subagent_envelope_into_gateway_route_envelope() -> None:
    subagent_envelope = session_routing.build_subagent_route_envelope(
        session_key="agent:worker:child",
        parent_session_key="agent:main:parent",
        agent_id="worker",
        run_id="run-child",
        parent_task_id="task-parent",
        spawn_depth=2,
        origin="test_spawn",
    )
    normalize_route_envelope = getattr(gateway_routing, "normalize_route_envelope", None)

    assert callable(normalize_route_envelope)

    normalized = normalize_route_envelope(subagent_envelope)

    assert isinstance(normalized, gateway_routing.RouteEnvelope)
    assert normalized.source_kind is gateway_routing.SourceKind.SUBAGENT
    assert normalized.interaction_mode is InteractionMode.UNATTENDED
    assert normalized.session_key == "agent:worker:child"
    assert normalized.agent_id == "worker"
    assert normalized.channel_type == "subagent"
    assert normalized.channel_name == "subagent"
    assert normalized.channel_id == "run-child"
    assert normalized.metadata == {
        "parent_session_key": "agent:main:parent",
        "run_id": "run-child",
        "parent_task_id": "task-parent",
        "spawn_depth": 2,
        "origin": "test_spawn",
    }
    assert normalized.input_provenance == {
        "kind": "subagent_task",
        "parent_session_key": "agent:main:parent",
        "run_id": "run-child",
        "parent_task_id": "task-parent",
    }

    ctx = tool_context_from_envelope(normalized)

    assert ctx.caller_kind is CallerKind.SUBAGENT
    assert ctx.interaction_mode is InteractionMode.UNATTENDED
    assert ctx.session_key == "agent:worker:child"
    assert ctx.agent_id == "worker"
    assert ctx.subagent_depth == 2
