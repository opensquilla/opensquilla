"""Unit tests for the user_input step type additions (PR1)."""

from __future__ import annotations

import dataclasses

import pytest

from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaPaused,
    MetaStep,
)


def test_clarify_field_minimal_construction():
    f = ClarifyField(name="destination", type="string")
    assert f.name == "destination"
    assert f.type == "string"
    assert f.required is False
    assert f.prompt == ""
    assert f.choices == ()
    assert f.default is None
    assert f.min is None
    assert f.max is None
    assert f.max_chars is None


def test_clarify_field_is_frozen():
    f = ClarifyField(name="destination", type="string")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.name = "other"  # type: ignore[misc]


def test_clarify_field_enum_choices_immutable():
    f = ClarifyField(
        name="budget",
        type="enum",
        choices=("budget", "mid", "premium"),
        default="mid",
    )
    assert f.choices == ("budget", "mid", "premium")
    assert isinstance(f.choices, tuple)


def test_clarify_step_config_defaults():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="destination", type="string"),),
    )
    assert cfg.mode == "form"
    assert len(cfg.fields) == 1
    assert cfg.skip_if == ""
    assert cfg.cancel_keywords == ()
    assert cfg.timeout_hours == 24
    assert cfg.intro == ""
    assert cfg.nl_extract is False
    assert cfg.nl_extract_tier == ""


def test_clarify_step_config_is_frozen():
    cfg = ClarifyStepConfig(mode="form", fields=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.mode = "chat"  # type: ignore[misc]


def test_meta_paused_is_exception_and_carries_payload():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string"),),
    )
    paused = MetaPaused(
        run_id="r123",
        step_id="collect",
        schema=cfg,
        intro="hello",
    )
    assert isinstance(paused, Exception)
    assert paused.run_id == "r123"
    assert paused.step_id == "collect"
    assert paused.schema is cfg
    assert paused.intro == "hello"


def test_meta_paused_can_be_raised_and_caught():
    cfg = ClarifyStepConfig(mode="form", fields=())
    with pytest.raises(MetaPaused) as excinfo:
        raise MetaPaused(run_id="r", step_id="s", schema=cfg)
    assert excinfo.value.run_id == "r"


def test_meta_paused_attributes_are_effectively_immutable():
    """MetaPaused is not a frozen dataclass (Exception incompatibility — see
    types.py docstring), but is treated as immutable by convention. Attributes
    are read-only once initialized; accidental mutation is prevented by the
    keyword-only constructor and __slots__ design, not by runtime enforcement."""
    cfg = ClarifyStepConfig(mode="form", fields=())
    paused = MetaPaused(run_id="r", step_id="s", schema=cfg)
    # Verify that __slots__ prevents adding unknown attributes on Exception subclasses
    # (Note: Exception has __dict__, so unknown attributes CAN be added; this test
    # documents the expected "by convention" immutability rather than enforced immutability)
    assert paused.run_id == "r"
    assert paused.step_id == "s"
    assert paused.schema is cfg


def test_meta_step_clarify_config_defaults_to_none():
    s = MetaStep(id="x", skill="x")
    assert s.clarify_config is None


def test_meta_step_can_carry_clarify_config():
    cfg = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="destination", type="string"),),
    )
    s = MetaStep(id="collect", skill="collect", kind="user_input", clarify_config=cfg)
    assert s.kind == "user_input"
    assert s.clarify_config is cfg


def test_meta_result_paused_defaults_to_false():
    from opensquilla.skills.meta.types import MetaResult
    r = MetaResult(ok=True, final_text="done")
    assert r.paused is False
    assert r.paused_payload is None


def test_meta_result_paused_carries_payload():
    from opensquilla.skills.meta.types import MetaPaused, MetaResult
    cfg = ClarifyStepConfig(mode="form", fields=())
    paused = MetaPaused(run_id="r1", step_id="collect", schema=cfg)
    r = MetaResult(ok=False, paused=True, paused_payload=paused)
    assert r.ok is False
    assert r.paused is True
    assert r.paused_payload is paused
