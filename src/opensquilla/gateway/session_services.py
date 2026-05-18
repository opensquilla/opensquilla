"""Compatibility imports for session/runtime service accessors."""

from __future__ import annotations

from opensquilla.session.services import (
    SessionEpochCache,
    SessionLockProvider,
    SessionStorageProvider,
    get_session_epoch,
    get_session_lock,
    get_session_storage,
    set_session_epoch,
)

__all__ = [
    "SessionEpochCache",
    "SessionLockProvider",
    "SessionStorageProvider",
    "get_session_epoch",
    "get_session_lock",
    "get_session_storage",
    "set_session_epoch",
]
