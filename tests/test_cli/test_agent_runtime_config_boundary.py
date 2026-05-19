from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.cli import agent_cmd, agent_runtime_config
from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig

RUNTIME_CONFIG_HELPERS = (
    "_resolve_permissions_profile",
    "_with_agent_workspace_config",
    "_with_agent_thinking_config",
    "_with_agent_model_config",
    "_agent_model_from_config",
    "_resolve_workspace_strict",
    "_parse_bool",
)


def test_agent_cmd_keeps_runtime_config_helpers_as_compatibility_aliases() -> None:
    for name in RUNTIME_CONFIG_HELPERS:
        helper = getattr(agent_runtime_config, name)
        assert getattr(agent_cmd, name) is helper
        assert helper.__module__ == "opensquilla.cli.agent_runtime_config"


def test_runtime_config_resolves_permission_profile_from_argument_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSQUILLA_AGENT_PERMISSIONS", " full ")

    assert agent_runtime_config._resolve_permissions_profile(None) == "full"
    assert agent_runtime_config._resolve_permissions_profile(" BYPASS ") == "bypass"

    with pytest.raises(ValueError, match="permissions must be one of"):
        agent_runtime_config._resolve_permissions_profile("benchmark")


def test_runtime_config_overrides_copy_plain_config_without_mutating_original() -> None:
    memory = SimpleNamespace(source="global")
    llm = SimpleNamespace(model="base/model", thinking="low")
    cfg = SimpleNamespace(workspace_dir=None, memory=memory, llm=llm)

    workspace_cfg = agent_runtime_config._with_agent_workspace_config(cfg, "/work")
    model_cfg = agent_runtime_config._with_agent_model_config(workspace_cfg, "agent/model")
    thinking_cfg = agent_runtime_config._with_agent_thinking_config(model_cfg, "high")

    assert cfg.workspace_dir is None
    assert cfg.memory.source == "global"
    assert cfg.llm.model == "base/model"
    assert cfg.llm.thinking == "low"
    assert workspace_cfg.workspace_dir == "/work"
    assert workspace_cfg.memory.source == "workspace"
    assert workspace_cfg.memory is not memory
    assert model_cfg.llm.model == "agent/model"
    assert model_cfg.llm is not llm
    assert thinking_cfg.llm.thinking == "high"


def test_runtime_config_resolves_agent_model_and_workspace_strict_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = GatewayConfig(agents=[AgentEntryConfig(id="ops", model="agent/model")])

    assert agent_runtime_config._agent_model_from_config(cfg, "ops") == "agent/model"
    assert agent_runtime_config._agent_model_from_config(cfg, "unknown") is None
    assert agent_runtime_config._resolve_workspace_strict(
        cli_value=True,
        config_value=False,
        entrypoint_default=False,
        env={},
    )
    assert agent_runtime_config._resolve_workspace_strict(
        cli_value=None,
        config_value=None,
        entrypoint_default=True,
        env={"OPENSQUILLA_WORKSPACE_STRICT": "off"},
    ) is False

    monkeypatch.delenv("OPENSQUILLA_WORKSPACE_STRICT", raising=False)
    assert agent_runtime_config._parse_bool(" yes ") is True
    assert agent_runtime_config._parse_bool("0") is False
    assert agent_runtime_config._parse_bool("sometimes") is None
