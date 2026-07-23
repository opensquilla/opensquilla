"""Offline tests for the AIQ bridge (contrib/aiq).

No network, no credentials, no model calls: the bridge must import, register,
validate, and degrade cleanly without the AIQ repo or its dependencies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

import opensquilla.contrib.aiq as contrib_aiq
from opensquilla.contrib.aiq import runtime as aiq_runtime
from opensquilla.contrib.aiq.agent import (
    AIQ_AGENT_ID,
    aiq_agent_entry,
    aiq_agent_tool_allowlist,
    ensure_aiq_agent,
    load_persona,
)
from opensquilla.contrib.aiq.catalog import aiq_tool_names, load_catalog
from opensquilla.contrib.aiq.runtime import resolve_repo_path, resolve_user_email
from opensquilla.engine.types import ToolCall
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import get_default_registry
from opensquilla.tools.schema_validation import validate_tool_arguments
from opensquilla.tools.types import CallerKind, ToolContext
from opensquilla.tools.visibility import is_tool_visible

EXPECTED_TOOL_COUNT = 42

ENVELOPE_KEYS = {"status", "tool", "error_class", "user_message", "retry_allowed"}


def _agent_ctx(allowed: set[str] | None = None) -> ToolContext:
    return ToolContext(
        is_owner=True,
        caller_kind=CallerKind.AGENT,
        allowed_tools=allowed,
        run_mode="full",
    )


def test_bridge_imports_and_registers_without_aiq_on_path() -> None:
    """Importing the bridge never touches the AIQ repo and registers all tools."""

    assert not [m for m in sys.modules if m == "lib" or m.startswith("lib.")]
    names = aiq_tool_names()
    assert len(names) == EXPECTED_TOOL_COUNT
    assert len(set(names)) == EXPECTED_TOOL_COUNT
    registry = get_default_registry()
    for name in names:
        assert registry.get(name) is not None, f"{name} not registered"
    # The inventory's headline tools and the long-tail meta pair are present.
    for expected in (
        "prints_latest",
        "securities_search",
        "bond_calculate",
        "search_tools",
        "call_tool",
        "generate_portfolio_proposal",
    ):
        assert expected in names


def test_bridged_tools_hidden_unless_allowlisted() -> None:
    registry = get_default_registry()
    default_ctx = ToolContext(is_owner=True, caller_kind=CallerKind.AGENT)
    allow_ctx = _agent_ctx(allowed=set(aiq_tool_names()))
    for name in aiq_tool_names():
        rt = registry.get(name)
        assert rt is not None
        assert rt.spec.exposed_by_default is False
        assert not is_tool_visible(rt, default_ctx)
        assert is_tool_visible(rt, allow_ctx)


def _example_value(schema: dict[str, Any]) -> Any:
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    declared = schema.get("type")
    types = declared if isinstance(declared, list) else [declared]
    primary = next((t for t in types if t and t != "null"), "string")
    if primary == "string":
        return "example"
    if primary == "integer":
        return 1
    if primary == "number":
        return 1.5
    if primary == "boolean":
        return True
    if primary == "array":
        item_schema = schema.get("items")
        return [_example_value(item_schema)] if isinstance(item_schema, dict) else []
    if primary == "object":
        return {}
    return "example"


def test_every_declared_schema_passes_schema_validation() -> None:
    """Synthesized schema-conformant args validate; wrong types are rejected."""

    for tool_def in load_catalog():
        assert isinstance(tool_def.params, dict)
        # Properties-only convention: never the full {"type": "object"} wrapper.
        assert tool_def.params.get("type") != "object"
        assert set(tool_def.required) <= set(tool_def.params)
        arguments = {name: _example_value(tool_def.params[name]) for name in tool_def.params}
        errors = validate_tool_arguments(
            arguments,
            properties=tool_def.params,
            required=tool_def.required,
        )
        assert errors == [], f"{tool_def.name}: {errors}"
        # Missing required args must be flagged.
        if tool_def.required:
            errors = validate_tool_arguments(
                {},
                properties=tool_def.params,
                required=tool_def.required,
            )
            assert errors, f"{tool_def.name}: missing required args not flagged"


async def test_dispatch_rejects_arguments_violating_schema() -> None:
    handler = build_tool_handler(get_default_registry(), _agent_ctx({"prints_latest"}))
    result = await handler(
        ToolCall(
            tool_use_id="tc-bad-args",
            tool_name="prints_latest",
            arguments={"cusips": "not-an-array"},
        )
    )
    payload = json.loads(result.content)
    assert payload["status"] == "rejected"
    assert payload["error_class"] == "InvalidToolArgumentsError"


async def test_unavailable_repo_yields_clean_failure_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AIQ_REPO_PATH", str(tmp_path / "nowhere"))
    handler = build_tool_handler(
        get_default_registry(),
        _agent_ctx({"prints_latest", "bond_calculate"}),
    )
    # One network-classified tool and one local-classified tool.
    for name, arguments in (
        ("prints_latest", {"cusips": ["037833AK6"]}),
        (
            "bond_calculate",
            {
                "calculation": "price_to_yield",
                "coupon_rate": 5.0,
                "maturity_date": "2030-01-01",
                "price": 99.5,
            },
        ),
    ):
        result = await handler(
            ToolCall(tool_use_id=f"tc-{name}", tool_name=name, arguments=arguments)
        )
        assert result.is_error is True
        envelope = json.loads(result.content)
        assert set(envelope) == ENVELOPE_KEYS
        assert envelope["status"] == "error"
        assert envelope["tool"] == name
        assert envelope["error_class"] == "SafeToolError"
        assert envelope["retry_allowed"] is False
        assert "AIQ" in envelope["user_message"]
        assert "Traceback" not in envelope["user_message"]


def test_repo_path_and_email_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AIQ_REPO_PATH", str(tmp_path))
    monkeypatch.setenv("AIQ_USER_EMAIL", "trader@example.com")
    assert resolve_repo_path() == tmp_path
    assert resolve_user_email() == "trader@example.com"


def test_persona_is_ported_and_adapted() -> None:
    persona = load_persona()
    assert "FINRA TRACE" in persona
    assert "securities_search" in persona
    assert "bond_calculate" in persona
    # Harness adaptation: OpenSquilla's skill mechanism, not AIQ's read_skill.
    assert "skill_view" in persona
    assert "read_skill" not in persona
    assert "load at most one" in persona
    assert "detail='compact'" in persona


def test_securities_detail_schema_matches_aiq_backend_contract() -> None:
    securities = next(tool for tool in load_catalog() if tool.name == "securities_search")
    detail = securities.params["detail"]
    assert detail["enum"] == ["compact", "full"]
    assert detail["default"] == "full"
    assert "detail" not in securities.required

    compound_fields = {
        "price_min",
        "price_max",
        "duration_min",
        "duration_max",
        "maturity_years",
        "maturity_ladder_years",
        "include_recent_prints",
        "recent_prints_limit",
        "include_cpp_history",
        "cpp_history_lookback_days",
        "include_period_history",
    }
    assert compound_fields <= set(securities.params)
    assert securities.params["order_by"]["default"] == "smart"
    assert securities.params["recent_prints_limit"]["default"] == "10"


def test_ranking_skill_uses_progressive_detail_without_a_second_tool() -> None:
    skill = Path("src/opensquilla/skills/bundled/aiq-rankings-and-leaderboards/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "securities_search(detail='compact'" in skill
    assert "Do **not** automatically repeat a successful compact call" in skill
    assert "trace_notional(group_by='issuer')" in skill


async def test_bridge_forwards_compact_detail_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeFunctionTool:
        async def on_invoke_tool(self, *, ctx, input):
            captured["ctx"] = ctx
            captured["arguments"] = json.loads(input)
            return json.dumps({"bonds": [], "meta": {"detail": "compact"}})

    monkeypatch.setattr(
        aiq_runtime, "_load_function_tool", lambda _module, _attr: FakeFunctionTool()
    )
    monkeypatch.setattr(aiq_runtime, "_make_aiq_tool_context", lambda _name, _args: object())

    result = await aiq_runtime.invoke_aiq_tool(
        "securities_search",
        "lib.tools.sql_data_tools.securities_tools",
        "securities_search",
        {
            "detail": "compact",
            "order_by": "notional",
            "include_liquidity": "true",
            "include_recent_prints": "true",
            "include_period_history": "day",
        },
        [],
    )
    assert captured["arguments"]["detail"] == "compact"
    assert captured["arguments"]["include_recent_prints"] == "true"
    assert captured["arguments"]["include_period_history"] == "day"
    assert json.loads(result)["meta"]["detail"] == "compact"


async def test_agent_registration_resolves(tmp_path) -> None:
    from opensquilla.agents.registry import AgentRegistry
    from opensquilla.gateway.config import GatewayConfig

    entry = aiq_agent_entry()
    assert entry.id == AIQ_AGENT_ID
    assert entry.model == "claude-sonnet-4-5"
    assert set(aiq_tool_names()) <= set(entry.tools["allow"])

    config = GatewayConfig()
    registry = AgentRegistry(config, persist_changes=False)
    workspace = str(tmp_path / "aiq-workspace")
    summary = await registry.create_agent(
        agent_id=entry.id,
        name=entry.name,
        description=entry.description,
        model=entry.model,
        workspace=workspace,
        tools=entry.tools,
        enabled=True,
        system_prompt=entry.system_prompt,
    )
    assert summary["id"] == AIQ_AGENT_ID
    assert config.agents[0].id == AIQ_AGENT_ID
    assert config.agents[0].tools == entry.tools
    # ensure_aiq_agent is idempotent over an existing entry and writes the
    # persona bootstrap file into the agent workspace.
    summary = await ensure_aiq_agent(registry, workspace=workspace)
    assert summary["id"] == AIQ_AGENT_ID
    assert len(config.agents) == 1
    persona_file = await registry.get_agent_file(AIQ_AGENT_ID, "AGENTS.md")
    assert "FINRA TRACE" in persona_file["content"]


def test_allowlist_includes_native_helpers() -> None:
    allow = aiq_agent_tool_allowlist()
    assert "skill_view" in allow
    assert "web_search" in allow


def test_register_is_idempotent() -> None:
    before = set(get_default_registry().list_names())
    contrib_aiq.register_aiq_tools()
    assert set(get_default_registry().list_names()) == before
