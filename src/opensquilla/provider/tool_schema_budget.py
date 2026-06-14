"""Fit tool definitions into a per-route schema budget.

Budgets (``max_tool_schema_chars``) are measured in compact-JSON
serialization characters via the same ``_payload_chars`` accounting as
provider request proof — not wire bytes, which serialize larger.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from opensquilla.provider.openai import _build_openai_tool
from opensquilla.provider.request_proof import _payload_chars
from opensquilla.provider.types import ToolDefinition


@dataclass(frozen=True)
class ToolSchemaFitResult:
    tool_defs: list[ToolDefinition]
    selected_toolset: str
    dropped_tools: list[str]
    tools_chars: int
    budget_chars: int

    @property
    def changed(self) -> bool:
        return bool(self.dropped_tools)


def openai_tool_payload(tool_defs: Sequence[ToolDefinition]) -> list[dict[str, Any]]:
    return [_build_openai_tool(tool) for tool in tool_defs]


def tool_schema_chars(tool_defs: Sequence[ToolDefinition]) -> int:
    return _payload_chars(openai_tool_payload(tool_defs))


def fit_tool_schema_budget(
    tool_defs: Sequence[ToolDefinition],
    *,
    toolset: str | None = None,
    toolsets: Mapping[str, Sequence[str]] | None = None,
    priority: Sequence[str] | None = None,
    max_tool_schema_chars: int | None = None,
) -> ToolSchemaFitResult:
    original = list(tool_defs)
    original_names = [tool.name for tool in original]
    selected_toolset = str(toolset or "full").strip() or "full"
    configured_toolsets = toolsets or {}

    if selected_toolset == "full":
        candidates = list(original)
    else:
        allowed = configured_toolsets.get(selected_toolset)
        if allowed is None:
            selected_toolset = "full"
            candidates = list(original)
        else:
            allowed_names = {str(name) for name in allowed}
            candidates = [tool for tool in original if tool.name in allowed_names]

    budget = _positive_int(max_tool_schema_chars)
    if budget is not None:
        candidates = _fit_candidates_to_budget(
            candidates,
            priority=priority or (),
            budget=budget,
        )

    kept_names = {tool.name for tool in candidates}
    dropped_tools = [name for name in original_names if name not in kept_names]
    return ToolSchemaFitResult(
        tool_defs=candidates,
        selected_toolset=selected_toolset,
        dropped_tools=dropped_tools,
        tools_chars=tool_schema_chars(candidates),
        budget_chars=budget or 0,
    )


def _fit_candidates_to_budget(
    candidates: list[ToolDefinition],
    *,
    priority: Sequence[str],
    budget: int,
) -> list[ToolDefinition]:
    priority_rank = {name: index for index, name in enumerate(priority)}
    original_index = {id(tool): index for index, tool in enumerate(candidates)}
    ordered = sorted(
        candidates,
        key=lambda tool: (
            priority_rank.get(tool.name, len(priority_rank)),
            original_index[id(tool)],
        ),
    )
    selected: list[ToolDefinition] = []
    selected_ids: set[int] = set()
    for tool in ordered:
        proposed = selected + [tool]
        if tool_schema_chars(proposed) <= budget:
            selected.append(tool)
            selected_ids.add(id(tool))
    return [tool for tool in candidates if id(tool) in selected_ids]


def _positive_int(value: int | None) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
