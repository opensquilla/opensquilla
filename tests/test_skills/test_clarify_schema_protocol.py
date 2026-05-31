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
