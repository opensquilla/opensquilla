"""Unit tests for the user_input step executor (PR3, design §8.1)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from opensquilla.skills.meta.executors.user_input import (
    _deterministic_upstream_prefill,
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
async def test_pause_uses_explicit_localized_intro_and_prompts():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(
                name="topic",
                type="string",
                required=True,
                prompt="主题 / Topic",
                prompt_by_language={"zh": "主题", "en": "Topic"},
            ),
        ),
        intro="补充信息 / Add details",
        intro_by_language={
            "zh": "请补充信息。",
            "en": "Please add details.",
        },
    )

    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True
    with pytest.raises(MetaPaused) as zh_exc:
        await run_user_input_step(
            _step(cfg),
            inputs={"user_message": "写一份报告", "user_language": "zh", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
        )

    assert zh_exc.value.schema.intro == "请补充信息。"
    assert zh_exc.value.schema.fields[0].prompt == "主题"

    with pytest.raises(MetaPaused) as en_exc:
        await run_user_input_step(
            _step(cfg),
            inputs={"user_message": "write a report", "user_language": "en", "collected": {}},
            outputs={},
            run_id="r2",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000001.0,
        )

    assert en_exc.value.schema.intro == "Please add details."
    assert en_exc.value.schema.fields[0].prompt == "Topic"


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

    `try_claim_awaiting` is a SYNCHRONOUS method on MetaRunWriter. We
    simulate the raise by giving the MagicMock a sync `side_effect`."""
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


# ── Step (c): pre-fill scan ──


def _cfg_with_nl_extract(*fields: ClarifyField) -> ClarifyStepConfig:
    """Schema variant with ``nl_extract`` enabled for prefill tests."""
    return ClarifyStepConfig(
        mode="form",
        fields=fields or (
            ClarifyField(name="destination", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
        nl_extract=True,
    )


def _llm_returning(payload):
    """Build a fake llm_chat that yields ``payload`` (dict → JSON, str passthrough)."""
    if isinstance(payload, dict):
        payload = json.dumps(payload)

    async def _chat(_system: str, _user: str) -> str:
        return payload

    return _chat


@pytest.mark.asyncio
async def test_prefill_scan_seeds_awaiting_filled_with_known_values() -> None:
    """When ``llm_chat`` and ``prefill_context`` are wired, the
    executor must run a single NL extract pass over the context
    BEFORE claiming the awaiting state, and merge any high-confidence
    values into ``awaiting_filled_json``. The user must still confirm
    via the surface, so MetaPaused still fires."""
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True
    chat = _llm_returning({
        "intent": "FILL",
        "fields": {"destination": "Tokyo"},
        "ambiguous_fields": [{"name": "days", "reason": "duration not stated"}],
        "unknown_mentions": [],
    })
    with pytest.raises(MetaPaused):
        await run_user_input_step(
            _step(_cfg_with_nl_extract()),
            inputs={"user_message": "plan our Tokyo trip", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
            llm_chat=chat,
            prefill_context={
                "original_user_message": "plan our Tokyo trip",
            },
        )
    kwargs = dao.try_claim_awaiting.call_args.kwargs
    filled = json.loads(kwargs["awaiting_filled_json"])
    assert filled["destination"] == "Tokyo", (
        "high-confidence prefill must seed awaiting_filled_json"
    )
    audit = filled.get("__prefill_audit__")
    assert audit, "prefill audit payload must be present"
    assert audit["source"] == "auto_prefill"
    assert "destination" in audit["fields"]
    # Ambiguous fields must NOT be silently pre-filled — the user
    # still has to answer those.
    assert "days" not in filled
    ambiguous = {a["name"] for a in audit["ambiguous"]}
    assert "days" in ambiguous


@pytest.mark.asyncio
async def test_prefill_scan_ignores_empty_sentinel_from_catch_all_field() -> None:
    """Prefill runs before the user has answered, so an extractor that follows
    a catch-all prompt's empty-input instruction must not make ``(empty)`` look
    like a real user confirmation."""
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True
    chat = _llm_returning({
        "intent": "FILL",
        "fields": {"review": "(empty)"},
        "ambiguous_fields": [],
        "unknown_mentions": [],
    })
    cfg = _cfg_with_nl_extract(
        ClarifyField(
            name="review",
            type="string",
            required=True,
            prompt=(
                "The user's verbatim reply about the script draft. "
                "If the user's reply is empty or pure whitespace, emit \"(empty)\"."
            ),
        ),
    )

    with pytest.raises(MetaPaused) as exc:
        await run_user_input_step(
            _step(cfg),
            inputs={"user_message": "生成一个短剧，啥都行", "collected": {}},
            outputs={"script_draft": "draft text"},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
            llm_chat=chat,
            prefill_context={
                "original_user_message": "生成一个短剧，啥都行",
                "prior_step_outputs": {"script_draft": "draft text"},
            },
        )

    kwargs = dao.try_claim_awaiting.call_args.kwargs
    filled = json.loads(kwargs["awaiting_filled_json"])
    assert "review" not in filled
    audit = filled.get("__prefill_audit__")
    assert audit
    assert "review" not in audit.get("fields", [])
    assert audit.get("dropped_empty_sentinels") == ["review"]
    assert exc.value.confirmed_fields is None


def test_deterministic_prefill_skips_empty_list_and_unspecified_sentinels() -> None:
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="dimensions", type="string", required=True),
            ClarifyField(
                name="time_window",
                type="enum",
                choices=("LAST_WEEK", "LAST_MONTH", "LAST_QUARTER"),
            ),
        ),
    )

    hits = _deterministic_upstream_prefill(
        cfg,
        {
            "prior_step_outputs": {
                "preferences": "DIMENSIONS: []\nTIME_WINDOW: UNSPECIFIED",
            },
        },
    )

    assert hits == {}


