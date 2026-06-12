from __future__ import annotations

from opensquilla.tools.builtin.memory_tools import create_memory_tools
from opensquilla.tools.registry import ToolRegistry


def test_memory_tool_descriptions_keep_profile_out_of_memory_save() -> None:
    registry = ToolRegistry()
    create_memory_tools(object(), object(), registry=registry, memory_source="workspace")

    memory_search = registry.get("memory_search")
    memory_save = registry.get("memory_save")

    assert memory_search is not None
    assert memory_save is not None
    assert "decisions, dates, people, preferences, or todos" not in memory_search.spec.description
    assert "Searches curated memory source files by default" in memory_search.spec.description
    assert "source=sessions for indexed transcript snippets" in memory_search.spec.description
    assert "USER.md" in memory_save.spec.description
    assert "filesystem tools, not memory_save" in memory_save.spec.description


def test_profile_recall_guidance_stays_in_system_prompt() -> None:
    from opensquilla.identity.prompt import assemble_system_prompt
    from opensquilla.identity.types import AgentProfile

    prompt = assemble_system_prompt(
        AgentProfile(agent_id="main", prompt_mode="full"),
        tools=["memory_search", "memory_get"],
    )

    assert "user identity/profile questions" in prompt
    assert "first use injected `USER.md`" in prompt
    assert "Do not call `memory_search` for those questions" in prompt
    assert "For `source: memory` results, use `memory_get`" in prompt
