"""is_meta_auto_trigger_enabled defaults OFF and reads meta_skill.auto_trigger."""

from __future__ import annotations

from types import SimpleNamespace

from opensquilla.skills.meta.enabled import is_meta_auto_trigger_enabled


def test_none_config_defaults_false() -> None:
    # Unlike is_meta_skill_enabled (defaults True), missing config => manual-only.
    assert is_meta_auto_trigger_enabled(None) is False


def test_mapping_direct_key() -> None:
    assert is_meta_auto_trigger_enabled({"meta_skill_auto_trigger": True}) is True
    assert is_meta_auto_trigger_enabled({"meta_skill_auto_trigger": False}) is False


def test_mapping_nested_meta_skill() -> None:
    assert is_meta_auto_trigger_enabled({"meta_skill": {"auto_trigger": True}}) is True
    # absent key => False
    assert is_meta_auto_trigger_enabled({"meta_skill": {"enabled": True}}) is False


def test_mapping_gateway_config_recursion() -> None:
    cfg = {"gateway_config": {"meta_skill": {"auto_trigger": True}}}
    assert is_meta_auto_trigger_enabled(cfg) is True


def test_attribute_object() -> None:
    cfg = SimpleNamespace(meta_skill=SimpleNamespace(enabled=True, auto_trigger=True))
    assert is_meta_auto_trigger_enabled(cfg) is True
    cfg_off = SimpleNamespace(meta_skill=SimpleNamespace(enabled=True, auto_trigger=False))
    assert is_meta_auto_trigger_enabled(cfg_off) is False


def test_attribute_object_missing_meta_skill_defaults_false() -> None:
    assert is_meta_auto_trigger_enabled(SimpleNamespace()) is False
