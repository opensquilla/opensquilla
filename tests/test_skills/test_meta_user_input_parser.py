"""Parser validation tests for the new user_input step kind (PR1, design §5.2)."""

from __future__ import annotations

import pytest

from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
from opensquilla.skills.meta.types import ClarifyStepConfig
from opensquilla.skills.types import SkillLayer, SkillSpec


def _spec(steps: list[dict]) -> SkillSpec:
    """Build a minimal meta-kind SkillSpec for parser tests."""
    return SkillSpec(
        name="test-skill",
        description="",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=["test trigger"],
        content="",
        kind="meta",
        meta_priority=0,
        composition_raw={"steps": steps},
    )


def test_user_input_kind_is_accepted_by_parser():
    spec = _spec([
        {
            "id": "collect",
            "kind": "user_input",
            "skill": "collect",
            "clarify": {
                "mode": "form",
                "fields": [
                    {"name": "destination", "type": "string", "required": True},
                ],
            },
        },
    ])
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.steps[0].kind == "user_input"
    assert isinstance(plan.steps[0].clarify_config, ClarifyStepConfig)
    assert plan.steps[0].clarify_config.fields[0].name == "destination"


def test_user_input_requires_clarify_block():
    spec = _spec([{"id": "collect", "kind": "user_input", "skill": "collect"}])
    with pytest.raises(MetaPlanError, match="user_input.*requires.*clarify"):
        parse_meta_plan(spec)
