"""Built-in ``core`` toolset and tier-toolset name validation.

Covers the two halves of the toolset wiring contract:

* ``ToolsConfig`` ships a ``core`` toolset whose members survive the char
  budget priority ordering and resolve through ``fit_tool_schema_budget``.
* A tier ``toolset`` that names neither ``full`` nor a key of the EFFECTIVE
  ``[tools.toolsets]`` dict fails at config load instead of silently falling
  back to ``full``.
"""

from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig, ToolsConfig
from opensquilla.provider.tool_schema_budget import fit_tool_schema_budget
from opensquilla.provider.types import ToolDefinition, ToolInputSchema

CORE_TOOLS = [
    "exec_command",
    "read_file",
    "write_file",
    "edit_file",
    "grep_search",
    "glob_search",
    "list_dir",
    "web_search",
    "web_fetch",
    "publish_artifact",
    "session_status",
    "message",
    "router_control",
    "meta_invoke",
]


def test_core_keeps_the_meta_invoke_entry_point() -> None:
    """meta_resolution prompt hints instruct the model to call meta_invoke
    first; a core surface without it strands meta-armed turns (live
    incident: agent:main:webchat:ymmm74ps — sticky meta hints on a c1 turn
    whose toolset lacked meta_invoke produced dead-end turns and the user's
    switch request never executed).
    """
    assert "meta_invoke" in ToolsConfig().toolsets["core"]
    priority = ToolsConfig().toolset_priority
    assert priority.index("meta_invoke") < priority.index("web_search")


def test_core_keeps_the_router_control_escape_hatch() -> None:
    """A routed tier without router_control cannot switch tiers or release an
    active hold from chat; text-compat models are allowlist-gated, so the
    session is locked on the tier (live incident: agent:main:webchat:t65cahdl).
    """
    assert "router_control" in ToolsConfig().toolsets["core"]
    priority = ToolsConfig().toolset_priority
    assert priority.index("router_control") < priority.index("web_search")


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} tool",
        input_schema=ToolInputSchema(
            properties={"query": {"type": "string"}},
            required=["query"],
        ),
    )


class TestCoreToolsetDefault:
    def test_core_toolset_exists_with_expected_members(self) -> None:
        cfg = ToolsConfig()
        assert cfg.toolsets["core"] == CORE_TOOLS

    def test_core_members_present_in_toolset_priority(self) -> None:
        cfg = ToolsConfig()
        missing = [name for name in CORE_TOOLS if name not in cfg.toolset_priority]
        assert missing == []

    def test_core_resolves_through_fit(self) -> None:
        cfg = ToolsConfig()
        tool_defs = [_tool(name) for name in CORE_TOOLS] + [_tool("memory_search")]
        result = fit_tool_schema_budget(
            tool_defs,
            toolset="core",
            toolsets=cfg.toolsets,
            priority=cfg.toolset_priority,
        )
        assert result.selected_toolset == "core"
        assert [tool.name for tool in result.tool_defs] == CORE_TOOLS
        assert result.dropped_tools == ["memory_search"]


class TestTierToolsetValidation:
    def test_unknown_tier_toolset_rejected_at_load(self) -> None:
        with pytest.raises(ValueError, match=r"tiers\.c1\.toolset 'croe'") as exc:
            GatewayConfig(
                squilla_router={"tiers": {"c1": {"toolset": "croe"}}},
            )
        assert "core" in str(exc.value)
        assert "full" in str(exc.value)

    def test_full_and_builtin_names_accepted(self) -> None:
        cfg = GatewayConfig(
            squilla_router={
                "tiers": {
                    "c0": {"toolset": "full"},
                    "c1": {"toolset": "core"},
                    "c2": {"toolset": "web"},
                }
            },
        )
        assert cfg.squilla_router.tiers["c1"]["toolset"] == "core"

    def test_operator_replaced_dict_validates_effective_names(self) -> None:
        cfg = GatewayConfig(
            tools={"toolsets": {"research": ["web_search", "web_fetch"]}},
            squilla_router={"tiers": {"c1": {"toolset": "research"}}},
        )
        assert cfg.squilla_router.tiers["c1"]["toolset"] == "research"

    def test_replace_semantics_drop_builtin_names(self) -> None:
        # [tools.toolsets] REPLACES the built-ins; "core" is gone once an
        # operator overrides the dict without restating it.
        with pytest.raises(ValueError, match=r"tiers\.c1\.toolset 'core'"):
            GatewayConfig(
                tools={"toolsets": {"research": ["web_search"]}},
                squilla_router={"tiers": {"c1": {"toolset": "core"}}},
            )

    def test_camelcase_toolset_key_validated(self) -> None:
        with pytest.raises(ValueError, match=r"tiers\.c2\.toolset 'nope'"):
            GatewayConfig(
                squilla_router={"tiers": {"c2": {"toolSet": "nope"}}},
            )

    def test_tier_without_toolset_passes(self) -> None:
        cfg = GatewayConfig(
            squilla_router={"tiers": {"c1": {"model": "some/model"}}},
        )
        assert "toolset" not in cfg.squilla_router.tiers["c1"]
