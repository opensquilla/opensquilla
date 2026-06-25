"""Unit tests for clarify_schema surface protocol (PR5)."""

from __future__ import annotations

import json

from opensquilla.skills.meta.clarify_schema import (
    field_to_protocol,
    schema_to_protocol,
)
from opensquilla.skills.meta.types import ClarifyField, ClarifyStepConfig


def test_field_to_protocol_minimal():
    f = ClarifyField(name="x", type="string", required=True, prompt="hi")
    payload = field_to_protocol(f)
    assert payload == {
        "name": "x",
        "type": "string",
        "required": True,
        "prompt": "hi",
    }
    # No default/min/max/max_chars/choices keys when unset.
    assert "default" not in payload
    assert "min" not in payload
    assert "max" not in payload
    assert "max_chars" not in payload
    assert "choices" not in payload


def test_field_to_protocol_full():
    f = ClarifyField(
        name="days", type="int", required=True, prompt="days",
        min=1, max=14,
    )
    payload = field_to_protocol(f)
    assert payload == {
        "name": "days",
        "type": "int",
        "required": True,
        "prompt": "days",
        "min": 1,
        "max": 14,
    }


def test_field_to_protocol_enum_with_default():
    f = ClarifyField(
        name="budget", type="enum",
        choices=("budget", "mid", "premium"), default="mid",
        prompt="budget",
    )
    payload = field_to_protocol(f)
    assert payload["choices"] == ["budget", "mid", "premium"]
    assert payload["default"] == "mid"
    assert payload["required"] is False


def test_field_to_protocol_zh_enum_options_keep_values_but_localize_labels():
    f = ClarifyField(
        name="language",
        type="enum",
        choices=("en", "zh", "mixed"),
        default="zh",
        prompt="输出语言",
    )

    payload = field_to_protocol(f, language="zh")

    assert payload["choices"] == ["en", "zh", "mixed"]
    assert payload["options"] == [
        {"value": "en", "label": "英文"},
        {"value": "zh", "label": "中文"},
        {"value": "mixed", "label": "中英混合"},
    ]
    assert payload["default"] == "zh"


def test_field_to_protocol_en_enum_options_are_english_labels():
    f = ClarifyField(
        name="time_window",
        type="enum",
        choices=("LAST_WEEK", "LAST_MONTH", "LAST_QUARTER"),
        default="LAST_MONTH",
        prompt="Time window",
    )

    payload = field_to_protocol(f, language="en")

    assert payload["choices"] == ["LAST_WEEK", "LAST_MONTH", "LAST_QUARTER"]
    assert payload["options"] == [
        {"value": "LAST_WEEK", "label": "Last week"},
        {"value": "LAST_MONTH", "label": "Last month"},
        {"value": "LAST_QUARTER", "label": "Last quarter"},
    ]


def test_field_to_protocol_xml_escapes_prompt():
    """Author-supplied prompt strings are XML-escaped so embedding the
    payload in HTML/XML cannot be hijacked by injecting tags."""
    f = ClarifyField(
        name="x", type="string", required=True,
        prompt="<script>alert('XSS')</script>",
    )
    payload = field_to_protocol(f)
    assert "<script>" not in payload["prompt"]
    assert "&lt;script&gt;" in payload["prompt"]


def test_schema_to_protocol_full():
    schema = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="destination", type="string", required=True,
                         prompt="目的地"),
            ClarifyField(name="days", type="int", required=True, min=1, max=14,
                         prompt="天数"),
        ),
        intro="需要确认几件事。",
        cancel_keywords=("取消", "cancel"),
        timeout_hours=24,
        nl_extract=True,
    )
    payload = schema_to_protocol(schema)
    assert payload["mode"] == "form"
    assert payload["intro"] == "需要确认几件事。"
    assert payload["timeout_hours"] == 24
    assert payload["nl_extract"] is True
    assert payload["cancel_keywords"] == ["取消", "cancel"]
    assert len(payload["fields"]) == 2
    assert payload["fields"][0]["name"] == "destination"
    assert payload["fields"][1]["min"] == 1


def test_schema_to_protocol_passes_language_to_field_options():
    schema = ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(
                name="export_docx",
                type="enum",
                choices=("YES", "NO"),
                default="NO",
                prompt="是否导出 DOCX",
            ),
        ),
        intro="请确认",
    )

    payload = schema_to_protocol(schema, language="zh")

    assert payload["fields"][0]["options"] == [
        {"value": "YES", "label": "是"},
        {"value": "NO", "label": "否"},
    ]


def test_schema_to_protocol_intro_override_takes_precedence():
    schema = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string", required=True),),
        intro="schema intro",
    )
    payload = schema_to_protocol(schema, intro_override="step-specific intro")
    assert payload["intro"] == "step-specific intro"


def test_schema_to_protocol_intro_override_empty_falls_back_to_schema():
    schema = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string", required=True),),
        intro="schema intro",
    )
    payload = schema_to_protocol(schema, intro_override="")
    assert payload["intro"] == "schema intro"


