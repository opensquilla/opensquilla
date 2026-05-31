"""Unit tests for the user_input step executor (PR3, design §8.1)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from opensquilla.skills.meta.executors.user_input import (
    _render_clarify_config,
    run_user_input_step,
)
from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaPaused,
    MetaStep,
)


def _cfg(skip_if: str = "") -> ClarifyStepConfig:
    return ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="destination", type="string", required=True),),
        skip_if=skip_if,
    )


def _step(cfg: ClarifyStepConfig) -> MetaStep:
    return MetaStep(
        id="collect",
        skill="collect",
        kind="user_input",
        clarify_config=cfg,
    )


@pytest.mark.asyncio
async def test_skip_if_true_returns_empty_without_pausing():
    """skip_if='True' (or any truthy expression) bypasses the pause."""
    dao = MagicMock()
    text = await run_user_input_step(
        _step(_cfg(skip_if="True")),
        inputs={"user_message": "hi", "collected": {}},
        outputs={},
        run_id="r1",
        session_id="S1",
        dao=dao,
        now=lambda: 1700000000.0,
    )
    assert text == ""
    dao.try_claim_awaiting.assert_not_called()


@pytest.mark.asyncio
async def test_no_skip_raises_meta_paused_after_successful_cas():
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True
    with pytest.raises(MetaPaused) as exc:
        await run_user_input_step(
            _step(_cfg()),
            inputs={"user_message": "hi", "collected": {}},
            outputs={"upstream": "some output"},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
        )
    assert exc.value.run_id == "r1"
    assert exc.value.step_id == "collect"
    assert exc.value.schema.fields[0].name == "destination"

    dao.try_claim_awaiting.assert_called_once()
    kwargs = dao.try_claim_awaiting.call_args.kwargs
    assert kwargs["run_id"] == "r1"
    assert kwargs["session_id"] == "S1"
    assert kwargs["step_id"] == "collect"
    assert json.loads(kwargs["inputs_json"])["user_message"] == "hi"
    assert json.loads(kwargs["step_outputs_json"])["upstream"] == "some output"
    assert kwargs["awaiting_since"] == 1700000000.0


def test_clarify_copy_renders_against_inputs_and_outputs():
    cfg = ClarifyStepConfig(
        mode="form",
        intro=(
            "{% if 'LANGUAGE: zh' in outputs.paper_collect %}"
            "请补充论文信息"
            "{% else %}"
            "Please add paper details"
            "{% endif %}"
        ),
        fields=(
            ClarifyField(
                name="topic",
                type="string",
                required=True,
                prompt=(
                    "{% if 'LANGUAGE: zh' in outputs.paper_collect %}"
                    "论文主题"
                    "{% else %}"
                    "Paper topic"
                    "{% endif %}"
                ),
            ),
        ),
    )

    rendered = _render_clarify_config(
        cfg,
        inputs={"user_message": "写一篇论文", "collected": {}},
        outputs={"paper_collect": "LANGUAGE: zh\nNEEDS_CLARIFICATION: yes"},
    )

    assert rendered.intro == "请补充论文信息"
    assert rendered.fields[0].prompt == "论文主题"
    assert rendered.fields[0].name == "topic"
    assert rendered.fields[0].required is True

    rendered_en = _render_clarify_config(
        cfg,
        inputs={"user_message": "write a paper", "collected": {}},
        outputs={"paper_collect": "LANGUAGE: en\nNEEDS_CLARIFICATION: yes"},
    )

    assert rendered_en.intro == "Please add paper details"
    assert rendered_en.fields[0].prompt == "Paper topic"


@pytest.mark.asyncio
async def test_english_pause_filters_cjk_cancel_keywords_and_prompts():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(
                name="topic",
                type="string",
                required=True,
                prompt="报告主题 / Report topic",
            ),
        ),
        intro="报告主题或决策场景还不够明确。",
        cancel_keywords=("算了", "取消", "cancel", "stop"),
    )
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True

    with pytest.raises(MetaPaused) as exc:
        await run_user_input_step(
            _step(cfg),
            inputs={
                "user_message": "Please research this.",
                "user_language": "en",
                "collected": {},
            },
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
        )

    paused = exc.value
    assert paused.language == "en"
    assert paused.schema.intro == (
        "A few required details are still missing. Please provide the fields "
        "below so I can continue."
    )
    assert paused.schema.fields[0].prompt == "Report topic"
    assert paused.schema.cancel_keywords == ("cancel", "stop")


@pytest.mark.asyncio
async def test_cas_failure_does_not_raise_meta_paused():
    """When the DAO rejects the claim, the executor signals a normal failure
    by raising RuntimeError. The orchestrator treats it as a regular step
    failure — on_failure substitute may fire (design §10)."""
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = False
    with pytest.raises(RuntimeError, match="awaiting claim rejected"):
        await run_user_input_step(
            _step(_cfg()),
            inputs={"user_message": "hi", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
        )


@pytest.mark.asyncio
async def test_skip_if_uses_inputs_and_outputs_context():
    """Verify Jinja context wiring matches the rest of the meta-skill engine."""
    dao = MagicMock()
    cfg = _cfg(skip_if='"done" in outputs.upstream')
    text = await run_user_input_step(
        _step(cfg),
        inputs={"user_message": "hi", "collected": {}},
        outputs={"upstream": "done with prep"},
        run_id="r1",
        session_id="S1",
        dao=dao,
        now=lambda: 1700000000.0,
    )
    assert text == ""
    dao.try_claim_awaiting.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_error_propagates_unchanged():
    """If the DAO call is cancelled mid-call, the executor must not swallow
    the CancelledError — the scheduler relies on it to tear down siblings.

    `try_claim_awaiting` is a SYNCHRONOUS method on MetaRunWriter; the
    executor wraps it with asyncio.to_thread. We simulate the raise by
    giving the MagicMock a sync `side_effect`."""
    dao = MagicMock()
    dao.try_claim_awaiting = MagicMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await run_user_input_step(
            _step(_cfg()),
            inputs={"user_message": "hi", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
        )
