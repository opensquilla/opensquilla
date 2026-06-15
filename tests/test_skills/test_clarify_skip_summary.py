"""Tests for the clarify-skip transparency helper (trust-gap fix).

The (c)/(d) confirmed_fields protocol only fires when a user_input
step actually pauses. A meta author can suppress the form entirely
with ``when: 'NEEDS_CLARIFICATION: no' in outputs.x``, which used to
leave the user with zero visibility into what the system inferred.
``_build_clarify_skip_summary`` ships a transparency payload on the
skipped path so the surface can render a "we inferred this — confirm
/ change" card.
"""

from __future__ import annotations

from opensquilla.skills.meta.scheduler import _build_clarify_skip_summary
from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaStep,
)


def _user_input_step(
    *,
    step_id: str = "intel_clarify",
    depends_on: tuple[str, ...] = ("preferences",),
    when: str = "'NEEDS_CLARIFICATION: yes' in outputs.preferences",
    fields: tuple[ClarifyField, ...] = (
        ClarifyField(
            name="accounts",
            type="string",
            required=True,
            prompt="Companies to monitor",
        ),
        ClarifyField(
            name="time_window",
            type="enum",
            required=False,
            choices=("LAST_WEEK", "LAST_MONTH"),
        ),
    ),
) -> MetaStep:
    return MetaStep(
        id=step_id,
        skill=step_id,
        kind="user_input",
        depends_on=depends_on,
        when=when,
        clarify_config=ClarifyStepConfig(
            mode="form",
            fields=fields,
            nl_extract=True,
        ),
    )


def test_skip_summary_returns_none_for_non_user_input_step() -> None:
    """The transparency card is only meaningful for skipped user_input
    steps. A skipped llm_chat / agent / tool_call step is just a
    no-op; surfacing a "confirm what we inferred" card on it would
    be noise."""
    step = MetaStep(
        id="x", skill="x", kind="llm_chat", when="false",
    )
    assert _build_clarify_skip_summary(step, {}, {}) is None


def test_skip_summary_returns_none_when_clarify_config_missing() -> None:
    """Defensive: a parser invariant guarantees clarify_config is
    present on user_input steps, but the helper still returns None
    rather than raising if a malformed step slipped through."""
    step = MetaStep(id="x", skill="x", kind="user_input")
    assert _build_clarify_skip_summary(step, {}, {}) is None


def test_skip_summary_includes_field_names_and_prompts() -> None:
    """The surface needs to render "what would have been asked"
    so the user can recognise which fields were silently filled.
    Each entry carries the field's name, required flag, and prompt."""
    step = _user_input_step()
    summary = _build_clarify_skip_summary(step, {}, {})
    assert summary is not None
    assert summary["step_id"] == "intel_clarify"
    fields = summary["fields"]
    assert len(fields) == 2
    by_name = {f["name"]: f for f in fields}
    assert by_name["accounts"]["required"] is True
    assert by_name["accounts"]["prompt"] == "Companies to monitor"
    assert by_name["time_window"]["required"] is False


def test_skip_summary_excerpts_upstream_step_outputs() -> None:
    """The ``when:`` expression typically keys off an upstream step's
    output (e.g. ``outputs.preferences``). The user wants to see what
    that upstream step produced so they can verify the system's
    inference was correct. Each ``depends_on`` step contributes an
    excerpt block."""
    step = _user_input_step()
    outputs = {
        "preferences": (
            "ACCOUNTS: OpenAI, Anthropic\n"
            "DIMENSIONS: PRICING, PRODUCT\n"
            "NEEDS_CLARIFICATION: no\n"
        ),
    }
    summary = _build_clarify_skip_summary(step, {}, outputs)
    assert summary is not None
    inferred = summary["inferred_from"]
    assert len(inferred) == 1
    assert inferred[0]["step"] == "preferences"
    assert "OpenAI" in inferred[0]["excerpt"]
    assert "NEEDS_CLARIFICATION" in inferred[0]["excerpt"]


def test_skip_summary_truncates_oversized_upstream_excerpts() -> None:
    """A 4 KB upstream output would bloat every tool result. Cap
    each excerpt and add a ``...[truncated]`` marker so the surface
    knows there's more (it can request the full output via a
    follow-up if needed)."""
    step = _user_input_step()
    long_blob = "X" * 5000
    outputs = {"preferences": long_blob}
    summary = _build_clarify_skip_summary(step, {}, outputs)
    assert summary is not None
    excerpt = summary["inferred_from"][0]["excerpt"]
    assert excerpt.endswith("...[truncated]")
    # Upstream cap is bounded; the exact value is implementation
    # detail but the excerpt must be far smaller than the source.
    assert len(excerpt) < len(long_blob)


def test_skip_summary_carries_trigger_message_for_attribution() -> None:
    """The card displays "You said: ..." so the user can match the
    inferred answers to the original request that triggered the
    meta-skill."""
    step = _user_input_step()
    inputs = {"user_message": "Watch this account for OpenAI and Anthropic"}
    summary = _build_clarify_skip_summary(step, inputs, {})
    assert summary is not None
    assert "OpenAI" in summary["trigger_message"]


def test_skip_summary_strips_preflight_confirmation_protocol_from_trigger() -> None:
    step = _user_input_step()
    inputs = {
        "user_message": (
            "请帮我判断这份供应商续费材料。\n\n"
            "合同摘录：\n"
            "- 价格：每月 $4,800\n\n"
            "Confirmed request fields:\n"
            "- audience: decision owner\n"
            "- decision_question: 签不签合同\n\n"
            "<!-- opensquilla:meta_preflight_confirmed=1 -->"
        )
    }

    summary = _build_clarify_skip_summary(step, inputs, {})

    assert summary is not None
    assert summary["trigger_message"] == (
        "请帮我判断这份供应商续费材料。\n\n"
        "合同摘录：\n"
        "- 价格：每月 $4,800"
    )
    assert "Confirmed request fields" not in summary["trigger_message"]
    assert "opensquilla:meta_preflight" not in summary["trigger_message"]


def test_skip_summary_omits_empty_upstream_outputs() -> None:
    """An empty / whitespace-only upstream output is not useful
    attribution; drop it rather than ship an empty excerpt."""
    step = _user_input_step()
    summary = _build_clarify_skip_summary(step, {}, {"preferences": "   "})
    assert summary is not None
    assert summary["inferred_from"] == []


def test_skip_summary_carries_default_label_and_hint() -> None:
    """Every payload ships with surface-agnostic copy so even a
    minimal renderer (CLI plaintext, IM channel) can announce the
    intent without re-deriving copy."""
    step = _user_input_step()
    summary = _build_clarify_skip_summary(step, {}, {})
    assert summary is not None
    assert "infer" in summary["label"].lower() or "answers" in summary["label"].lower()
    assert summary["hint_action"]
