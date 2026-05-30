"""PR7 — render_paused_outcome IM-fallback layout per spec §9.3.

These tests pin the layout the IM channel relies on (qualifier blocks,
reply-format example, default markers). The simpler smoke coverage in
``test_turn_finalizer_paused.py`` stays unchanged.
"""

from __future__ import annotations

from opensquilla.engine.turn_runner.turn_finalizer_stage import (
    render_paused_outcome,
)
from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaPaused,
    MetaResult,
)


def _paused(cfg: ClarifyStepConfig, intro: str = "") -> MetaResult:
    paused = MetaPaused(run_id="r1", step_id="collect", schema=cfg, intro=intro)
    return MetaResult(ok=False, paused=True, paused_payload=paused)


def test_int_field_with_range_renders_qualifier():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="days", type="int", required=True, min=1, max=14,
                         prompt="天数"),
        ),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "days" in text
    assert "(1-14)" in text
    assert "[必填]" in text


def test_int_field_only_min_renders_ge_qualifier():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="n", type="int", required=True, min=5),),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "(>=5)" in text


def test_enum_field_renders_choices_qualifier():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="budget", type="enum", required=False,
                         choices=("budget", "mid", "premium"),
                         default="mid", prompt="预算"),
        ),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "[budget|mid|premium]" in text
    assert "默认 mid" in text


def test_optional_field_without_default_renders_optional_flag():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="notes", type="string", required=False,
                         prompt="备注"),
        ),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "[可选]" in text


def test_string_max_chars_renders_qualifier():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="notes", type="string", required=True,
                         max_chars=100),
        ),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "(<=100 chars)" in text


def test_english_schema_renders_english_fallback_copy():
    cfg = ClarifyStepConfig(
        mode="form",
        intro="Some paper details are missing.",
        fields=(
            ClarifyField(
                name="topic",
                type="string",
                required=True,
                max_chars=200,
                prompt="Paper topic",
            ),
            ClarifyField(
                name="paper_mode",
                type="enum",
                required=False,
                choices=("FULL_MANUSCRIPT", "COMPACT_SKELETON"),
                default="COMPACT_SKELETON",
                prompt="Mode",
            ),
        ),
        cancel_keywords=("cancel", "stop"),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "Please reply with these fields:" in text
    assert "[required]" in text
    assert "(default COMPACT_SKELETON)" in text
    assert "Reply format example:" in text
    assert "Or reply cancel / stop to cancel." in text
    assert "请回复以下字段" not in text
    assert "必填" not in text


def test_format_example_block_present_for_required_fields():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="destination", type="string", required=True,
                         prompt="目的地"),
            ClarifyField(name="days", type="int", required=True, min=1, max=14,
                         prompt="天数"),
            ClarifyField(name="budget", type="enum", required=False,
                         choices=("budget", "mid"), default="mid"),
        ),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "回复格式示例" in text
    # Required fields appear in the sample block; optional ones do not
    # when at least one required field is present.
    assert "destination: <value>" in text
    assert "days: 1" in text
    assert "budget: mid" not in text


def test_format_example_falls_back_to_all_fields_when_no_required():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="note", type="string", required=False,
                         prompt="备注"),
        ),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "回复格式示例" in text
    assert "note: <value>" in text


def test_cancel_keywords_render_at_tail():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string", required=True),),
        cancel_keywords=("取消", "cancel"),
    )
    text = render_paused_outcome(_paused(cfg))
    assert "或回复 取消 / cancel 取消。" in text


def test_intro_override_takes_precedence():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string", required=True),),
        intro="default intro",
    )
    text = render_paused_outcome(_paused(cfg, intro="override intro"))
    assert text.startswith("override intro")
    assert "default intro" not in text


def test_non_paused_result_returns_final_text():
    result = MetaResult(ok=True, final_text="done", paused=False)
    assert render_paused_outcome(result) == "done"


def test_paused_without_payload_returns_final_text():
    result = MetaResult(ok=False, final_text="x", paused=True, paused_payload=None)
    assert render_paused_outcome(result) == "x"


def test_field_order_preserved():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="first", type="string", required=True),
            ClarifyField(name="second", type="string", required=True),
            ClarifyField(name="third", type="string", required=True),
        ),
    )
    text = render_paused_outcome(_paused(cfg))
    pos_first = text.find("1) first")
    pos_second = text.find("2) second")
    pos_third = text.find("3) third")
    assert 0 < pos_first < pos_second < pos_third
