"""Agent configuration DTOs shared by gateway and agent services."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentSubagentDefaults(BaseModel):
    """Per-agent subagent governance defaults.

    All fields are optional. ``None`` means "unset"; downstream code falls
    back to global agent defaults and then to "preserve current behavior".
    Only ``cascade_on_parent_kill`` has a non-None default because killing
    children is the safer behavior when in doubt.
    """

    model: str | None = None
    """Default LLM model for subagents spawned under this agent. ``None`` ->
    fall back to caller's model (current behavior)."""

    max_children_per_session: int | None = None
    """Max active children one parent session can hold. ``None`` -> no
    enforcement (current behavior)."""

    allow_agents: list[str] | None = None
    """Cross-agent spawn allowlist. ``None`` = unset (current behavior); ``[]``
    = self only; ``["*"]`` = any. Other values are exact agent_id matches."""

    cascade_on_parent_kill: bool = True
    """When ``True``, killing a parent session also cancels its descendants."""


class AgentEntryConfig(BaseModel):
    """Config entry for a durable, user-managed agent."""

    id: str
    name: str | None = None
    description: str | None = None
    model: str | None = None
    workspace: str | None = None
    agent_dir: str | None = None
    tools: dict[str, Any] | list[str] | str | None = None
    enabled: bool = True
    system_prompt: str | None = None
    subagents: AgentSubagentDefaults | None = None

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("agent id must be non-empty")
        from opensquilla.session.keys import normalize_agent_id

        return normalize_agent_id(raw)


class AgentDefaults(BaseModel):
    """Global fallback defaults applied when an agent does not override."""

    subagents: AgentSubagentDefaults | None = None


class SubagentsGatewayConfig(BaseModel):
    """Gateway-level subagent governance knobs."""

    enforce_disabled_agents: bool = False
    """When True, ``sessions_spawn`` rejects requests targeting an agent whose
    ``enabled=False``. Default off so existing deployments are unaffected."""

    subagent_reserved_slots: int = Field(default=2, ge=0)
    """Number of slots in ``task_runtime.max_concurrency`` reserved for
    non-subagent tasks so a fan-out parent never starves itself."""

    archive_after_minutes: int = Field(default=60, ge=0)
    """Minutes after a subagent session goes terminal before its transcript
    is archived. ``0`` disables auto-archive."""

    prompt_compact: bool = False
    """When enabled, subagent bootstrap prompts keep only AGENTS.md and TOOLS.md."""
