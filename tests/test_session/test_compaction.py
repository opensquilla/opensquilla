"""Tests for context window compaction logic."""

import pytest

from opensquilla.session.compaction import (
    CompactionConfig,
    CompactionRequest,
    call_compaction_llm,
    compact_context,
    estimate_entry_replay_tokens,
)
from opensquilla.session.compaction_lifecycle import compaction_effect_payload


def _make_entries(n: int, tokens_each: int = 100) -> list[dict]:
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"message {i} " + "x" * 50,
            "token_count": tokens_each,
        }
        for i in range(n)
    ]


def test_compaction_effect_payload_marks_automatic_noop_not_user_visible():
    payload = compaction_effect_payload(
        status="skipped",
        source="automatic",
        reason="within_compaction_budget",
    )

    assert payload == {
        "applied": False,
        "durability": "none",
        "skip_reason": "within_compaction_budget",
        "user_visible": False,
    }


def test_compaction_effect_payload_surfaces_non_benign_skip_reasons():
    for reason in ("coverage_blocked", "empty_summary", "no_safe_turn_boundary"):
        payload = compaction_effect_payload(
            status="skipped",
            source="automatic",
            reason=reason,
        )

        assert payload["applied"] is False
        assert payload["durability"] == "none"
        assert payload["skip_reason"] == reason
        assert payload["user_visible"] is True


def test_compaction_effect_payload_marks_durable_completion_applied():
    payload = compaction_effect_payload(status="completed", source="automatic")

    assert payload["applied"] is True
    assert payload["durability"] == "durable"
    assert payload["user_visible"] is True


@pytest.mark.asyncio
async def test_no_compaction_needed_small_context():
    entries = _make_entries(5, tokens_each=10)  # 50 tokens total
    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=10_000,  # huge window
        )
    )
    assert result.removed_count == 0
    assert result.kept_entries == entries
    assert result.summary_source == "skipped"
    assert result.skip_reason == "within_compaction_budget"


@pytest.mark.asyncio
async def test_compaction_occurs_when_over_budget():
    entries = _make_entries(20, tokens_each=200)  # 4000 tokens
    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=1000,  # tight window
        )
    )
    assert result.removed_count > 0
    assert result.summary != ""
    assert result.chunks_processed >= 1
    assert result.summary_source == "fallback"
    assert result.tokens_before == 4000
    assert result.tokens_after < result.tokens_before
    assert result.remaining_budget_tokens >= 0


def test_replay_token_estimate_uses_tool_payload_summary_not_raw_arguments():
    large_content = "x" * 80_000
    entry = {
        "role": "assistant",
        "content": "wrote file",
        "token_count": 1,
        "tool_calls": [
            {
                "type": "tool_use",
                "tool_use_id": "write-large",
                "name": "write_file",
                "input": {"path": "index.html", "content": large_content},
            }
        ],
        "reasoning_content": "private reasoning " + ("r" * 20_000),
    }

    tokens = estimate_entry_replay_tokens(entry)

    assert tokens < 500


@pytest.mark.asyncio
async def test_compaction_source_is_llm_when_all_chunks_use_llm(monkeypatch):
    calls: list[str] = []

    async def fake_llm(**kwargs):
        calls.append(kwargs["chunk_text"])
        return "LLM summary"

    monkeypatch.setattr("opensquilla.session.compaction.call_compaction_llm", fake_llm)
    entries = _make_entries(12, tokens_each=200)

    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=500,
            config=CompactionConfig(model="test/model", api_key="test-key"),
        )
    )

    assert calls
    assert result.removed_count > 0
    assert result.summary_source == "llm"


@pytest.mark.asyncio
async def test_compaction_source_is_mixed_when_llm_partly_falls_back(monkeypatch):
    responses = ["LLM summary", None]

    async def fake_llm(**kwargs):
        return responses.pop(0) if responses else "LLM summary"

    monkeypatch.setattr("opensquilla.session.compaction.call_compaction_llm", fake_llm)
    entries = _make_entries(12, tokens_each=200)

    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=500,
            config=CompactionConfig(model="test/model", api_key="test-key"),
        )
    )

    assert result.removed_count > 0
    assert result.summary_source == "mixed"


@pytest.mark.asyncio
async def test_compaction_keeps_recent_entries():
    entries = _make_entries(20, tokens_each=200)
    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=1000,
        )
    )
    # kept entries should be a tail of the original
    if result.kept_entries:
        last_kept = result.kept_entries[-1]
        assert last_kept in entries[-len(result.kept_entries) :]


@pytest.mark.asyncio
async def test_empty_entries():
    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=[],
            context_window_tokens=1000,
        )
    )
    assert result.removed_count == 0
    assert result.kept_entries == []
    assert result.summary == ""
    assert result.skip_reason == "no_entries"


@pytest.mark.asyncio
async def test_custom_config():
    entries = _make_entries(20, tokens_each=200)
    cfg = CompactionConfig(
        base_chunk_ratio=0.3,
        min_chunk_ratio=0.1,
        safety_margin=1.0,
        default_parts=3,
        identifier_policy="off",
    )
    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=500,
            config=cfg,
        )
    )
    assert result.removed_count > 0


@pytest.mark.asyncio
async def test_strict_identifier_policy_in_summary():
    entries = _make_entries(10, tokens_each=200)
    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=500,
            config=CompactionConfig(identifier_policy="strict"),
        )
    )
    if result.summary:
        assert "identifier" in result.summary.lower() or "IMPORTANT" in result.summary


@pytest.mark.asyncio
async def test_chunks_processed_count():
    entries = _make_entries(30, tokens_each=200)
    result = await compact_context(
        CompactionRequest(
            session_id="s1",
            entries=entries,
            context_window_tokens=500,
        )
    )
    assert result.chunks_processed >= 1


@pytest.mark.asyncio
async def test_call_compaction_llm_adds_openrouter_app_attribution(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "summary"}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url, *, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(
        "opensquilla.session.compaction.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    result = await call_compaction_llm(
        chunk_text="old conversation",
        identifier_instruction="",
        model="openai/gpt-4o-mini",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        timeout=10.0,
    )

    assert result == "summary"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://opensquilla.ai",
        "X-OpenRouter-Title": "OpenSquilla",
        "X-OpenRouter-Categories": "cli-agent,personal-agent",
    }


@pytest.mark.asyncio
async def test_call_compaction_llm_timeout_returns_none(monkeypatch) -> None:
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url, *, json, headers):
            raise TimeoutError("summary timed out")

    monkeypatch.setattr(
        "opensquilla.session.compaction.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    result = await call_compaction_llm(
        chunk_text="old conversation",
        identifier_instruction="",
        model="openai/gpt-4o-mini",
        api_key="test-key",
        timeout=0.01,
    )

    assert result is None


@pytest.mark.asyncio
async def test_custom_instructions_are_user_scoped_and_identifier_policy_stays_system(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "summary"}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url, *, json, headers):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "opensquilla.session.compaction.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    await call_compaction_llm(
        chunk_text="old conversation",
        identifier_instruction="Preserve exact IDs.",
        model="openai/gpt-4o-mini",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        timeout=10.0,
        custom_instructions="Focus on deployment decisions.",
    )

    messages = captured["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert "Preserve exact IDs." in messages[0]["content"]
    assert "Focus on deployment decisions." not in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "Focus on deployment decisions." in messages[1]["content"]
