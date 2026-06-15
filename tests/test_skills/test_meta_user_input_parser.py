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


def test_user_input_accepts_localized_intro_and_prompts():
    spec = _spec([
        {
            "id": "collect",
            "kind": "user_input",
            "skill": "collect",
            "clarify": {
                "mode": "form",
                "intro": "补充信息 / Add details",
                "intro_zh": "请补充信息。",
                "intro_en": "Please add details.",
                "fields": [
                    {
                        "name": "topic",
                        "type": "string",
                        "required": True,
                        "prompt": "主题 / Topic",
                        "prompt_zh": "主题",
                        "prompt_en": "Topic",
                    },
                ],
            },
        },
    ])

    plan = parse_meta_plan(spec)
    assert plan is not None
    cfg = plan.steps[0].clarify_config
    assert cfg is not None
    assert cfg.intro_by_language == {
        "zh": "请补充信息。",
        "en": "Please add details.",
    }
    assert cfg.fields[0].prompt_by_language == {
        "zh": "主题",
        "en": "Topic",
    }


def test_user_input_splits_legacy_bilingual_intro_and_prompts():
    spec = _spec([
        {
            "id": "collect",
            "kind": "user_input",
            "skill": "collect",
            "clarify": {
                "mode": "form",
                "intro": "请补充信息 / Please add details",
                "fields": [
                    {
                        "name": "topic",
                        "type": "string",
                        "required": True,
                        "prompt": "主题 / Topic",
                    },
                ],
            },
        },
    ])

    plan = parse_meta_plan(spec)

    assert plan is not None
    cfg = plan.steps[0].clarify_config
    assert cfg is not None
    assert cfg.intro_by_language == {
        "zh": "请补充信息",
        "en": "Please add details",
    }
    assert cfg.fields[0].prompt_by_language == {
        "zh": "主题",
        "en": "Topic",
    }


def test_user_input_parser_appends_generic_additional_notes_field():
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
    cfg = plan.steps[0].clarify_config
    assert cfg is not None
    notes = cfg.fields[-1]
    assert notes.name == "additional_notes"
    assert notes.type == "string"
    assert notes.required is False
    assert notes.max_chars == 2000
    assert "备注" in notes.prompt_by_language["zh"]
    assert "Additional" in notes.prompt_by_language["en"]


def test_user_input_requires_clarify_block():
    spec = _spec([{"id": "collect", "kind": "user_input", "skill": "collect"}])
    with pytest.raises(MetaPlanError, match="user_input.*requires.*clarify"):
        parse_meta_plan(spec)


def _user_input_spec(**clarify_overrides) -> SkillSpec:
    """Minimal user_input step with the given clarify overrides."""
    base_clarify = {
        "mode": "form",
        "fields": [{"name": "x", "type": "string", "required": True}],
    }
    base_clarify.update(clarify_overrides)
    return _spec([
        {"id": "collect", "kind": "user_input", "skill": "collect", "clarify": base_clarify},
    ])


# Rule 1: mode must be "form" or "chat"; default "form"
def test_rule01_mode_defaults_to_form():
    spec = _spec([{
        "id": "c", "kind": "user_input", "skill": "c",
        "clarify": {"fields": [{"name": "x", "type": "string"}]},
    }])
    plan = parse_meta_plan(spec)
    assert plan.steps[0].clarify_config.mode == "form"


def test_rule01_unknown_mode_rejected():
    with pytest.raises(MetaPlanError, match="clarify.mode"):
        parse_meta_plan(_user_input_spec(mode="dialog"))


# Rule 2: field name regex
def test_rule02_field_name_regex_rejects_uppercase():
    with pytest.raises(MetaPlanError, match=r"name.*must match"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "BAD", "type": "string"}],
        ))


def test_rule02_field_names_must_be_unique():
    with pytest.raises(MetaPlanError, match="duplicate name"):
        parse_meta_plan(_user_input_spec(
            fields=[
                {"name": "x", "type": "string"},
                {"name": "x", "type": "int"},
            ],
        ))


