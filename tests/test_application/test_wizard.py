from __future__ import annotations

import pytest

from opensquilla.application.wizard import (
    WizardRegistry,
    get_wizard_registry,
    reset_wizard_registry,
)
from opensquilla.gateway import wizard as gateway_wizard


def test_wizard_registry_advances_and_applies_schema_defaults() -> None:
    registry = WizardRegistry()

    wizard_id, first_step = registry.start("onboard_agent")

    assert len(wizard_id) == 8
    assert first_step.to_dict()["stepId"] == "agent_identity"

    first = registry.advance(wizard_id, {"agent_name": "cora"})
    assert first.completed is False
    assert first.next_step is not None
    assert first.next_step.step_id == "system_prompt"

    second = registry.advance(wizard_id, {"system_prompt": "Help with release work"})
    assert second.completed is False
    assert second.next_step is not None
    assert second.next_step.step_id == "defaults"

    final = registry.advance(wizard_id, {"default_model": "openai/gpt-4o-mini"})
    assert final.completed is True
    assert final.next_step is None
    assert final.result == {
        "wizardType": "onboard_agent",
        "answers": {
            "agent_name": "cora",
            "system_prompt": "Help with release work",
            "persona_tone": "professional",
            "default_model": "openai/gpt-4o-mini",
            "temperature": 7,
        },
    }


def test_wizard_registry_rejects_blank_required_answers() -> None:
    registry = WizardRegistry()
    wizard_id, _first_step = registry.start("onboard_agent")

    with pytest.raises(ValueError, match="missing required field"):
        registry.advance(wizard_id, {"agent_name": "  "})


def test_gateway_wizard_imports_remain_compatible_with_application_singleton() -> None:
    reset_wizard_registry()

    assert gateway_wizard.get_wizard_registry() is get_wizard_registry()

    wizard_id, _first_step = gateway_wizard.get_wizard_registry().start("onboard_agent")
    assert get_wizard_registry().status(wizard_id).wizard_type == "onboard_agent"
