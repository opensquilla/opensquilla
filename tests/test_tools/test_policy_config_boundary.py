from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from opensquilla.gateway.config import GatewayConfig
from opensquilla.tools import policy_helpers
from opensquilla.tools.policy import apply_tool_policy_from_config
from opensquilla.tools.policy_config import (
    ToolPolicy,
    expand_selectors,
    policy_from_config,
    profile_allowlist,
    sender_policy,
)
from opensquilla.tools.types import CallerKind, ToolContext

ROOT = Path(__file__).resolve().parents[2]
POLICY_HELPERS = ROOT / "src/opensquilla/tools/policy_helpers.py"
POLICY_CONFIG = ROOT / "src/opensquilla/tools/policy_config.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _top_level_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _top_level_assignments(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_policy_helpers_delegates_config_policy_to_boundary() -> None:
    imports = _imports_from(POLICY_HELPERS)
    helper_functions = _top_level_functions(POLICY_HELPERS)
    helper_assignments = _top_level_assignments(POLICY_HELPERS)

    assert ("opensquilla.tools", "policy_config") in imports
    assert policy_helpers.ToolPolicy is ToolPolicy
    assert "ToolPolicy" not in _top_level_classes(POLICY_HELPERS)
    assert "ToolPolicy" in helper_assignments
    assert "_TOOL_GROUPS" not in helper_assignments
    assert "_TOOL_PROFILES" not in helper_assignments
    assert "_SENDER_SCOPED_TOOL_GROUPS" not in helper_assignments
    assert "_SENDER_SCOPED_TOOL_NAMES" not in helper_assignments
    assert "_expand_selectors" not in helper_functions
    assert "_policy_from_config" not in helper_functions
    assert "_apply_channel_layer" not in helper_functions
    assert "_apply_sender_layer" not in helper_functions

    config_functions = _top_level_functions(POLICY_CONFIG)
    config_assignments = _top_level_assignments(POLICY_CONFIG)
    assert "ToolPolicy" in _top_level_classes(POLICY_CONFIG)
    assert "_TOOL_GROUPS" in config_assignments
    assert "_TOOL_PROFILES" in config_assignments
    assert "_SENDER_SCOPED_TOOL_GROUPS" in config_assignments
    assert "_SENDER_SCOPED_TOOL_NAMES" in config_assignments
    assert "expand_selectors" in config_functions
    assert "policy_from_config" in config_functions
    assert "apply_channel_layer" in config_functions
    assert "apply_sender_layer" in config_functions


def test_policy_config_expands_current_groups_patterns_and_profiles() -> None:
    available = frozenset(
        {
            "create_pptx",
            "feishu_perm_grant_member",
            "http_request",
            "image_generate",
            "install_skill_deps",
            "message",
            "session_status",
            "web_fetch",
            "web_search",
        }
    )

    assert expand_selectors(
        frozenset(
            {
                "channel:media",
                "channel:perm",
                "group:trusted_host",
                "web_*",
                "missing",
            }
        ),
        available,
    ) == {
        "create_pptx",
        "feishu_perm_grant_member",
        "image_generate",
        "install_skill_deps",
        "web_fetch",
        "web_search",
    }
    assert profile_allowlist("minimal", available) == {"session_status"}
    assert profile_allowlist("full", available) is None


def test_policy_config_parses_gateway_and_sender_policy_shapes() -> None:
    config = SimpleNamespace(
        tools=SimpleNamespace(
            profile="coding",
            deny=["exec_*"],
            also_allow=["http_request"],
        ),
        toolsBySender={
            "id:alice": {"allow": ["message"], "deny": ["read_file"]},
            "*": {"alsoAllow": ["sessions_send"]},
        },
    )

    policy = policy_from_config(config)

    assert policy == ToolPolicy(
        profile="coding",
        deny=frozenset({"exec_*"}),
        also_allow=frozenset({"http_request"}),
        by_sender={
            "id:alice": ToolPolicy(
                allow=frozenset({"message"}),
                deny=frozenset({"read_file"}),
            ),
            "*": ToolPolicy(also_allow=frozenset({"sessions_send"})),
        },
    )
    assert sender_policy(policy, "alice") == ToolPolicy(
        allow=frozenset({"message"}),
        deny=frozenset({"read_file"}),
    )
    assert sender_policy(policy, "bob") == ToolPolicy(
        also_allow=frozenset({"sessions_send"})
    )


def test_policy_helpers_apply_workspace_write_deny_globs_from_config() -> None:
    ctx = apply_tool_policy_from_config(
        ToolContext(),
        available_tools=["write_file", "exec_command"],
        config={"tools": {"workspaceWriteDenyGlobs": ["generated/**", "*.secret"]}},
    )

    assert set(ctx.workspace_write_deny_globs) == {"generated/**", "*.secret"}


def test_gateway_tools_config_preserves_workspace_write_deny_globs() -> None:
    cfg = GatewayConfig(
        tools={
            "workspace_write_deny_globs": ["tests/**", "*.spec.*"],
        }
    )

    ctx = apply_tool_policy_from_config(
        ToolContext(),
        available_tools=["write_file", "exec_command"],
        config=cfg,
    )

    assert set(ctx.workspace_write_deny_globs) == {"tests/**", "*.spec.*"}


def test_policy_helpers_apply_runtime_policy_through_config_boundary() -> None:
    config = {
        "channels": {
            "feishu": {
                "groups": {
                    "oc_demo": {
                        "tools": {
                            "profile": "minimal",
                            "also_allow": ["channel:perm"],
                            "toolsBySender": {
                                "id:ou_allowed": {"also_allow": ["channel:perm"]}
                            },
                        }
                    }
                }
            }
        }
    }
    available = ["session_status", "feishu_perm_grant_member"]

    default_ctx = apply_tool_policy_from_config(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CHANNEL,
            channel_kind="feishu",
            channel_id="oc_demo",
            sender_id="ou_other",
        ),
        available_tools=available,
        config=config,
    )
    sender_ctx = apply_tool_policy_from_config(
        ToolContext(
            is_owner=False,
            caller_kind=CallerKind.CHANNEL,
            channel_kind="feishu",
            channel_id="oc_demo",
            sender_id="ou_allowed",
        ),
        available_tools=available,
        config=config,
    )

    assert default_ctx.allowed_tools == {"session_status"}
    assert sender_ctx.allowed_tools == {"session_status", "feishu_perm_grant_member"}
    assert policy_helpers.private_memory_read_tool_denied(
        ToolContext(caller_kind=CallerKind.SUBAGENT), "memory_get"
    )
