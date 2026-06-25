"""Smoke test for the collected: {} namespace introduced in PR1."""

from __future__ import annotations

from opensquilla.skills.meta.inputs import make_meta_inputs


def test_make_meta_inputs_includes_empty_collected_namespace():
    inputs = make_meta_inputs(user_message="hello", system_prompt="sp")
    assert "collected" in inputs
    assert inputs["collected"] == {}
    assert inputs["user_language"] == "en"


def test_make_meta_inputs_detects_chinese_user_language():
    inputs = make_meta_inputs(user_message="帮我写一篇论文")
    assert inputs["user_language"] == "zh"


def test_make_meta_inputs_collected_is_mutable_dict_not_shared():
    """Two calls return separate dicts so callers can mutate independently."""
    a = make_meta_inputs(user_message="x")
    b = make_meta_inputs(user_message="y")
    a["collected"]["foo"] = "bar"
    assert b["collected"] == {}


def test_make_meta_inputs_surfaces_supplied_audience_and_language_preferences():
    inputs = make_meta_inputs(
        user_message="Please build a launch brief.",
        audience="executive team",
        language="zh-CN",
        preferences={
            "preferred_language": "zh-CN",
            "audience_profile": "executive team",
            "empty": "",
        },
    )

    assert inputs["audience"] == "executive team"
    assert inputs["language"] == "zh-CN"
    assert inputs["preferences"] == {
        "preferred_language": "zh-CN",
        "audience_profile": "executive team",
        "audience": "executive team",
        "language": "zh-CN",
    }
    assert inputs["user_language"] == "zh"
    assert "Simplified Chinese" in inputs["language_instruction"]


def test_meta_input_overrides_ignore_generic_preferences_metadata():
    from opensquilla.skills.meta.inputs import meta_input_overrides_from_metadata

    overrides = meta_input_overrides_from_metadata({
        "preferences": {"briefing_depth": "compact"},
        "audience": "everyone",
        "language": "fr",
        "preferred_language": "de",
    })

    assert overrides == {}


def test_meta_input_overrides_accept_explicit_meta_preferences_only():
    from opensquilla.skills.meta.inputs import meta_input_overrides_from_metadata

    overrides = meta_input_overrides_from_metadata({
        "meta_audience": "executive team",
        "meta_language": "zh-CN",
        "meta_preferences": {
            "api_token": "sk-secret-12345678",
            "briefing_depth": "deep",
            "auth_header": "Bearer abc",
        },
    })

    assert overrides == {
        "audience": "executive team",
        "language": "zh-CN",
        "preferences": {"briefing_depth": "deep"},
    }


def test_meta_input_overrides_filters_secret_and_large_text_fields():
    from opensquilla.skills.meta.inputs import meta_input_overrides_from_metadata

    assert meta_input_overrides_from_metadata({
        "meta_audience": "sk-secret-12345678",
        "meta_language": "Bearer abcdef",
    }) == {}
    assert meta_input_overrides_from_metadata({
        "meta_audience": {"team": "exec"},
        "meta_language": ["zh-CN"],
    }) == {}

    overrides = meta_input_overrides_from_metadata({
        "meta_audience": "x" * 600,
        "meta_language": "zh-CN" + ("x" * 200),
    })
    assert len(overrides["audience"]) <= 256
    assert len(overrides["language"]) <= 64
