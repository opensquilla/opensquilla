"""Tests for gateway attachment validation.

The gateway accepts image/*, application/pdf, and text-family MIMEs
(text/plain, text/markdown, text/html, text/csv, application/json). The
validator sniffs MIME from decoded bytes and prefers the sniffed type on
mismatch, the per-turn cap is 10, and a {file_uuid: ...} reference shape is
accepted for the upload store.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from opensquilla.gateway.rpc_session_send_inputs import (
    ALLOWED_MEDIA_TYPES as _ALLOWED_MEDIA_TYPES,
)
from opensquilla.gateway.rpc_session_send_inputs import (
    MAX_ATTACHMENT_BYTES as _MAX_ATTACHMENT_BYTES,
)
from opensquilla.gateway.rpc_session_send_inputs import (
    MAX_ATTACHMENTS as _MAX_ATTACHMENTS,
)
from opensquilla.gateway.rpc_session_send_inputs import (
    MAX_TEXT_ATTACHMENT_BYTES as _MAX_TEXT_ATTACHMENT_BYTES,
)
from opensquilla.gateway.rpc_session_send_inputs import (
    validate_session_attachments,
)


def _validate_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    return validate_session_attachments(raw_attachments, logger=None)


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _attach(media_type: str, payload: bytes, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"type": media_type, "data": _b64(payload)}
    item.update(extra)
    return item


# ---------------------------------------------------------------------------
# Allow-list locked at exactly the 10 supported MIMEs.
# ---------------------------------------------------------------------------

def test_allowed_media_types_set_contents() -> None:
    assert _ALLOWED_MEDIA_TYPES == {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/html",
        "text/csv",
        "application/json",
    }


def test_max_attachments_per_turn_is_ten() -> None:
    assert _MAX_ATTACHMENTS == 10


def test_rpc_session_attachment_helpers_live_in_send_input_boundary() -> None:
    import ast
    from pathlib import Path

    from opensquilla.gateway import rpc_session_send_inputs, rpc_sessions

    source = Path(rpc_sessions.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    boundary_path = Path(rpc_session_send_inputs.__file__)

    assert boundary_path.exists()

    boundary_tree = ast.parse(boundary_path.read_text(encoding="utf-8"))
    top_level_functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    boundary_defs = {
        node.name
        for node in ast.walk(boundary_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_validate_attachments" not in top_level_functions
    assert "_resolve_attachments" not in top_level_functions
    assert {
        "validate_session_attachments",
        "resolve_session_attachments",
    } <= boundary_defs


# ---------------------------------------------------------------------------
# Inline acceptance for each non-image MIME class.
# ---------------------------------------------------------------------------

def test_pdf_inline_accepted() -> None:
    pdf_bytes = b"%PDF-1.4\n%fake one-page pdf body\n"
    out = _validate_attachments([_attach("application/pdf", pdf_bytes, name="r.pdf")])
    assert len(out) == 1
    assert out[0]["type"] == "application/pdf"
    assert out[0]["data"] == _b64(pdf_bytes)


@pytest.mark.parametrize(
    ("claimed_mime", "payload"),
    [
        ("text/plain", b"hello world\n"),
        ("text/csv", b"col_a,col_b\n1,2\n3,4\n"),
        ("application/json", b'{"k": "v"}'),
        ("text/markdown", b"# title\n\nbody\n"),
    ],
)
def test_text_csv_json_inline_accepted(claimed_mime: str, payload: bytes) -> None:
    name = f"f.{claimed_mime.split('/')[-1]}"
    out = _validate_attachments([_attach(claimed_mime, payload, name=name)])
    assert len(out) == 1
    assert out[0]["type"] == claimed_mime


def test_html_inline_accepted() -> None:
    html = b"<html><body>hi</body></html>"
    out = _validate_attachments([_attach("text/html", html, name="page.html")])
    assert len(out) == 1
    assert out[0]["type"] == "text/html"


# ---------------------------------------------------------------------------
# Rejection paths.
# ---------------------------------------------------------------------------

def test_unknown_mime_rejected() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        _validate_attachments(
            [_attach("application/x-shellscript", b"#!/bin/sh\necho hi\n", name="x.sh")]
        )


def test_oversize_rejected() -> None:
    payload = b"%PDF-1.4\n" + b"a" * (_MAX_ATTACHMENT_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds"):
        _validate_attachments([_attach("application/pdf", payload, name="big.pdf")])


def test_text_family_above_direct_cap_rejected() -> None:
    payload = b"a" * (_MAX_TEXT_ATTACHMENT_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds"):
        _validate_attachments([_attach("text/plain", payload, name="big.txt")])


def test_too_many_attachments_rejected() -> None:
    items = [_attach("text/plain", b"x", name=f"f{i}.txt") for i in range(_MAX_ATTACHMENTS + 1)]
    with pytest.raises(ValueError, match="at most"):
        _validate_attachments(items)


# ---------------------------------------------------------------------------
# MIME sniffing semantics.
# ---------------------------------------------------------------------------

def test_mime_sniff_overrides_client_claim() -> None:
    """A claimed text/plain payload that is actually PDF magic is upgraded.

    When the sniffed MIME is in the allow-list and differs from the client
    claim, the sniffed type wins.
    """
    pdf_bytes = b"%PDF-1.4\nbody\n"
    out = _validate_attachments([_attach("text/plain", pdf_bytes, name="weird.txt")])
    assert out[0]["type"] == "application/pdf"


def test_claimed_pdf_without_magic_bytes_rejected() -> None:
    """Claimed application/pdf without %PDF- magic is hard-rejected.

    A large blob of arbitrary bytes claiming PDF is a text-bomb vector;
    sniffer must not silently downgrade. Locked decision: raise ValueError
    matching '415' or 'magic'.
    """
    not_a_pdf = b"definitely not a pdf, just text bytes\n"
    with pytest.raises(ValueError, match=r"(magic|415|application/pdf)"):
        _validate_attachments([_attach("application/pdf", not_a_pdf, name="liar.pdf")])


def test_mime_sniff_logs_warning_on_mismatch() -> None:
    """Mismatch between claimed and sniffed MIME emits a structured warning.

    The validator accepts a structured logger; capture via a tiny fake logger
    rather than caplog to test the contract, not the framework plumbing.
    """
    captured: list[tuple[str, dict[str, Any]]] = []

    class FakeLogger:
        def warning(self, event: str, **kwargs: Any) -> None:
            captured.append((event, kwargs))

    pdf_bytes = b"%PDF-1.4\nbody\n"
    validate_session_attachments(
        [_attach("text/plain", pdf_bytes, name="weird.txt")],
        logger=FakeLogger(),
    )

    assert any(
        "mime" in event.lower() and "mismatch" in event.lower() for event, _ in captured
    ), captured
    mismatch = next(kwargs for event, kwargs in captured if "mismatch" in event)
    assert mismatch.get("claimed") == "text/plain"
    assert mismatch.get("sniffed") == "application/pdf"


# ---------------------------------------------------------------------------
# file_uuid reference shape.
# ---------------------------------------------------------------------------

def test_file_uuid_reference_resolved() -> None:
    """Validator accepts {file_uuid, name, mime} without inline data.

    The validator must not crash on the staged upload shape and must thread
    ``file_uuid`` through for downstream materialization.
    """
    out = _validate_attachments(
        [
            {
                "file_uuid": "u-deadbeef",
                "mime": "application/pdf",
                "name": "big.pdf",
            }
        ]
    )
    assert len(out) == 1
    assert out[0]["file_uuid"] == "u-deadbeef"
    assert out[0]["type"] == "application/pdf"
    assert "data" not in out[0]


def test_attachment_with_both_data_and_file_uuid_rejected() -> None:
    """Validator rejects 400 if an attachment carries both inline data AND file_uuid.

    Both fields means the client was confused; pick one instead of silently
    coercing.
    """
    item = _attach("application/pdf", b"%PDF-1.4\n", name="x.pdf")
    item["file_uuid"] = "u-1234"
    with pytest.raises(ValueError, match=r"(both|exactly one)"):
        _validate_attachments([item])
