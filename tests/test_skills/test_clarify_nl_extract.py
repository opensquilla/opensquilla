"""Unit tests for the nl_extract opt-in LLM extractor (PR9, design §5.5)."""

from __future__ import annotations

import json

import pytest

from opensquilla.skills.meta.clarify_nl_extract import NLExtractResult, extract
from opensquilla.skills.meta.types import ClarifyField, ClarifyStepConfig


def _schema(*fields: ClarifyField) -> ClarifyStepConfig:
    return ClarifyStepConfig(mode="form", fields=tuple(fields), nl_extract=True)


def _llm_returning(payload: str | dict):
    """Build a mock llm_chat that returns `payload` (str or dict)."""
    if isinstance(payload, dict):
        payload = json.dumps(payload)

    async def _chat(system: str, user: str) -> str:
        # Defensive: assert the system prompt includes our scoping markers.
        assert "STRICT JSON" in system
        assert "<user_reply>" in user
        return payload

    return _chat


def _llm_raising(exc: Exception):
    async def _chat(system: str, user: str) -> str:
        raise exc

    return _chat


# ── happy path: single-shot extraction of multiple fields ──

@pytest.mark.asyncio
async def test_extract_multiple_fields_natural_language():
    """The flagship case: '我们俩去东京玩 5 天预算 mid' fills all four fields."""
    fields = (
        ClarifyField(name="destination", type="string", required=True),
        ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ClarifyField(name="party_size", type="int", required=True, min=1, max=20),
        ClarifyField(name="budget", type="enum",
                     choices=("budget", "mid", "premium"), default="mid"),
    )
    schema = _schema(*fields)
    llm = _llm_returning({
        "destination": "Tokyo",
        "days": 5,
        "party_size": 2,
        "budget": "mid",
    })

    result = await extract(
        reply_text="我们俩去东京玩 5 天预算 mid",
        schema=schema,
        active_fields=fields,
        llm_chat=llm,
    )

    assert result.errors == []
    assert result.fields == {
        "destination": "Tokyo",
        "days": 5,
        "party_size": 2,
        "budget": "mid",
    }


