"""Shared contract-level errors.

The contracts package intentionally stays independent from concrete runtime
implementations. These errors are safe for ports, adapters, and tests to share
without importing gateway, engine, tool, or provider internals.
"""

from __future__ import annotations


class ContractError(RuntimeError):
    """Base error for boundary-level contract failures."""


class CapabilityUnavailableError(ContractError):
    """Raised when a requested port capability is not available."""


class ContractPermissionError(ContractError):
    """Raised when a caller is not allowed to use a boundary operation."""


__all__ = [
    "CapabilityUnavailableError",
    "ContractError",
    "ContractPermissionError",
]
