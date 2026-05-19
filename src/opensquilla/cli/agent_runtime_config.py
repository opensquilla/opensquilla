"""Runtime configuration helpers for the one-shot agent CLI."""

from __future__ import annotations

import copy
import os
from typing import Any

_AGENT_PERMISSION_PROFILES = frozenset({"restricted", "bypass", "full"})


def _resolve_permissions_profile(value: str | None) -> str:
    raw = value if value is not None else os.environ.get("OPENSQUILLA_AGENT_PERMISSIONS")
    profile = (raw or "restricted").strip().lower()
    if profile not in _AGENT_PERMISSION_PROFILES:
        allowed = ", ".join(sorted(_AGENT_PERMISSION_PROFILES))
        raise ValueError(f"permissions must be one of: {allowed}")
    return profile


def _with_agent_workspace_config(config: Any, workspace: str) -> Any:
    memory = getattr(config, "memory", None)
    if memory is not None and hasattr(memory, "model_copy"):
        memory = memory.model_copy(update={"source": "workspace"})
    elif memory is not None:
        memory = copy.copy(memory)
        setattr(memory, "source", "workspace")

    update: dict[str, Any] = {"workspace_dir": workspace}
    if memory is not None:
        update["memory"] = memory
    if hasattr(config, "model_copy"):
        return config.model_copy(update=update)
    copied = copy.copy(config)
    setattr(copied, "workspace_dir", workspace)
    if memory is not None:
        setattr(copied, "memory", memory)
    return copied


def _with_agent_thinking_config(config: Any, thinking: str) -> Any:
    llm = getattr(config, "llm", None)
    if llm is None:
        return config
    if hasattr(llm, "model_copy"):
        llm = llm.model_copy(update={"thinking": thinking})
    else:
        llm = copy.copy(llm)
        setattr(llm, "thinking", thinking)

    if hasattr(config, "model_copy"):
        return config.model_copy(update={"llm": llm})
    copied = copy.copy(config)
    setattr(copied, "llm", llm)
    return copied


def _with_agent_model_config(config: Any, model: str) -> Any:
    llm = getattr(config, "llm", None)
    if llm is None:
        return config
    if hasattr(llm, "model_copy"):
        llm = llm.model_copy(update={"model": model})
    else:
        llm = copy.copy(llm)
        setattr(llm, "model", model)

    if hasattr(config, "model_copy"):
        return config.model_copy(update={"llm": llm})
    copied = copy.copy(config)
    setattr(copied, "llm", llm)
    return copied


def _agent_model_from_config(config: Any, agent_id: str) -> str | None:
    try:
        from opensquilla.agents.scope import resolve_agent_model

        return resolve_agent_model(agent_id, config)
    except Exception:
        return None


def _resolve_workspace_strict(
    *,
    cli_value: bool | None,
    config_value: Any,
    entrypoint_default: bool,
    env: dict[str, str] | None = None,
) -> bool:
    if cli_value is not None:
        return cli_value

    env_value = _parse_bool((env or os.environ).get("OPENSQUILLA_WORKSPACE_STRICT"))
    if env_value is not None:
        return env_value

    if isinstance(config_value, bool):
        return config_value
    return entrypoint_default


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None
