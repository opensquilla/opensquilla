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