@pytest.mark.asyncio
async def test_extract_partial_fields_only():
    """Model may omit fields it did not see — that's fine."""
    fields = (
        ClarifyField(name="destination", type="string", required=True),
        ClarifyField(name="notes", type="string", required=False),
    )
    schema = _schema(*fields)
    llm = _llm_returning({"destination": "Shanghai"})

    result = await extract(
        reply_text="去上海", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.errors == []
    assert result.fields == {"destination": "Shanghai"}


@pytest.mark.asyncio
async def test_extract_uses_trusted_context_for_references():
    """Replies like 'as above' should have bounded prior context available."""
    fields = (
        ClarifyField(name="accounts", type="string", required=True),
        ClarifyField(name="dimensions", type="string", required=True),
    )
    schema = _schema(*fields)

    async def _chat(system: str, user: str) -> str:
        assert "<trusted_context>" in user
        assert "月之暗面" in user
        assert "全部关注" in user
        assert "Use <trusted_context>" in system
        return json.dumps({
            "accounts": "月之暗面, minimax",
            "dimensions": "PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS",
        })

    result = await extract(
        reply_text="账号上面已经提过了，维度全部关注",
        schema=schema,
        active_fields=fields,
        llm_chat=_chat,
        context={
            "original_user_message": "盯一下月之暗面和minimax",
            "prior_step_outputs": {
                "preferences": "ACCOUNTS:\n  - 月之暗面\n  - minimax",
            },
        },
    )

    assert result.errors == []
    assert result.fields == {
        "accounts": "月之暗面, minimax",
        "dimensions": "PRICING, PRODUCT, LEADERSHIP, HIRING, NEWS",
    }


# ── key whitelist ──

@pytest.mark.asyncio
async def test_unknown_keys_silently_dropped():
    """Model output containing un-listed keys must not leak into fields."""
    fields = (ClarifyField(name="destination", type="string", required=True),)
    schema = _schema(*fields)
    llm = _llm_returning({
        "destination": "Tokyo",
        "secret_admin_flag": True,  # prompt injection attempt
        "evil_payload": "; DROP TABLE meta_skill_runs;",
    })

    result = await extract(
        reply_text="anything", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.errors == []
    assert result.fields == {"destination": "Tokyo"}


# ── validator reapplied ──

@pytest.mark.asyncio
async def test_int_field_out_of_range_rejected_even_from_llm():
    fields = (ClarifyField(name="days", type="int", required=True, min=1, max=14),)
    schema = _schema(*fields)
    llm = _llm_returning({"days": 99})

    result = await extract(
        reply_text="99 天", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.fields == {}
    assert any("max" in e.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_int_field_as_string_from_llm_still_coerced():
    """LLM that hallucinates strings for int fields gets coerced or rejected."""
    fields = (ClarifyField(name="days", type="int", required=True),)
    schema = _schema(*fields)
    llm = _llm_returning({"days": "five"})

    result = await extract(
        reply_text="five days",
        schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.fields == {}
    assert any("integer" in e.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_enum_field_invalid_choice_rejected():
    fields = (
        ClarifyField(name="budget", type="enum", required=True,
                     choices=("budget", "mid", "premium")),
    )
    schema = _schema(*fields)
    llm = _llm_returning({"budget": "luxury"})

    result = await extract(
        reply_text="luxury", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.fields == {}
    assert any("luxury" in e for e in result.errors)


# ── JSON parsing ──

@pytest.mark.asyncio
async def test_json_with_code_fence_stripped():
    """Models often wrap JSON in ```json … ``` despite instructions."""
    fields = (ClarifyField(name="destination", type="string", required=True),)
    schema = _schema(*fields)
    llm = _llm_returning('```json\n{"destination": "Kyoto"}\n```')

    result = await extract(
        reply_text="Kyoto", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.errors == []
    assert result.fields == {"destination": "Kyoto"}


@pytest.mark.asyncio
async def test_malformed_json_returns_error():
    fields = (ClarifyField(name="destination", type="string", required=True),)
    schema = _schema(*fields)
    llm = _llm_returning("not even close to JSON {")

    result = await extract(
        reply_text="x", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.fields == {}
    assert any("not valid JSON" in e for e in result.errors)


@pytest.mark.asyncio
async def test_non_object_json_returns_error():
    fields = (ClarifyField(name="destination", type="string", required=True),)
    schema = _schema(*fields)
    llm = _llm_returning('["Tokyo"]')  # array, not object

    result = await extract(
        reply_text="x", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.fields == {}
    assert any("JSON object" in e for e in result.errors)


@pytest.mark.asyncio
async def test_empty_llm_response_returns_error():
    fields = (ClarifyField(name="destination", type="string", required=True),)
    schema = _schema(*fields)
    llm = _llm_returning("")

    result = await extract(
        reply_text="x", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.fields == {}
    assert any("empty" in e.lower() for e in result.errors)


# ── LLM call failure ──

@pytest.mark.asyncio
async def test_llm_exception_logged_and_surfaced_as_error():
    fields = (ClarifyField(name="destination", type="string", required=True),)
    schema = _schema(*fields)
    llm = _llm_raising(RuntimeError("provider down"))

    result = await extract(
        reply_text="x", schema=schema, active_fields=fields, llm_chat=llm,
    )
    assert result.fields == {}
    assert any("provider down" in e for e in result.errors)


# ── chat mode: single-field whitelist ──

@pytest.mark.asyncio
async def test_chat_mode_single_active_field_only():
    """In chat mode, active_fields is one field; the LLM cannot fill others."""
    all_fields = (
        ClarifyField(name="destination", type="string", required=True),
        ClarifyField(name="days", type="int", required=True),
    )
    schema = ClarifyStepConfig(
        mode="chat", fields=all_fields, nl_extract=True,
    )
    # Chat-mode caller passes only the currently-asked field
    active = (all_fields[1],)
    llm = _llm_returning({
        "destination": "extra-attempt",  # SHOULD be dropped (not in active)
        "days": 7,
    })

    result = await extract(
        reply_text="差不多 7 天", schema=schema,
        active_fields=active, llm_chat=llm,
    )
    assert result.errors == []
    assert result.fields == {"days": 7}
    assert "destination" not in result.fields


# ── result type ──

def test_nl_extract_result_is_dataclass_with_two_fields():
    r = NLExtractResult(fields={"x": 1}, errors=["e"])
    assert r.fields == {"x": 1}
    assert r.errors == ["e"]
