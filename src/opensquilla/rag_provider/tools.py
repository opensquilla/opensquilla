from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from opensquilla.rag_provider.protocol import (
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
)
from opensquilla.sandbox.operation_runtime import SandboxToolDescriptor
from opensquilla.tools.types import ToolError, ToolHandler, ToolSpec


@dataclass(frozen=True)
class ToolBinding:
    spec: ToolSpec
    handler: ToolHandler


def _network_descriptor(kind: str) -> SandboxToolDescriptor:
    return SandboxToolDescriptor.network(
        kind=kind,
        argv_factory=lambda arguments: (
            kind,
            str(arguments.get("query") or arguments.get("evidence_id") or ""),
        ),
        record_payload=False,
    )


def rag_provider_tool_bindings(runtime: Any) -> dict[str, ToolBinding]:
    async def knowledge_search(query: str, limit: int = 8) -> str:
        clean = str(query or "").strip()
        if not clean:
            raise ToolError("query is required")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ToolError("limit must be between 1 and 20")
        try:
            validated = await runtime.search(query=clean, limit=limit)
        except Exception as error:
            raise _safe_tool_error(error) from error
        payload = dict(validated.payload)
        payload["providerBudgetViolation"] = validated.provider_budget_violation
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    async def knowledge_get(evidence_id: str, cursor: str | None = None) -> str:
        clean = str(evidence_id or "").strip()
        if not clean:
            raise ToolError("evidence_id is required")
        if cursor is not None and not str(cursor).strip():
            raise ToolError("cursor must be a non-empty string")
        try:
            payload = await runtime.get(evidence_id=clean, cursor=cursor)
        except Exception as error:
            raise _safe_tool_error(error) from error
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    search_spec = ToolSpec(
        name="knowledge_search",
        description=(
            "Search the configured external knowledge provider and return citable evidence."
        ),
        parameters={
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        required=["query"],
        result_budget_class="external",
        sandbox=_network_descriptor("knowledge.search"),
    )
    get_spec = ToolSpec(
        name="knowledge_get",
        description="Read normalized source text around evidence returned by knowledge_search.",
        parameters={
            "evidence_id": {"type": "string", "minLength": 1},
            "cursor": {"type": "string", "minLength": 1},
        },
        required=["evidence_id"],
        result_budget_class="external",
        sandbox=_network_descriptor("knowledge.get"),
    )
    return {
        search_spec.name: ToolBinding(search_spec, knowledge_search),
        get_spec.name: ToolBinding(get_spec, knowledge_get),
    }


def _safe_tool_error(error: Exception) -> ToolError:
    if isinstance(error, ProviderNotFound):
        return ToolError("provider_not_found")
    if isinstance(error, ProviderProtocolViolation):
        return ToolError("provider_protocol_violation")
    if isinstance(error, ProviderUnavailable):
        return ToolError("knowledge_provider_unavailable")
    if isinstance(error, RuntimeError) and str(error) in {
        "knowledge_provider_unavailable",
        "knowledge_get_unavailable",
    }:
        return ToolError("knowledge_provider_unavailable")
    return ToolError("knowledge_provider_unavailable")
