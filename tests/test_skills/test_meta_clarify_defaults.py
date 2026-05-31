"""Regression: schema-declared defaults must be materialised into
``inputs.collected.<step>`` on resume.

Without ``_merge_clarify_defaults`` the runtime would only write the
fields the user actually submitted, so any downstream Jinja template
referencing an optional field (e.g.
``{{ inputs.collected.paper_collect.language }}``) would explode with
``UndefinedError`` whenever the user skipped it — even though the
SKILL.md schema declared ``default: en``.
"""

from __future__ import annotations

from opensquilla.skills.meta.orchestrator import _merge_clarify_defaults


def _schema_dict() -> dict:
    return {
        "mode": "form",
        "fields": [
            {"name": "topic", "type": "string", "required": True},
            {"name": "paper_mode", "type": "enum", "required": True,
             "choices": ["A", "B"]},
            {"name": "language", "type": "enum",
             "choices": ["en", "zh"], "default": "en"},
            {"name": "target_length_pages", "type": "int",
             "min": 1, "max": 50, "default": 10},
            {"name": "audience", "type": "enum",
             "choices": ["academic"], "default": "academic"},
        ],
    }


def test_defaults_back_fill_when_optional_fields_omitted():
    """User submitted only the 2 required fields; the 3 optional ones
    should get their schema-declared defaults."""
    merged = _merge_clarify_defaults(
        _schema_dict(),
        {"topic": "RAG", "paper_mode": "A"},
    )
    assert merged == {
        "topic": "RAG",
        "paper_mode": "A",
        "language": "en",
        "target_length_pages": 10,
        "audience": "academic",
    }


def test_user_values_override_defaults():
    """When the user IS supplying an optional field, the default must
    not stomp on it."""
    merged = _merge_clarify_defaults(
        _schema_dict(),
        {
            "topic": "RAG",
            "paper_mode": "A",
            "language": "zh",
            "target_length_pages": 25,
        },
    )
    assert merged["language"] == "zh"
    assert merged["target_length_pages"] == 25
    assert merged["audience"] == "academic"  # unsupplied → default


def test_unknown_keys_are_dropped():
    """Prompt-injection / nl_extract leaks must not enter collected."""
    merged = _merge_clarify_defaults(
        _schema_dict(),
        {"topic": "RAG", "paper_mode": "A", "evil": "rm -rf"},
    )
    assert "evil" not in merged
    assert merged["topic"] == "RAG"


def test_empty_user_input_still_gets_defaults():
    """Edge case: user pressed cancel-form-and-submit-empty (shouldn't
    happen via the form, but nl_extract could land here)."""
    merged = _merge_clarify_defaults(_schema_dict(), {})
    # Required fields remain missing (downstream will raise — fine);
    # optional fields with defaults are populated.
    assert "topic" not in merged
    assert "paper_mode" not in merged
    assert merged["language"] == "en"
    assert merged["target_length_pages"] == 10
    assert merged["audience"] == "academic"


def test_field_without_default_stays_absent():
    """A schema field that is optional AND has no default must NOT
    appear in merged output — that's the author's explicit choice."""
    schema = {
        "fields": [
            {"name": "notes", "type": "string"},  # optional, no default
        ],
    }
    merged = _merge_clarify_defaults(schema, {})
    assert merged == {}


def test_default_none_is_treated_as_unset():
    """``default: None`` is the same as no default declaration."""
    schema = {
        "fields": [
            {"name": "notes", "type": "string", "default": None},
        ],
    }
    merged = _merge_clarify_defaults(schema, {})
    assert merged == {}


def test_no_fields_no_crash():
    """A clarify config with empty fields list is degenerate but parses;
    helper must not crash."""
    assert _merge_clarify_defaults({"fields": []}, {"x": 1}) == {}
    assert _merge_clarify_defaults({}, {"x": 1}) == {}