# Rule 3: type whitelist
def test_rule03_type_must_be_in_whitelist():
    with pytest.raises(MetaPlanError, match="type 'float'"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "float"}],
        ))


# Rule 4: enum requires choices
def test_rule04_enum_requires_choices():
    with pytest.raises(MetaPlanError, match="enum type requires non-empty choices"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "enum"}],
        ))


def test_rule04_enum_choices_must_be_unique():
    with pytest.raises(MetaPlanError, match="choices must be unique"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "enum", "choices": ["a", "a"]}],
        ))


# Rule 5: int min/max
def test_rule05_int_min_must_not_exceed_max():
    with pytest.raises(MetaPlanError, match=r"min=10.*max=1"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "int", "min": 10, "max": 1}],
        ))


def test_rule05_min_max_only_for_int():
    with pytest.raises(MetaPlanError, match="min/max only valid"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "string", "min": 1}],
        ))


# Rule 6: string max_chars range
def test_rule06_string_max_chars_in_range():
    with pytest.raises(MetaPlanError, match="max_chars must be an int in"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "string", "max_chars": 5000}],
        ))


def test_rule06_max_chars_only_for_string():
    with pytest.raises(MetaPlanError, match="max_chars only valid"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "int", "max_chars": 10}],
        ))


# Rule 7: required and default mutually exclusive
def test_rule07_required_and_default_mutually_exclusive():
    with pytest.raises(MetaPlanError, match="required=true and default are mutually exclusive"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "string", "required": True, "default": "y"}],
        ))


# Rule 8: default must pass per-type validation
def test_rule08_enum_default_must_be_in_choices():
    with pytest.raises(MetaPlanError, match=r"default 'big' not in choices"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "enum",
                     "choices": ["small", "mid"], "default": "big"}],
        ))


def test_rule08_int_default_must_be_int():
    with pytest.raises(MetaPlanError, match="default for int field must be an int"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "int", "default": "five"}],
        ))


def test_rule08_int_default_below_min_rejected():
    with pytest.raises(MetaPlanError, match="default 0 is below min=1"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "int", "min": 1, "max": 10, "default": 0}],
        ))


def test_rule08_int_default_above_max_rejected():
    with pytest.raises(MetaPlanError, match="default 11 is above max=10"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "int", "min": 1, "max": 10, "default": 11}],
        ))


def test_rule08_string_default_exceeding_max_chars_rejected():
    with pytest.raises(MetaPlanError, match="default length .* exceeds max_chars"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "string", "max_chars": 5,
                     "default": "longer than five"}],
        ))


def test_rule08_int_default_must_not_be_bool():
    """In Python, isinstance(True, int) is True. Catch this explicitly so
    `default: true` on an int field cannot silently coerce."""
    with pytest.raises(MetaPlanError, match="default for int field must be an int"):
        parse_meta_plan(_user_input_spec(
            fields=[{"name": "x", "type": "int", "default": True}],
        ))


# Defensive: required must be a real boolean (not 'false' string, etc.)
def test_required_must_be_real_bool_truthy_string_rejected():
    """A literal 'false' string in YAML decodes to a string, not False.
    The parser explicitly rejects implicit string-to-bool coercion."""
    spec = _spec([
        {
            "id": "collect", "kind": "user_input", "skill": "collect",
            "clarify": {
                "mode": "form",
                "fields": [{"name": "x", "type": "string", "required": "false"}],
            },
        },
    ])
    with pytest.raises(MetaPlanError, match="required.*must be a boolean"):
        parse_meta_plan(spec)


# Rule 9: skip_if must be a string AND must compile_expression at parse time
def test_rule09_skip_if_must_be_string():
    with pytest.raises(MetaPlanError, match="skip_if must be a string"):
        parse_meta_plan(_user_input_spec(skip_if=123))


def test_rule09_skip_if_compiles_at_parse_time():
    """Spec §5.2 rule 9: skip_if must compile via _JINJA_ENV.compile_expression.
    Malformed Jinja is rejected before SkillSpec ever loads."""
    with pytest.raises(MetaPlanError, match="skip_if failed to compile"):
        parse_meta_plan(_user_input_spec(skip_if="this is not jinja {{"))


