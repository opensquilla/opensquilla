"""MetaSkillConfig.auto_trigger defaults False and is a declared field."""

from __future__ import annotations

from opensquilla.gateway.config import MetaSkillConfig


def test_auto_trigger_defaults_false() -> None:
    cfg = MetaSkillConfig()
    assert cfg.auto_trigger is False
    # enabled remains True (master gate unchanged).
    assert cfg.enabled is True


def test_auto_trigger_can_be_enabled() -> None:
    cfg = MetaSkillConfig(auto_trigger=True)
    assert cfg.auto_trigger is True
