"""Unit tests for CLI clarify_form pure helpers and async prompter (PR6)."""

from __future__ import annotations

import pytest

from opensquilla.cli.repl.clarify_form import (
    ClarifyFormResult,
    coerce_field_input,
    fields_to_chat_send_message,
    is_cancel_token,
    prompt_clarify_form,
    render_field_label,
)

# ── render_field_label ──

def test_label_string_required_with_prompt():
    label = render_field_label({
        "name": "destination", "type": "string", "required": True,
        "prompt": "目的地",
    })
    assert label == "destination (string, required): 目的地"


def test_label_int_with_range():
    label = render_field_label({
        "name": "days", "type": "int", "required": True,
        "prompt": "天数", "min": 1, "max": 14,
    })
    assert label == "days (int 1-14, required): 天数"


def test_label_enum_with_choices_and_default():
    label = render_field_label({
        "name": "budget", "type": "enum", "required": False,
        "prompt": "预算", "choices": ["budget", "mid", "premium"],
        "default": "mid",
    })
    assert label == "budget (enum [budget|mid|premium], default=mid): 预算"


def test_label_string_with_max_chars():
    label = render_field_label({
        "name": "notes", "type": "string", "required": False,
        "prompt": "备注", "max_chars": 100,
    })
    assert "≤100 chars" in label
    assert "optional" in label


def test_label_int_only_min():
    label = render_field_label({
        "name": "n", "type": "int", "required": True, "min": 5,
    })
    assert ">=5" in label


def test_label_int_only_max():
    label = render_field_label({
        "name": "n", "type": "int", "required": True, "max": 100,
    })
    assert "<=100" in label


def test_label_without_prompt():
    label = render_field_label({"name": "x", "type": "string", "required": True})
    assert label == "x (string, required)"


# ── coerce_field_input ──

def test_coerce_string_simple():
    value, err = coerce_field_input(
        {"name": "x", "type": "string", "required": True}, "Tokyo",
    )
    assert err is None
    assert value == "Tokyo"


def test_coerce_string_max_chars_exceeded():
    value, err = coerce_field_input(
        {"name": "n", "type": "string", "required": True, "max_chars": 5},
        "longer than five",
    )
    assert value is None
    assert "max_chars" in err


def test_coerce_int_valid():
    value, err = coerce_field_input(
        {"name": "days", "type": "int", "required": True, "min": 1, "max": 14},
        "5",
    )
    assert err is None
    assert value == 5


def test_coerce_int_non_numeric():
    value, err = coerce_field_input(
        {"name": "days", "type": "int", "required": True}, "abc",
    )
    assert value is None
    assert "integer" in err


def test_coerce_int_below_min():
    value, err = coerce_field_input(
        {"name": "days", "type": "int", "required": True, "min": 1, "max": 14},
        "0",
    )
    assert value is None
    assert "min=1" in err


def test_coerce_int_above_max():
    value, err = coerce_field_input(
        {"name": "days", "type": "int", "required": True, "min": 1, "max": 14},
        "100",
    )
    assert value is None
    assert "max=14" in err


def test_coerce_bool_true_variants():
    for s in ("true", "True", "yes", "Y", "1", "是"):
        value, err = coerce_field_input(
            {"name": "b", "type": "bool", "required": True}, s,
        )
        assert err is None, s
        assert value is True, s


def test_coerce_bool_false_variants():
    for s in ("false", "False", "no", "N", "0", "否"):
        value, err = coerce_field_input(
            {"name": "b", "type": "bool", "required": True}, s,
        )
        assert err is None, s
        assert value is False, s


def test_coerce_bool_invalid():
    value, err = coerce_field_input(
        {"name": "b", "type": "bool", "required": True}, "maybe",
    )
    assert value is None
    assert "bool" in err


def test_coerce_enum_valid():
    value, err = coerce_field_input(
        {"name": "budget", "type": "enum", "required": True,
         "choices": ["budget", "mid", "premium"]},
        "mid",
    )
    assert err is None
    assert value == "mid"


def test_coerce_enum_invalid():
    value, err = coerce_field_input(
        {"name": "budget", "type": "enum", "required": True,
         "choices": ["budget", "mid", "premium"]},
        "luxury",
    )
    assert value is None
    assert "luxury" in err


def test_coerce_required_empty_errors():
    value, err = coerce_field_input(
        {"name": "x", "type": "string", "required": True}, "",
    )
    assert value is None
    assert "required" in err


def test_coerce_optional_empty_is_silent():
    """Empty input on an optional field returns (None, None) so the caller
    can simply skip the field — not an error condition."""
    value, err = coerce_field_input(
        {"name": "x", "type": "string", "required": False}, "",
    )
    assert value is None
    assert err is None


