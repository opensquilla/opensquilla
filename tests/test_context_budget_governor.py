from __future__ import annotations

from opensquilla.context_budget import (
    ContextBudgetClass,
    ContextBudgetGovernor,
)
from opensquilla.engine import AgentConfig, ThinkingLevel


def test_context_budget_governor_derives_large_window_caps() -> None:
    budget = ContextBudgetGovernor.from_values(
        context_window_tokens=200_000,
        max_output_tokens=8_192,
        thinking_budget_tokens=0,
        context_overflow_threshold=0.85,
    ).snapshot()

    assert budget.provider_request_max_chars > 500_000
    assert budget.default_tool_argument_max_chars > 8_000
    assert budget.default_tool_result_provider_max_chars > 96_000
    assert budget.external_tool_result_provider_max_chars < (
        budget.default_tool_result_provider_max_chars
    )


def test_context_budget_governor_keeps_small_windows_guarded() -> None:
    budget = ContextBudgetGovernor.from_values(
        context_window_tokens=8_000,
        max_output_tokens=8_192,
        thinking_budget_tokens=0,
        context_overflow_threshold=0.85,
    ).snapshot()

    assert 4_000 <= budget.provider_request_max_chars <= 32_000
    assert 2_000 <= budget.default_tool_argument_max_chars <= 16_000
    assert budget.default_tool_result_provider_max_chars <= 32_000


def test_context_budget_governor_honors_explicit_overrides() -> None:
    governor = ContextBudgetGovernor.from_values(
        context_window_tokens=200_000,
        max_output_tokens=8_192,
        thinking_budget_tokens=0,
        context_overflow_threshold=0.85,
        provider_request_proof_max_chars=123_456,
        tool_use_argument_provider_request_max_chars=12_345,
        tool_result_provider_request_max_chars=54_321,
    )

    budget = governor.snapshot()

    assert budget.provider_request_max_chars == 123_456
    assert governor.tool_argument_chars_for(ContextBudgetClass.LOCAL) == 12_345
    assert governor.tool_result_provider_chars_for(ContextBudgetClass.LOCAL) == 54_321


def test_context_budget_governor_glm_derived_proof_budget_anchor() -> None:
    """Anchor: the GLM window with the xhigh output reserve derives 339,945."""
    budget = ContextBudgetGovernor.from_values(
        context_window_tokens=202_752,
        max_output_tokens=32_768,
        thinking_budget_tokens=50_000,
        context_overflow_threshold=0.85,
    ).snapshot()

    assert budget.provider_request_max_chars == 339_945


def test_context_budget_governor_explicit_proof_budget_bypasses_glm_ladder() -> None:
    """An explicit 650k proof budget beats the derived GLM-window ladder."""
    budget = ContextBudgetGovernor.from_values(
        context_window_tokens=202_752,
        max_output_tokens=32_768,
        thinking_budget_tokens=20_000,
        context_overflow_threshold=0.85,
        provider_request_proof_max_chars=650_000,
    ).snapshot()

    assert budget.provider_request_max_chars == 650_000
    # Derived side-effect caps scale from the explicit proof budget.
    assert budget.default_tool_argument_max_chars == 104_000  # 650k * 0.16
    assert budget.external_tool_argument_max_chars == 32_000  # 32k clamp
    assert budget.default_tool_result_provider_max_chars == 160_000  # clamp
    assert budget.external_tool_result_provider_max_chars == 160_000


def test_context_budget_governor_from_agent_config_reads_explicit_proof_budget() -> None:
    """AgentConfig.provider_request_proof_max_chars reaches the governor bypass."""
    config = AgentConfig(
        context_window_tokens=202_752,
        max_tokens=32_768,
        thinking=ThinkingLevel.HIGH,
        provider_request_proof_max_chars=650_000,
    )

    assert (
        ContextBudgetGovernor.from_config(config).snapshot().provider_request_max_chars == 650_000
    )

    derived = AgentConfig(
        context_window_tokens=202_752,
        max_tokens=32_768,
        thinking=ThinkingLevel.HIGH,
    )

    assert (
        ContextBudgetGovernor.from_config(derived).snapshot().provider_request_max_chars == 441_945
    )


def test_context_budget_governor_external_caps_stay_stricter_than_local() -> None:
    governor = ContextBudgetGovernor.from_values(
        context_window_tokens=200_000,
        max_output_tokens=8_192,
        thinking_budget_tokens=0,
        context_overflow_threshold=0.85,
    )

    assert governor.tool_argument_chars_for(ContextBudgetClass.EXTERNAL) < (
        governor.tool_argument_chars_for(ContextBudgetClass.LOCAL)
    )
    assert governor.tool_result_provider_chars_for(ContextBudgetClass.EXTERNAL) < (
        governor.tool_result_provider_chars_for(ContextBudgetClass.LOCAL)
    )
