"""Runtime gate for model-visible meta-skill behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def is_meta_skill_enabled(config: Any) -> bool:
    """Return whether model-visible meta-skill behavior is enabled.

    Missing configuration defaults to True for backwards compatibility. The
    helper accepts GatewayConfig-like objects, AgentConfig-like objects with
    metadata, and plain metadata dictionaries used by lower-level tests.
    """

    if config is None:
        return True

    if isinstance(config, Mapping):
        if "meta_skill_enabled" in config:
            return bool(config["meta_skill_enabled"])
        gateway_config = config.get("gateway_config")
        if gateway_config is not None:
            return is_meta_skill_enabled(gateway_config)
        meta_skill = config.get("meta_skill")
        if meta_skill is not None:
            return _enabled_from_meta_skill_config(meta_skill)
        return True

    metadata = getattr(config, "metadata", None)
    if isinstance(metadata, Mapping):
        if "meta_skill_enabled" in metadata:
            return bool(metadata["meta_skill_enabled"])
        gateway_config = metadata.get("gateway_config")
        if gateway_config is not None:
            return is_meta_skill_enabled(gateway_config)

    meta_skill = getattr(config, "meta_skill", None)
    if meta_skill is None:
        return True
    return _enabled_from_meta_skill_config(meta_skill)


def _enabled_from_meta_skill_config(meta_skill: Any) -> bool:
    if isinstance(meta_skill, Mapping):
        return bool(meta_skill.get("enabled", True))
    return bool(getattr(meta_skill, "enabled", True))
