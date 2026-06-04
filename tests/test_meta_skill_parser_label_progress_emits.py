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


def test_parser_label_optional():
    plan = parse_meta_plan(_spec_with([
        {"id": "intake", "kind": "llm_chat"},
    ]))
    assert plan is not None
    assert plan.steps[0].label == ""