def test_schema_to_protocol_intro_xml_escaped():
    schema = ClarifyStepConfig(
        mode="form",
        fields=(ClarifyField(name="x", type="string", required=True),),
        intro="<b>bold</b> & co",
    )
    payload = schema_to_protocol(schema)
    assert "<b>" not in payload["intro"]
    assert "&lt;b&gt;" in payload["intro"]
    assert "&amp;" in payload["intro"]


def test_schema_to_protocol_is_json_serialisable():
    """The whole point of the protocol is to be JSON-safe so WS / RPC
    layers can send it without custom encoders."""
    schema = ClarifyStepConfig(
        mode="chat",
        fields=(
            ClarifyField(name="destination", type="string", required=True),
            ClarifyField(name="budget", type="enum",
                         choices=("a", "b"), default="a"),
        ),
        intro="hi",
        cancel_keywords=("cancel",),
    )
    payload = schema_to_protocol(schema)
    # Must round-trip through json without losing anything.
    serialised = json.dumps(payload, ensure_ascii=False)
    restored = json.loads(serialised)
    assert restored == payload


def test_schema_to_protocol_empty_fields_list():
    """Edge case: parser allows fields=() for some test fixtures.
    schema_to_protocol must not crash on it."""
    schema = ClarifyStepConfig(mode="form", fields=())
    payload = schema_to_protocol(schema)
    assert payload["fields"] == []
    assert payload["mode"] == "form"


# ── Step (d): confirmed_fields / ambiguous_fields / unknown_mentions ──


def _schema_with_two_fields() -> ClarifyStepConfig:
    return ClarifyStepConfig(
        mode="form",
        fields=(
            ClarifyField(name="city", type="string", required=True),
            ClarifyField(name="days", type="int", required=True, min=1, max=30),
        ),
    )


def test_protocol_omits_prefill_keys_when_no_audit() -> None:
    """Backwards compatibility: surfaces that don't render the new
    keys must continue to receive exactly the historical payload
    shape when no prefill audit was attached."""
    payload = schema_to_protocol(_schema_with_two_fields())
    assert "confirmed_fields" not in payload
    assert "ambiguous_fields" not in payload
    assert "unknown_mentions" not in payload


def test_protocol_renders_confirmed_fields_when_prefilled() -> None:
    """Step (d): when the prefill scan landed values, the surface
    payload carries an entry per inferred field with the source
    label so the surface can render 'we noticed X — please confirm'.

    Hallucinated audit names (a field not in the schema) must be
    filtered out — the schema's field whitelist is the authority."""
    payload = schema_to_protocol(
        _schema_with_two_fields(),
        confirmed_fields={"city": "Tokyo", "totally_made_up": "x"},
        prefill_audit={
            "source": "auto_prefill",
            "fields": ["city", "totally_made_up"],
            "ambiguous": [{"name": "days", "reason": "duration not stated"}],
            "unknown_mentions": [{"text": "next month", "guess": ""}],
        },
    )
    assert payload["confirmed_fields"] == [
        {"name": "city", "value": "Tokyo", "source": "auto_prefill"},
    ]
    assert payload["ambiguous_fields"] == [
        {"name": "days", "reason": "duration not stated"},
    ]
    # ``unknown_mentions`` are XML-escaped at the protocol boundary so
    # angle brackets cannot leak into a Web surface as live HTML.
    assert payload["unknown_mentions"] == [{"text": "next month"}]


def test_protocol_unknown_mentions_escape_angle_brackets() -> None:
    """Defence in depth: ``unknown_mentions`` and ``ambiguous_fields``
    text comes from user-mentioned spans the model echoed back. The
    surface payload crosses HTML / XML rendering boundaries so escape
    every quoted span at the protocol boundary."""
    payload = schema_to_protocol(
        _schema_with_two_fields(),
        confirmed_fields={"city": "Tokyo"},
        prefill_audit={
            "source": "auto_prefill",
            "fields": ["city"],
            "ambiguous": [{"name": "days", "reason": "<script>"}],
            "unknown_mentions": [{"text": "<b>oops</b>", "guess": "<i>?</i>"}],
        },
    )
    ambiguous = payload["ambiguous_fields"][0]
    assert "<script>" not in ambiguous["reason"]
    mention = payload["unknown_mentions"][0]
    assert mention["text"] == "&lt;b&gt;oops&lt;/b&gt;"
    assert mention.get("guess") == "&lt;i&gt;?&lt;/i&gt;"


def test_protocol_drops_audit_entries_for_unknown_field_names() -> None:
    """An audit listing a hallucinated field name in ``ambiguous`` must
    be dropped so a regression in the executor cannot redirect the
    surface's reprompt to a fake field."""
    payload = schema_to_protocol(
        _schema_with_two_fields(),
        confirmed_fields={"city": "Tokyo"},
        prefill_audit={
            "source": "auto_prefill",
            "fields": ["city"],
            "ambiguous": [{"name": "phantom_field", "reason": "x"}],
            "unknown_mentions": [],
        },
    )
    assert payload["ambiguous_fields"] == []
