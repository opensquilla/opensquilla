"""Coding-mode toggle: ON enforces code-task, OFF makes it unreachable."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.engine.steps.coding_mode import enforce_coding_mode
from opensquilla.engine.steps.skills_filter import _eligibility_ctx
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc_config import _SAFE_WRITE_PATCH_PATHS
from opensquilla.skills.eligibility import (
    CODING_MODE_SKILLS,
    effective_disabled,
    is_skill_available,
)


class TestAvailabilityHelper:
    def test_codetask_gated_when_coding_mode_off(self):
        assert is_skill_available("code-task", disabled=[], coding_mode=False) is False

    def test_codetask_available_when_coding_mode_on(self):
        assert is_skill_available("code-task", disabled=[], coding_mode=True) is True

    def test_other_skill_unaffected_by_coding_mode(self):
        assert is_skill_available("git-diff", disabled=[], coding_mode=False) is True

    def test_other_skill_still_respects_disabled(self):
        assert is_skill_available("git-diff", disabled=["git-diff"], coding_mode=True) is False

    def test_effective_disabled_adds_codetask_when_off(self):
        assert CODING_MODE_SKILLS <= effective_disabled([], coding_mode=False)
        assert "code-task" not in effective_disabled([], coding_mode=True)


class TestConfig:
    def test_coding_mode_defaults_off(self):
        assert GatewayConfig().skills.coding_mode is False

    def test_coding_mode_is_safe_write_path(self):
        assert "skills.coding_mode" in _SAFE_WRITE_PATCH_PATHS


class TestSkillsFilterGate:
    def test_off_gates_codetask(self):
        ctx = _eligibility_ctx(SimpleNamespace(disabled=[], coding_mode=False))
        assert "code-task" in ctx.disabled_set

    def test_on_does_not_gate_codetask(self):
        ctx = _eligibility_ctx(SimpleNamespace(disabled=[], coding_mode=True))
        assert "code-task" not in ctx.disabled_set


class TestDirectiveInjection:
    def _ctx(self, coding_mode: bool):
        return SimpleNamespace(
            config=SimpleNamespace(skills=SimpleNamespace(coding_mode=coding_mode)),
            system_prompt="BASE",
            metadata={},
        )

    @pytest.mark.asyncio
    async def test_on_injects_directive_and_pins(self):
        ctx = await enforce_coding_mode(self._ctx(True))
        base, suffix = ctx.system_prompt
        assert base == "BASE"
        assert "CODING MODE" in suffix
        assert "opensquilla code-task solve" in suffix
        assert "code-task" in ctx.metadata["pinned_skills"]
        assert ctx.metadata["coding_mode"] is True

    @pytest.mark.asyncio
    async def test_off_injects_nothing(self):
        ctx = await enforce_coding_mode(self._ctx(False))
        # system_prompt unchanged (still a plain str), no pin.
        assert ctx.system_prompt == "BASE"
        assert "pinned_skills" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_directive_appends_to_existing_suffix(self):
        ctx = self._ctx(True)
        ctx.system_prompt = ("BASE", "PRIOR")
        out = await enforce_coding_mode(ctx)
        base, suffix = out.system_prompt
        assert base == "BASE"
        assert suffix.startswith("PRIOR")
        assert "CODING MODE" in suffix
