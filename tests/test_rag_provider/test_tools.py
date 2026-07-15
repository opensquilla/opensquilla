from __future__ import annotations

import json

import pytest

from opensquilla.gateway.rag_provider_tools import rag_provider_tool_bindings
from opensquilla.rag_provider.protocol import (
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
    ValidatedSearchResponse,
)
from opensquilla.tools.types import ToolError


class Runtime:
    async def search(self, *, query: str, limit: int):
        assert query == "NAND"
        assert limit == 8
        return ValidatedSearchResponse(
            payload={
                "returnedCount": 0,
                "totalMatched": None,
                "resultsTruncated": False,
                "results": [],
            },
            provider_budget_violation=False,
        )

    async def get(self, *, evidence_id: str, cursor: str | None):
        return {"evidenceId": evidence_id, "content": "source"}


@pytest.mark.asyncio
async def test_tool_specs_are_minimal_external_network_tools() -> None:
    bindings = rag_provider_tool_bindings(Runtime())
    search = bindings["knowledge_search"]
    get = bindings["knowledge_get"]
    assert set(search.spec.parameters) == {"query", "limit"}
    assert set(get.spec.parameters) == {"evidence_id", "cursor"}
    assert search.spec.result_budget_class == "external"
    assert search.spec.sandbox.domain == "network"
    assert search.spec.sandbox.enforce is True

    payload = json.loads(await search.handler(query="NAND", limit=8))
    assert payload["providerBudgetViolation"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "safe_code"),
    [
        (ProviderUnavailable("secret upstream body"), "knowledge_provider_unavailable"),
        (ProviderProtocolViolation("secret malformed body"), "provider_protocol_violation"),
        (ProviderNotFound("secret document path"), "provider_not_found"),
    ],
)
async def test_tool_errors_are_stable_and_do_not_leak_provider_details(
    error: Exception,
    safe_code: str,
) -> None:
    class FailingRuntime:
        async def search(self, **_: object):
            raise error

        async def get(self, **_: object):
            raise error

    bindings = rag_provider_tool_bindings(FailingRuntime())
    handler = (
        bindings["knowledge_get"].handler
        if isinstance(error, ProviderNotFound)
        else bindings["knowledge_search"].handler
    )
    arguments = (
        {"evidence_id": "ev_a"}
        if isinstance(error, ProviderNotFound)
        else {"query": "NAND"}
    )

    with pytest.raises(ToolError) as caught:
        await handler(**arguments)

    assert str(caught.value) == safe_code
    assert "secret" not in str(caught.value)
