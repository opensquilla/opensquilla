"""Unit tests for the user_input step type additions (PR1)."""

from __future__ import annotations

import dataclasses

import pytest

from opensquilla.skills.meta.types import ClarifyField, ClarifyStepConfig


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