def test_coerce_whitespace_only_treated_as_empty():
    value, err = coerce_field_input(
        {"name": "x", "type": "string", "required": True}, "   ",
    )
    assert value is None
    assert "required" in err


# ── is_cancel_token ──

def test_cancel_token_exact_match():
    assert is_cancel_token("cancel", ("cancel", "取消"))


def test_cancel_token_case_insensitive():
    assert is_cancel_token("CANCEL", ("cancel",))


def test_cancel_token_trims_whitespace():
    assert is_cancel_token("  cancel  ", ("cancel",))


def test_cancel_token_no_match_when_substring():
    """The token must match the WHOLE input, not be a substring of it."""
    assert not is_cancel_token("I want to cancel my booking", ("cancel",))


def test_cancel_token_empty_keywords_false():
    assert not is_cancel_token("anything", ())


def test_cancel_token_cjk():
    assert is_cancel_token("取消", ("取消", "cancel"))


# ── fields_to_chat_send_message ──

def test_fields_to_chat_send_message_basic():
    out = fields_to_chat_send_message({
        "destination": "Tokyo",
        "days": 5,
    })
    assert "destination: Tokyo" in out
    assert "days: 5" in out


def test_fields_to_chat_send_message_bool_lowercase():
    out = fields_to_chat_send_message({"flag": True, "off": False})
    assert "flag: true" in out
    assert "off: false" in out


def test_fields_to_chat_send_message_skips_empty():
    out = fields_to_chat_send_message({
        "destination": "Tokyo",
        "notes": "",
        "extra": None,
    })
    assert "destination: Tokyo" in out
    assert "notes" not in out
    assert "extra" not in out


# ── prompt_clarify_form (async, stubbed prompt) ──

@pytest.mark.asyncio
async def test_prompt_form_happy_path():
    """Walk through 2 fields with valid input; collect both."""
    schema = {
        "intro": "trip facts please",
        "fields": [
            {"name": "destination", "type": "string", "required": True,
             "prompt": "目的地"},
            {"name": "days", "type": "int", "required": True, "min": 1, "max": 14,
             "prompt": "天数"},
        ],
        "cancel_keywords": [],
    }
    answers = iter(["Tokyo", "5"])
    out_lines: list[str] = []

    async def _stub_prompt(prefix: str) -> str | None:
        return next(answers)

    result = await prompt_clarify_form(
        schema, prompt_fn=_stub_prompt, writer=out_lines.append,
    )
    assert result.cancelled is False
    assert result.fields == {"destination": "Tokyo", "days": 5}
    # intro was printed
    assert any("trip facts" in line for line in out_lines)


@pytest.mark.asyncio
async def test_prompt_form_retries_on_validation_error():
    """First answer fails int validation; second succeeds; field collected."""
    schema = {
        "fields": [
            {"name": "days", "type": "int", "required": True, "min": 1, "max": 14},
        ],
        "cancel_keywords": [],
    }
    answers = iter(["abc", "5"])
    out_lines: list[str] = []

    async def _stub(prefix: str) -> str | None:
        return next(answers)

    result = await prompt_clarify_form(
        schema, prompt_fn=_stub, writer=out_lines.append,
    )
    assert result.cancelled is False
    assert result.fields == {"days": 5}
    # error message was printed for the bad input
    assert any("integer" in line for line in out_lines)


@pytest.mark.asyncio
async def test_prompt_form_cancel_keyword_bails():
    schema = {
        "fields": [
            {"name": "x", "type": "string", "required": True},
            {"name": "y", "type": "string", "required": True},
        ],
        "cancel_keywords": ["cancel"],
    }
    answers = iter(["Tokyo", "cancel"])

    async def _stub(prefix: str) -> str | None:
        return next(answers)

    result = await prompt_clarify_form(schema, prompt_fn=_stub, writer=lambda _: None)
    assert result.cancelled is True
    assert result.fields == {}


@pytest.mark.asyncio
async def test_prompt_form_eof_bails():
    """Ctrl-D (prompt_fn returns None) cancels the whole form."""
    schema = {
        "fields": [
            {"name": "x", "type": "string", "required": True},
        ],
        "cancel_keywords": [],
    }

    async def _stub(prefix: str) -> str | None:
        return None

    result = await prompt_clarify_form(schema, prompt_fn=_stub, writer=lambda _: None)
    assert result.cancelled is True
    assert result.fields == {}


