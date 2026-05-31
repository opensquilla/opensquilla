from __future__ import annotations

from opensquilla.engine.context_budget import coordinate_provider_context_budget


def test_context_budget_sends_payload_when_proof_is_disabled() -> None:
    payload = {"messages": [{"role": "user", "content": "hello"}]}

    decision = coordinate_provider_context_budget(
        payload,
        projection_adapter="test",
        proof_budget=0,
    )

    assert decision.action == "send"
    assert decision.payload == payload
    assert decision.proof is None


def test_context_budget_reuses_provider_proof_for_budget_limited() -> None:
    payload = {"messages": [{"role": "user", "content": "x" * 5000}]}

    decision = coordinate_provider_context_budget(
        payload,
        projection_adapter="test",
        proof_budget=100,
    )

    assert decision.action == "budget_limited"
    assert decision.payload is None
    assert decision.reason == "provider_request_budget_exhausted"
    assert decision.proof is not None
    assert decision.proof["fallback_reason"] == "provider_request_budget_exhausted"


def test_context_budget_reports_send_compacted_when_provider_proof_compacts() -> None:
    payload = {
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": "x" * 5000,
                        },
                    }
                ],
            }
        ]
    }

    decision = coordinate_provider_context_budget(
        payload,
        projection_adapter="test",
        proof_budget=2000,
    )

    assert decision.action == "send_compacted"
    assert decision.proof is not None
    assert decision.proof["compact_needed"] is True
    assert decision.payload is not None
