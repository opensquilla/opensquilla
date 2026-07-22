"""The ``aiq`` agent registration: AIQ TraceAgent persona + tool allowlist.

The persona (``persona.md``) is AIQ TraceAgent's ``domain_instructions()``
ported to OpenSquilla, with only harness-specific references adapted (skill
loading via ``skill_view``, runtime date/time from the system prompt, and
specialist-agent handoffs replaced by the bridged first-class tools).

Two ways to register the agent:

1. Declaratively — add the ``[[agents]]`` block from
   ``opensquilla.toml.example`` (or ``docs/features/aiq-agent.md``) to the
   gateway TOML and restart.
2. Programmatically — ``await ensure_aiq_agent(agent_registry)``, e.g. from
   an embedding script; this persists the entry and writes the persona to the
   agent workspace's ``AGENTS.md`` bootstrap file (the canonical persona
   channel; see ``docs/agents.md``).

Per OpenSquilla's provider defaults for this integration, the agent's model
defaults to Anthropic Claude (``claude-sonnet-4-5``).
"""

from __future__ import annotations

from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any

from opensquilla.contrib.aiq.catalog import aiq_tool_names

if TYPE_CHECKING:
    from opensquilla.agents.registry import AgentRegistry
    from opensquilla.gateway.config import AgentEntryConfig

AIQ_AGENT_ID = "aiq"
AIQ_AGENT_NAME = "AIQ Markets"
AIQ_AGENT_DESCRIPTION = (
    "US corporate bond (FINRA TRACE) market-data analyst: prints, securities "
    "screening, movers, MarketAxess CP+, bond math, portfolios, trade tickets."
)
# Anthropic Claude is the default provider/model for this agent; see [llm] in
# opensquilla.toml.example and docs/providers-and-models.md.
AIQ_DEFAULT_MODEL = "claude-sonnet-4-5"

# Native OpenSquilla helpers the persona relies on, beyond the bridged tools.
_NATIVE_ALLOWED_TOOLS = ("skill_view", "web_search", "web_fetch")


@cache
def load_persona() -> str:
    """The ported TraceAgent persona (markdown)."""

    return resources.files(__package__).joinpath("persona.md").read_text(encoding="utf-8")


def aiq_agent_tool_allowlist() -> list[str]:
    """Every bridged AIQ tool plus the native helpers the persona references."""

    return [*aiq_tool_names(), *_NATIVE_ALLOWED_TOOLS]


def aiq_agent_entry(
    model: str | None = None,
    workspace: str | None = None,
) -> AgentEntryConfig:
    """Build the ``[[agents]]`` entry for the AIQ agent."""

    from opensquilla.gateway.config import AgentEntryConfig

    return AgentEntryConfig(
        id=AIQ_AGENT_ID,
        name=AIQ_AGENT_NAME,
        description=AIQ_AGENT_DESCRIPTION,
        model=model or AIQ_DEFAULT_MODEL,
        workspace=workspace,
        tools={"allow": aiq_agent_tool_allowlist()},
        enabled=True,
        system_prompt=load_persona(),
    )


async def ensure_aiq_agent(
    registry: AgentRegistry,
    *,
    model: str | None = None,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Create or refresh the ``aiq`` agent and its workspace persona file.

    Idempotent: an existing entry is updated in place. The persona is written
    to the agent workspace's ``AGENTS.md`` so it enters the assembled system
    prompt through the standard bootstrap-file channel.
    """

    entry = aiq_agent_entry(model=model, workspace=workspace)
    existing = await registry.list_agents(include_builtin=False)
    if any(a.get("id") == AIQ_AGENT_ID for a in existing):
        summary = await registry.update_agent(
            AIQ_AGENT_ID,
            name=entry.name,
            description=entry.description,
            model=entry.model,
            workspace=entry.workspace,
            tools=entry.tools,
            enabled=True,
            system_prompt=entry.system_prompt,
        )
    else:
        summary = await registry.create_agent(
            agent_id=AIQ_AGENT_ID,
            name=entry.name,
            description=entry.description,
            model=entry.model,
            workspace=entry.workspace,
            tools=entry.tools,
            enabled=True,
            system_prompt=entry.system_prompt,
        )
    await registry.set_agent_file(AIQ_AGENT_ID, "AGENTS.md", load_persona())
    return summary
