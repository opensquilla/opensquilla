"""Tests for creator/proposer.py (fill_slots, assemble) + patterns."""

from __future__ import annotations

import json

import pytest

from opensquilla.skills.creator.patterns.schemas import (
    FanOutMergeSlots,
    SequentialSlots,
)
from opensquilla.skills.creator.proposer import meta_skill_assemble


def test_sequential_slots_min_steps() -> None:
    with pytest.raises(ValueError):
        SequentialSlots(
            name="test-x", description="d" * 30, triggers=["t"],
            steps=[{"id": "a", "skill": "x", "task": "t"}],
        )


def test_sequential_with_keys_default_empty() -> None:
    slots = SequentialSlots(
        name="test-x", description="d" * 30, triggers=["t"],
        steps=[
            {"id": "a", "skill": "summarize", "task": "do thing"},
            {"id": "b", "skill": "memory", "task": "save"},
        ],
    )
    assert slots.steps[0].with_keys == {}


def test_fanout_tail_optional() -> None:
    slots = FanOutMergeSlots(
        name="test-x", description="d" * 30, triggers=["t"],
        branches=[
            {"id": "a", "skill": "weather", "task": "t"},
            {"id": "b", "skill": "summarize", "task": "t"},
        ],
        merge={"id": "m", "skill": "summarize", "task": "t"},
    )
    assert slots.tail is None


def test_meta_skill_assemble_p1() -> None:
    slots = {
        "name": "test-t1", "description": "d" * 30, "triggers": ["go"],
        "steps": [
            {"id": "a", "skill": "summarize", "task": "extract", "with_keys": {}},
            {"id": "b", "skill": "memory", "task": "store", "with_keys": {}},
        ],
        "meta_priority": 50,
    }
    md = meta_skill_assemble("p1_sequential", json.dumps(slots))
    assert "name: test-t1" in md
    assert "skill: summarize" in md
    assert "skill: memory" in md
    assert "depends_on: [a]" in md


def test_meta_skill_assemble_rejects_invalid_slots() -> None:
    with pytest.raises(ValueError):
        meta_skill_assemble("p1_sequential", '{"name": "x"}')


def test_meta_skill_fill_slots_with_stub_llm(monkeypatch) -> None:
    from opensquilla.skills.creator import proposer

    call_log: list[str] = []
    canned_response = json.dumps({
        "name": "synth-pipeline",
        "description": "Synthetic pipeline that does X then Y. Sample for testing fill_slots flow.",
        "meta_priority": 50,
        "triggers": ["synth test"],
        "steps": [
            {"id": "a", "skill": "summarize", "task": "process", "with_keys": {}},
            {"id": "b", "skill": "memory", "task": "save", "with_keys": {}},
        ],
    })

    def stub_llm(prompt: str, **_kwargs) -> str:
        call_log.append(prompt)
        return canned_response

    monkeypatch.setattr(proposer, "_call_llm_for_slots", stub_llm)

    result = proposer.meta_skill_fill_slots(
        pattern_id="p1_sequential",
        history_summary="(no history)",
        user_intent="process docs then save",
    )
    data = json.loads(result)
    assert data["name"] == "synth-pipeline"
    assert len(call_log) == 1
    # Catalog injection: skill names must appear in prompt
    assert "summarize" in call_log[0]


def test_creator_package_import_registers_tools() -> None:
    """C1 regression: importing the creator package must register both tools
    in the default ToolRegistry. Phase 1 cross-task review found that the
    @tool decorators only run when the module is imported — production code
    must import opensquilla.skills.creator somewhere in the meta-skill branch."""
    import importlib

    import opensquilla.skills.creator
    importlib.reload(opensquilla.skills.creator)

    from opensquilla.tools.registry import get_default_registry
    names = get_default_registry().list_names()
    meta_names = sorted(n for n in names if n.startswith("meta"))
    assert "meta_skill_assemble" in names, (
        f"meta_skill_assemble not registered; got: {meta_names}"
    )
    assert "meta_skill_fill_slots" in names, "meta_skill_fill_slots not registered"


def test_meta_skill_fill_slots_retries_once_on_validation_error(monkeypatch) -> None:
    from opensquilla.skills.creator import proposer

    responses = iter([
        '{"name": "bad"}',  # missing fields → ValidationError
        json.dumps({
            "name": "synth-pipeline",
            "description": "Synthetic pipeline that does X then Y. Sample.",
            "meta_priority": 50,
            "triggers": ["synth test"],
            "steps": [
                {"id": "a", "skill": "summarize", "task": "process", "with_keys": {}},
                {"id": "b", "skill": "memory", "task": "save", "with_keys": {}},
            ],
        }),
    ])
    prompts: list[str] = []

    def stub_llm(prompt: str, **_kwargs) -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(proposer, "_call_llm_for_slots", stub_llm)

    result = proposer.meta_skill_fill_slots(
        pattern_id="p1_sequential",
        history_summary="(no history)",
        user_intent="process docs then save",
    )
    data = json.loads(result)
    assert data["name"] == "synth-pipeline"
    assert len(prompts) == 2
    # Retry prompt must include the ValidationError feedback
    assert "failed schema validation" in prompts[1] or "errors" in prompts[1]