@pytest.mark.asyncio
async def test_prefill_scan_skipped_when_no_llm_chat_wired() -> None:
    """Backwards compatibility: callers that don't pass ``llm_chat``
    must see exactly the legacy behaviour — no prefill, no audit
    payload, ``awaiting_filled_json`` is the empty object."""
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True
    with pytest.raises(MetaPaused):
        await run_user_input_step(
            _step(_cfg_with_nl_extract()),
            inputs={"user_message": "hi", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
            # llm_chat=None is the default
        )
    kwargs = dao.try_claim_awaiting.call_args.kwargs
    filled = json.loads(kwargs["awaiting_filled_json"])
    assert filled == {}


@pytest.mark.asyncio
async def test_prefill_scan_skipped_when_nl_extract_false() -> None:
    """A clarify schema that opts out of NL extract must NOT trigger
    a prefill scan even if ``llm_chat`` is wired — operator declared
    "this step uses deterministic parsing only" and must be honoured."""
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="destination", type="string", required=True),),
        nl_extract=False,
    )
    chat_called = {"count": 0}

    async def counting_chat(_s, _u):
        chat_called["count"] += 1
        return "{}"

    with pytest.raises(MetaPaused):
        await run_user_input_step(
            _step(cfg),
            inputs={"user_message": "Tokyo!", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
            llm_chat=counting_chat,
            prefill_context={"original_user_message": "Tokyo!"},
        )
    assert chat_called["count"] == 0, "nl_extract=false must skip prefill"


@pytest.mark.asyncio
async def test_prefill_scan_failure_falls_back_to_pause() -> None:
    """A pre-fill LLM call that raises must downgrade silently to
    "no prefill" — the resolver still reaches MetaPaused so the user
    can answer normally. A regression that surfaced the LLM error
    would block legitimate clarify runs whenever the upstream
    provider hiccupped."""
    dao = MagicMock()
    dao.try_claim_awaiting.return_value = True

    async def raising_chat(_s, _u):
        raise RuntimeError("provider blew up")

    with pytest.raises(MetaPaused):
        await run_user_input_step(
            _step(_cfg_with_nl_extract()),
            inputs={"user_message": "Tokyo!", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=dao,
            now=lambda: 1700000000.0,
            llm_chat=raising_chat,
            prefill_context={"original_user_message": "Tokyo!"},
        )
    kwargs = dao.try_claim_awaiting.call_args.kwargs
    filled = json.loads(kwargs["awaiting_filled_json"])
    # No real fields landed; only the audit error trace.
    assert "destination" not in filled
    audit = filled.get("__prefill_audit__")
    assert audit, "prefill audit must record the failure"
    # ``extract`` catches the LLM exception itself and surfaces it
    # through ``errors``; outer-level guard captures truly raised
    # exceptions under ``error``. Either signal is acceptable evidence.
    assert audit.get("errors") or audit.get("error")


@pytest.mark.asyncio
async def test_prefill_scan_passes_awaiting_filled_json_to_dao() -> None:
    """The executor must always pass ``awaiting_filled_json`` to the
    DAO. The previous behaviour of swallowing ``TypeError`` and
    retrying with the legacy signature silently dropped prefill on the
    floor when a stub didn't keep up with the contract; that fallback
    is gone. A DAO that doesn't accept the kwarg is now treated as a
    real signature mismatch."""
    modern_dao = MagicMock()
    captured: dict = {}

    def claim(**kwargs):
        captured.update(kwargs)
        return True

    modern_dao.try_claim_awaiting.side_effect = claim
    chat = _llm_returning({
        "intent": "FILL",
        "fields": {"destination": "Tokyo"},
        "ambiguous_fields": [],
        "unknown_mentions": [],
    })
    with pytest.raises(MetaPaused):
        await run_user_input_step(
            _step(_cfg_with_nl_extract()),
            inputs={"user_message": "Tokyo trip", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=modern_dao,
            now=lambda: 1700000000.0,
            llm_chat=chat,
            prefill_context={"original_user_message": "Tokyo trip"},
        )
    # Modern claim signature receives the prefill JSON unconditionally.
    assert "awaiting_filled_json" in captured
    filled = json.loads(captured["awaiting_filled_json"])
    assert filled.get("destination") == "Tokyo"


@pytest.mark.asyncio
async def test_prefill_scan_propagates_dao_typeerror_now_that_fallback_is_gone() -> None:
    """If a misconfigured DAO doesn't accept ``awaiting_filled_json``,
    we surface the ``TypeError`` immediately rather than silently
    retrying with the legacy signature. Live traffic must never
    silently drop prefill — partial migrations now fail loud."""
    busted_dao = MagicMock()

    def claim(**kwargs):
        # Simulate the old MetaRunWriter signature: reject the new kwarg.
        if "awaiting_filled_json" in kwargs:
            raise TypeError("unexpected keyword argument 'awaiting_filled_json'")
        return True

    busted_dao.try_claim_awaiting.side_effect = claim
    chat = _llm_returning({
        "intent": "FILL",
        "fields": {"destination": "Tokyo"},
        "ambiguous_fields": [],
        "unknown_mentions": [],
    })
    with pytest.raises(TypeError):
        await run_user_input_step(
            _step(_cfg_with_nl_extract()),
            inputs={"user_message": "Tokyo trip", "collected": {}},
            outputs={},
            run_id="r1",
            session_id="S1",
            dao=busted_dao,
            now=lambda: 1700000000.0,
            llm_chat=chat,
            prefill_context={"original_user_message": "Tokyo trip"},
        )