def test_rule09_valid_skip_if_passes():
    plan = parse_meta_plan(_user_input_spec(
        skip_if="'destination=' in outputs.classify",
    ))
    assert plan.steps[0].clarify_config.skip_if == "'destination=' in outputs.classify"


# Rule 10: cancel_keywords list of non-empty strings; normalized to lowercase
def test_rule10_cancel_keywords_normalized_lowercase():
    plan = parse_meta_plan(_user_input_spec(cancel_keywords=["Cancel", "STOP", " 取消 "]))
    assert plan.steps[0].clarify_config.cancel_keywords == ("cancel", "stop", "取消")


def test_rule10_cancel_keywords_rejects_empty_string():
    with pytest.raises(MetaPlanError, match="list of non-empty strings"):
        parse_meta_plan(_user_input_spec(cancel_keywords=["", "stop"]))


# Rule 11: timeout_hours range
def test_rule11_timeout_hours_lower_bound():
    with pytest.raises(MetaPlanError, match=r"in \[1, 168\]"):
        parse_meta_plan(_user_input_spec(timeout_hours=0))


def test_rule11_timeout_hours_upper_bound():
    with pytest.raises(MetaPlanError, match=r"in \[1, 168\]"):
        parse_meta_plan(_user_input_spec(timeout_hours=169))


# Rule 12: field count caps
def test_rule12_form_mode_caps_at_12_fields():
    fields = [
        {"name": f"f{i}", "type": "string", "required": True}
        for i in range(13)
    ]
    with pytest.raises(MetaPlanError, match="max for mode='form'"):
        parse_meta_plan(_user_input_spec(fields=fields))


def test_rule12_chat_mode_caps_at_4_fields():
    fields = [
        {"name": f"f{i}", "type": "string", "required": True}
        for i in range(5)
    ]
    with pytest.raises(MetaPlanError, match="max for mode='chat'"):
        parse_meta_plan(_user_input_spec(mode="chat", fields=fields))


# Rule 13: prompt/intro stored verbatim — no escape at parse time
def test_rule13_intro_stored_verbatim_with_angle_brackets():
    plan = parse_meta_plan(_user_input_spec(intro="<b>important</b>"))
    assert plan.steps[0].clarify_config.intro == "<b>important</b>"


# Rule 14: nl_extract boolean + nl_extract_tier
def test_rule14_nl_extract_default_false():
    plan = parse_meta_plan(_user_input_spec())
    assert plan.steps[0].clarify_config.nl_extract is False
    assert plan.steps[0].clarify_config.nl_extract_tier == ""


def test_rule14_nl_extract_must_be_bool():
    with pytest.raises(MetaPlanError, match="nl_extract.*must be a boolean"):
        parse_meta_plan(_user_input_spec(nl_extract="yes"))


def test_rule14_nl_extract_tier_ignored_when_extract_false():
    plan = parse_meta_plan(_user_input_spec(nl_extract=False, nl_extract_tier="t3"))
    # spec §5.2 rule 14: tier is ignored when nl_extract is false
    assert plan.steps[0].clarify_config.nl_extract_tier == ""


def test_rule14_nl_extract_tier_kept_when_extract_true():
    plan = parse_meta_plan(_user_input_spec(nl_extract=True, nl_extract_tier="t1"))
    assert plan.steps[0].clarify_config.nl_extract is True
    assert plan.steps[0].clarify_config.nl_extract_tier == "t1"


# Cross-cutting: 'clarify' on a non-user_input step is rejected
def test_clarify_block_rejected_on_non_user_input_step():
    spec = _spec([
        {
            "id": "x", "kind": "agent", "skill": "summarize",
            "clarify": {"mode": "form", "fields": [{"name": "x", "type": "string"}]},
        },
    ])
    with pytest.raises(MetaPlanError, match="'clarify' only valid for kind=user_input"):
        parse_meta_plan(spec)
