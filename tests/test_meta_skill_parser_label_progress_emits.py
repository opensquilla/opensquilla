"""MetaStep 暴露 label 与 progress_emits，默认安全回退。"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
from opensquilla.skills.meta.types import MetaStep


def test_meta_step_default_label_empty():
    s = MetaStep(id="intake", skill="intake")
    assert s.label == ""
    assert s.progress_emits is True


def test_meta_step_explicit_label():
    s = MetaStep(id="intake", skill="intake", label="意图提取")
    assert s.label == "意图提取"


def test_meta_step_progress_emits_off():
    s = MetaStep(id="tool", skill="tool", kind="tool_call",
                 tool="memory_save", progress_emits=False)
    assert s.progress_emits is False


@dataclass
class _FakeSpec:
    name: str = "fake-meta"
    kind: str = "meta"
    composition_raw: dict[str, Any] = field(default_factory=dict)
    triggers: list[str] = field(default_factory=list)
    meta_priority: int = 0
    content: str = ""
    final_text_mode: str = "auto"
    request_template: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    eval_prompts: list[dict[str, Any]] = field(default_factory=list)
    preference_keys: list[str] = field(default_factory=list)
    policy_tags: list[str] = field(default_factory=list)


def _spec_with(steps):
    return _FakeSpec(composition_raw={"steps": steps})


def test_parser_reads_label():
    plan = parse_meta_plan(_spec_with([
        {"id": "intake", "kind": "llm_chat", "label": "意图提取"},
    ]))
    assert plan is not None
    assert plan.steps[0].label == "意图提取"


def test_parser_reads_progress_emits_false():
    plan = parse_meta_plan(_spec_with([
        {"id": "tool", "kind": "tool_call", "tool": "memory_save",
         "progress_emits": False},
    ]))
    assert plan is not None
    assert plan.steps[0].progress_emits is False


def test_parser_defaults_tool_call_progress_emits_false():
    plan = parse_meta_plan(_spec_with([
        {"id": "tool", "kind": "tool_call", "tool": "memory_save"},
    ]))
    assert plan is not None
    assert plan.steps[0].progress_emits is False


def test_parser_label_must_be_string():
    with pytest.raises(MetaPlanError, match="label"):
        parse_meta_plan(_spec_with([
            {"id": "intake", "kind": "llm_chat", "label": 123},
        ]))


def test_parser_progress_emits_must_be_bool():
    with pytest.raises(MetaPlanError, match="progress_emits"):
        parse_meta_plan(_spec_with([
            {"id": "intake", "kind": "llm_chat", "progress_emits": "yes"},
        ]))


def test_parser_label_optional_uses_readable_step_id_fallback():
    plan = parse_meta_plan(_spec_with([
        {"id": "source_digest", "kind": "llm_chat"},
    ]))
    assert plan is not None
    assert plan.steps[0].label == "Source Digest"
    assert plan.steps[0].label_by_language["en"] == "Source Digest"


def test_parser_reads_request_template_from_spec():
    spec = _spec_with([
        {"id": "intake", "kind": "llm_chat"},
    ])
    spec.request_template = {
        "outcome": "Decision memo",
        "fields": [
            {"name": "decision_criteria", "required": True},
            {"name": "time_window", "required": False, "default": "next 30 days"},
        ],
        "assumptions": ["Use public evidence only"],
    }

    plan = parse_meta_plan(spec)

    assert plan is not None
    assert plan.request_template["outcome"] == "Decision memo"
    assert plan.request_template["fields"][0]["name"] == "decision_criteria"


def test_parser_reads_output_contract_from_spec():
    spec = _spec_with([
        {"id": "final", "kind": "llm_chat"},
    ])
    spec.output_contract = {
        "required_sections": ["Recommendation", "Evidence"],
        "assumptions": ["Criteria inferred from request"],
        "unverified": ["Pricing may change"],
        "artifacts": [{"name": "decision_memo.md", "required": False}],
    }

    plan = parse_meta_plan(spec)

    assert plan is not None
    assert plan.output_contract["required_sections"] == ["Recommendation", "Evidence"]
    assert plan.output_contract["artifacts"][0]["name"] == "decision_memo.md"


def test_parser_reads_eval_preference_and_policy_metadata_from_spec():
    spec = _spec_with([
        {"id": "final", "kind": "llm_chat"},
    ])
    spec.eval_prompts = [{
        "name": "happy-path",
        "prompt": "Write a decision memo for project X",
        "rubric": ["Recommendation", "Evidence"],
    }]
    spec.preference_keys = ["preferred_language", "briefing_depth"]
    spec.policy_tags = ["public-data-only", "no-pii"]

    plan = parse_meta_plan(spec)

    assert plan is not None
    assert plan.eval_prompts[0]["name"] == "happy-path"
    assert plan.preference_keys == ("preferred_language", "briefing_depth")
    assert plan.policy_tags == ("public-data-only", "no-pii")
