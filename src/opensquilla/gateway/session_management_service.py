"""Compatibility imports for session create/patch service behavior."""

from __future__ import annotations

from opensquilla.session.management_service import (
    agent_registry_has,
    agent_registry_model,
    create_session,
    create_session_key,
    model_value,
    patch_session,
    require_session_key,
    session_turn_model,
)

__all__ = [
    "agent_registry_has",
    "agent_registry_model",
    "create_session",
    "create_session_key",
    "model_value",
    "patch_session",
    "require_session_key",
    "session_turn_model",
]
