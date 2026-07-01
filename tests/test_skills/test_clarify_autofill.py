from __future__ import annotations

import json

import pytest

from opensquilla.skills.meta.clarify_autofill import (
    autofill_required_clarify_fields,
)
from opensquilla.skills.meta.types import ClarifyField, ClarifyStepConfig


@pytest.mark.asyncio
async def test_autofill_fills_missing_required_fields_with_llm() -> None:
    schema = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="age", type="int", required=True, min=6, max=12),
            ClarifyField(
                name="budget",
                type="enum",
                required=True,
                choices=("50 元以内", "100 元以内", "200 元以内"),
            ),
            ClarifyField(name="topic", type="string", required=False),
        ),
    )

    async def fake_chat(system: str, user: str) -> str:
        assert "Return only one JSON object" in system
        assert "age" in user
        return json.dumps({"age": 9, "budget": "100 元以内"}, ensure_ascii=False)

    filled, completed = await autofill_required_clarify_fields(
        schema=schema,
        filled_fields={"topic": "磁力迷宫"},
        user_message="给 9 岁孩子做科学项目，预算 100 元以内。",
        clarify_reply="",
        llm_chat=fake_chat,
    )

    assert completed == {"age": 9, "budget": "100 元以内"}
    assert filled == {"topic": "磁力迷宫", "age": 9, "budget": "100 元以内"}


@pytest.mark.asyncio
async def test_autofill_can_infer_optional_fields_for_empty_form_submission() -> None:
    schema = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="topic", type="string", required=True),
            ClarifyField(
                name="age_band",
                type="enum",
                required=True,
                choices=("PRE_K", "EARLY_GRADE", "TWEEN", "TEEN"),
            ),
            ClarifyField(
                name="deadline_days",
                type="int",
                required=False,
                min=0,
                max=365,
                default=14,
            ),
            ClarifyField(
                name="language",
                type="enum",
                required=False,
                choices=("en", "zh", "mixed"),
                default="mixed",
            ),
        ),
    )

    async def fake_chat(_system: str, user: str) -> str:
        payload = json.loads(user)
        target_names = {
            field["name"] for field in payload["fields_to_infer"]
        }
        assert target_names == {
            "topic", "age_band", "deadline_days", "language",
        }
        return json.dumps(
            {
                "topic": "磁力迷宫",
                "age_band": "EARLY_GRADE",
                "deadline_days": 7,
                "language": "zh",
            },
            ensure_ascii=False,
        )

    filled, completed = await autofill_required_clarify_fields(
        schema=schema,
        filled_fields={"deadline_days": 14, "language": "mixed"},
        user_message="给 8 岁孩子做一个磁力迷宫项目。",
        clarify_reply="",
        llm_chat=fake_chat,
        infer_optional_fields=True,
    )

    assert completed == {
        "topic": "磁力迷宫",
        "age_band": "EARLY_GRADE",
        "deadline_days": 7,
        "language": "zh",
    }
    assert filled == completed


@pytest.mark.asyncio
async def test_autofill_replaces_uninformative_required_answers() -> None:
    schema = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="audience", type="string", required=True),
            ClarifyField(name="budget", type="string", required=True),
        ),
    )

    async def fake_chat(_system: str, _user: str) -> str:
        return '{"budget": "100 元以内"}'

    filled, completed = await autofill_required_clarify_fields(
        schema=schema,
        filled_fields={"audience": "老师", "budget": "都可以"},
        user_message="给小学生做一个科学项目。",
        clarify_reply="budget: 都可以",
        llm_chat=fake_chat,
    )

    assert completed == {"budget": "100 元以内"}
    assert filled == {"audience": "老师", "budget": "100 元以内"}


@pytest.mark.asyncio
async def test_autofill_uses_safe_fallback_without_llm() -> None:
    schema = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(
                name="budget",
                type="enum",
                required=True,
                choices=("50 元以内", "100 元以内"),
            ),
            ClarifyField(name="age", type="int", required=True, min=6, max=12),
        ),
    )

    filled, completed = await autofill_required_clarify_fields(
        schema=schema,
        filled_fields={},
        user_message="",
        clarify_reply="",
        llm_chat=None,
    )

    assert completed == {"budget": "50 元以内", "age": 6}
    assert filled == {"budget": "50 元以内", "age": 6}


@pytest.mark.asyncio
async def test_autofill_string_fallback_follows_english_user_message() -> None:
    schema = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="audience", type="string", required=True),
        ),
    )

    filled, completed = await autofill_required_clarify_fields(
        schema=schema,
        filled_fields={},
        user_message="Please create a concise launch plan.",
        clarify_reply="",
        llm_chat=None,
    )

    assert completed == {"audience": "Automatically inferred from context"}
    assert filled == {"audience": "Automatically inferred from context"}