@pytest.mark.asyncio
async def test_prompt_form_optional_field_can_be_skipped():
    schema = {
        "fields": [
            {"name": "destination", "type": "string", "required": True},
            {"name": "notes", "type": "string", "required": False},
        ],
        "cancel_keywords": [],
    }
    answers = iter(["Tokyo", ""])

    async def _stub(prefix: str) -> str | None:
        return next(answers)

    result = await prompt_clarify_form(schema, prompt_fn=_stub, writer=lambda _: None)
    assert result.cancelled is False
    assert result.fields == {"destination": "Tokyo"}


def test_result_dataclass_minimal():
    r = ClarifyFormResult(fields={"x": 1}, cancelled=False)
    assert r.fields == {"x": 1}
    assert r.cancelled is False


# ── Surface rendering of (d) protocol: confirmed / ambiguous / unknowns ──


@pytest.mark.asyncio
async def test_prompt_form_renders_confirmed_fields_and_accepts_enter() -> None:
    """When the schema carries ``confirmed_fields`` from the prefill
    scan, the user must see the inferred values up-front and be able
    to accept each by hitting Enter on an empty line. The accepted
    value lands in the result exactly as the audit reported."""
    schema = {
        "mode": "form",
        "intro": "",
        "fields": [
            {"name": "destination", "type": "string", "required": True, "prompt": "city"},
            {
                "name": "days",
                "type": "int",
                "required": True,
                "prompt": "days",
                "min": 1,
                "max": 30,
            },
        ],
        "cancel_keywords": [],
        "timeout_hours": 24,
        "confirmed_fields": [
            {"name": "destination", "value": "Tokyo", "source": "auto_prefill"},
        ],
        "ambiguous_fields": [
            {"name": "days", "reason": "duration not stated"},
        ],
        "unknown_mentions": [],
    }
    answers = iter(["", "5"])  # Enter on destination → confirm; "5" for days

    async def _stub(_prefix: str) -> str | None:
        return next(answers)

    out: list[str] = []
    result = await prompt_clarify_form(schema, prompt_fn=_stub, writer=out.append)

    assert result.cancelled is False
    assert result.fields == {"destination": "Tokyo", "days": 5}
    transcript = "\n".join(out)
    assert "noticed details" in transcript
    assert "destination" in transcript
    assert "Tokyo" in transcript
    assert "duration not stated" in transcript


@pytest.mark.asyncio
async def test_prompt_form_confirmed_field_can_be_overridden() -> None:
    """A user who disagrees with the inferred value must be able to
    type a new value to override. The overridden value wins; the
    confirmed value is discarded."""
    schema = {
        "mode": "form",
        "intro": "",
        "fields": [
            {"name": "destination", "type": "string", "required": True, "prompt": "city"},
        ],
        "cancel_keywords": [],
        "timeout_hours": 24,
        "confirmed_fields": [
            {"name": "destination", "value": "Tokyo", "source": "auto_prefill"},
        ],
    }

    async def _stub(_prefix: str) -> str | None:
        return "Osaka"

    result = await prompt_clarify_form(schema, prompt_fn=_stub, writer=lambda _: None)
    assert result.cancelled is False
    assert result.fields == {"destination": "Osaka"}


@pytest.mark.asyncio
async def test_prompt_form_renders_unknown_mentions() -> None:
    """``unknown_mentions`` must surface verbatim so the user knows the
    system noticed something it could not map to a field."""
    schema = {
        "mode": "form",
        "intro": "",
        "fields": [
            {"name": "destination", "type": "string", "required": True, "prompt": "city"},
        ],
        "cancel_keywords": [],
        "timeout_hours": 24,
        "confirmed_fields": [],
        "ambiguous_fields": [],
        "unknown_mentions": [
            {"text": "next month", "guess": "departure timing?"},
        ],
    }

    async def _stub(_prefix: str) -> str | None:
        return "Tokyo"

    out: list[str] = []
    await prompt_clarify_form(schema, prompt_fn=_stub, writer=out.append)
    transcript = "\n".join(out)
    assert "next month" in transcript
    assert "departure timing?" in transcript


@pytest.mark.asyncio
async def test_prompt_form_without_prefill_payload_unchanged() -> None:
    """Backwards compatibility: a schema without any prefill payload
    must render exactly as before — no transparency header, no extra
    blocks, no behavioural change."""
    schema = {
        "mode": "form",
        "intro": "",
        "fields": [
            {"name": "destination", "type": "string", "required": True, "prompt": "city"},
        ],
        "cancel_keywords": [],
        "timeout_hours": 24,
    }

    async def _stub(_prefix: str) -> str | None:
        return "Tokyo"

    out: list[str] = []
    result = await prompt_clarify_form(schema, prompt_fn=_stub, writer=out.append)
    assert result.fields == {"destination": "Tokyo"}
    transcript = "\n".join(out)
    assert "noticed details" not in transcript
