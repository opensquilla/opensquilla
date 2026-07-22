"""Frozen compatibility field for the retired onboarding migration advisory."""

from __future__ import annotations


def legacy_data_payload() -> None:
    """Return ``None`` without scanning the host filesystem.

    The ``legacyData`` key remains in the onboarding wire shape for the current
    major version. Candidate discovery is now settings-only.
    """

    return None
