"""Sandbox settings model and combination validation.

The settings live in their own module rather than being glued onto
:class:`opensquilla.gateway.config.GatewayConfig` directly so the validation rules
can be unit-tested without booting the gateway. ``GatewayConfig`` is expected
to attach a :class:`SandboxSettings` submodel in a later integration step.

The four-way truth table for the two feature switches is implemented in
:meth:`SandboxSettings.validate_combination`, which returns an
:class:`EffectiveMode` instead of mutating silently. The caller decides
whether to log a warning or abort. The active behaviour contract is recorded
in ``docs/adr/006-sandbox-governance.md``.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from opensquilla.sandbox.types import SecurityLevel

log = logging.getLogger(__name__)

BackendName = Literal["auto", "bubblewrap", "seatbelt", "noop"]
NetworkDefault = Literal["none", "proxy_allowlist"]


@dataclass(frozen=True)
class EffectiveMode:
    """Resolved runtime posture after combination validation.

    The gateway logs one line containing these fields on boot so operators
    can see at a glance which way the switches ended up pointing.
    """

    sandbox_enabled: bool
    grading_enabled: bool
    default_level: SecurityLevel
    backend: BackendName
    insecure_mode: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "sandbox_enabled": self.sandbox_enabled,
            "grading_enabled": self.grading_enabled,
            "default_level": self.default_level.label,
            "backend": self.backend,
            "insecure_mode": self.insecure_mode,
            "notes": list(self.notes),
        }


class SandboxSettings(BaseSettings):
    """Top-level sandbox configuration.

    Two independent switches (§6):

    * ``sandbox`` — whether isolation is enforced at all.
    * ``security_grading`` — whether the level-selection + approval flow is
      active. When false, the system uses a fixed ``STANDARD`` policy with no
      dynamic escalation.

    Both default to ``True``. Invalid combinations are coerced with an
    explicit warning via :meth:`validate_combination`; the coercion is
    deliberate so upgrades of existing deployments do not hard-fail.
    """

    model_config = SettingsConfigDict(env_prefix="OPENSQUILLA_SANDBOX_")

    sandbox: bool = True
    security_grading: bool = True
    default_level: SecurityLevel = SecurityLevel.STANDARD
    backend: BackendName = "auto"
    allow_legacy_mode: bool = False

    network_default: NetworkDefault = "none"
    denial_threshold: int = 3

    extra_ro_mounts: list[str] = Field(default_factory=list)
    extra_rw_mounts: list[str] = Field(default_factory=list)

    cpu_seconds: int = 30
    memory_mb: int = 1024
    wall_seconds: int = 60

    @model_validator(mode="after")
    def _check_legacy_level(self) -> SandboxSettings:
        """Prevent the DISABLED level from leaking in through default config.

        The ``DISABLED`` security level is legacy/compat only; selecting it
        requires the operator to also flip ``allow_legacy_mode`` on, which
        is a second explicit action. This matches §7.2's "no silent default"
        rule.
        """
        if self.default_level == SecurityLevel.DISABLED and not self.allow_legacy_mode:
            raise ValueError(
                "default_level=DISABLED requires allow_legacy_mode=True; "
                "legacy mode must be opted into explicitly"
            )
        return self

    def validate_combination(self) -> EffectiveMode:
        """Resolve the two switches into an :class:`EffectiveMode`.

        Truth table:

        * ``sandbox=True, grading=True`` — full mode, level selection on.
        * ``sandbox=True, grading=False`` — isolation on, fixed ``STANDARD``
          policy, approval escalation off.
        * ``sandbox=False, grading=True`` — inconsistent; grading coerced to
          ``False`` with a warning. Never silent.
        * ``sandbox=False, grading=False`` — legacy mode; single ``WARNING``
          emitted so running without sandbox is never invisible.

        The method emits logs as a side effect and returns the resolved
        posture. Callers should log ``EffectiveMode.as_dict()`` at boot.
        """
        notes: list[str] = []
        sandbox_enabled = self.sandbox
        grading_enabled = self.security_grading
        level = self.default_level

        if not sandbox_enabled and grading_enabled:
            log.warning(
                "sandbox.invalid_combo: sandbox=false with grading=true coerced to grading=false"
            )
            grading_enabled = False
            notes.append("grading_coerced_to_false_because_sandbox_disabled")

        if not grading_enabled and sandbox_enabled:
            log.info("sandbox.grading_disabled: using fixed STANDARD policy, no approval flow")
            level = SecurityLevel.STANDARD
            notes.append("fixed_standard_policy")

        insecure = not sandbox_enabled
        if insecure:
            log.warning("sandbox.disabled_insecure_mode: sandbox=false; host isolation is OFF")
            notes.append("insecure_mode")
            if not self.allow_legacy_mode:
                notes.append("legacy_flag_missing")

        return EffectiveMode(
            sandbox_enabled=sandbox_enabled,
            grading_enabled=grading_enabled,
            default_level=level,
            backend=self.backend,
            insecure_mode=insecure,
            notes=tuple(notes),
        )


def apply_host_compatibility(settings: SandboxSettings) -> SandboxSettings:
    """Adjust unsupported platform defaults before runtime selection."""

    if (
        sys.platform.startswith("win")
        and settings.sandbox
        and settings.backend == "auto"
    ):
        log.warning(
            "sandbox.windows_auto_backend_unsupported: "
            "no Windows sandbox backend is available; disabling sandbox for this runtime"
        )
        return settings.model_copy(
            update={
                "sandbox": False,
                "security_grading": False,
            }
        )
    return settings


__all__ = [
    "BackendName",
    "EffectiveMode",
    "NetworkDefault",
    "apply_host_compatibility",
    "SandboxSettings",
]
