from __future__ import annotations

from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig
from opensquilla.scheduler.routing import build_cron_route_envelope, tool_context_from_envelope
from opensquilla.scheduler.types import CronJob, DeliveryConfig
from opensquilla.tools.policy import apply_tool_policy_from_config
from opensquilla.tools.types import (
    CRON_AGENT_DENY,
    SUBAGENT_TOOL_DENY,
    CallerKind,
    InteractionMode,
    ToolContext,
)


def test_tool_policy_reads_direct_gateway_agents_list() -> None:
    cfg = GatewayConfig(
        agents=[
            AgentEntryConfig(
                id="ops",
                tools={"profile": "minimal", "also_allow": ["memory_search"]},
            )
        ]
    )
    ctx = ToolContext(agent_id="ops")

    result = apply_tool_policy_from_config(
        ctx,
        available_tools=["session_status", "memory_search", "exec_command"],
        config=cfg,
    )

    assert result.allowed_tools == {"session_status", "memory_search"}


def test_cron_route_tool_policy_can_only_narrow_or_extend_cron_baseline() -> None:
    job = CronJob(
        id="policy",
        name="Policy",
        tool_policy={
            "profile": "minimal",
            "also_allow": ["memory_search", "exec_command"],
            "deny": ["web_fetch"],
        },
    )

    envelope = build_cron_route_envelope(
        job,
        session_key="cron:policy:run:1",
        agent_id="main",
    )
    result = tool_context_from_envelope(envelope)

    assert envelope.metadata["tool_policy"] == job.tool_policy
    assert result.caller_kind is CallerKind.CRON
    assert result.allowed_tools == {"session_status", "memory_search"}
    assert "web_fetch" in result.denied_tools
    assert "exec_command" in result.denied_tools


def test_cron_route_tool_context_preserves_policy_and_route_fields() -> None:
    job = CronJob(
        id="policy-runtime",
        name="Policy Runtime",
        delivery=DeliveryConfig(
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
    envelope = build_cron_route_envelope(
        job,
        session_key="cron:policy-runtime:run:1",
        agent_id="main",
    )
    result = tool_context_from_envelope(
        envelope,
        is_owner=True,
        workspace_dir="/tmp/workspace",
        workspace_strict=True,
    )

    assert result.is_owner is True
    assert result.workspace_dir == "/tmp/workspace"
    assert result.workspace_strict is True
    assert result.caller_kind is CallerKind.CRON
    assert result.interaction_mode is InteractionMode.UNATTENDED
    assert result.source_kind == "cron"
    assert result.source_name == "cron"
    assert result.channel_kind == "cron"
    assert result.channel_id == "cron:policy-runtime"
    assert result.sender_id == "cron-job-policy-runtime"
    assert result.session_key == "cron:policy-runtime:run:1"
    assert result.allowed_tools == {"session_status", "memory_search"}
    assert "exec_command" in result.denied_tools
    assert "web_fetch" in result.denied_tools


def test_policy_deny_lists_do_not_reference_removed_agent_wrapper_tools() -> None:
    assert "spawn_subagent" not in SUBAGENT_TOOL_DENY
    assert "send_message" not in SUBAGENT_TOOL_DENY
    assert "spawn_subagent" not in CRON_AGENT_DENY
    assert "send_message" not in CRON_AGENT_DENY


def test_messaging_group_does_not_revive_removed_agent_send_wrapper() -> None:
    cfg = GatewayConfig(tools={"profile": "messaging"})
    ctx = ToolContext(agent_id="main")

    result = apply_tool_policy_from_config(
        ctx,
        available_tools=["message", "send_message", "sessions_send", "session_status"],
        config=cfg,
    )

    assert result.allowed_tools is not None
    assert "message" in result.allowed_tools
    assert "sessions_send" in result.allowed_tools
    assert "send_message" not in result.allowed_tools
