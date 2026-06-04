"""MetaStep 暴露 label 与 progress_emits，默认安全回退。"""

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
