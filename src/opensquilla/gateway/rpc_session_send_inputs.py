"""Input normalization helpers for gateway session send RPCs."""

from __future__ import annotations

from typing import Any

from opensquilla.gateway import attachment_ingest

ALLOWED_MEDIA_TYPES = attachment_ingest.ALLOWED_MEDIA_TYPES
MAX_ATTACHMENT_BYTES = attachment_ingest.MAX_ATTACHMENT_BYTES
MAX_STAGED_PDF_BYTES = attachment_ingest.MAX_STAGED_PDF_BYTES
MAX_TEXT_ATTACHMENT_BYTES = attachment_ingest.TEXT_ATTACHMENT_BYTES
MAX_TOTAL_ATTACHMENT_BYTES = attachment_ingest.MAX_TOTAL_ATTACHMENT_BYTES
MAX_ATTACHMENTS = attachment_ingest.MAX_ATTACHMENTS
attachment_media_type = attachment_ingest.attachment_media_type
normalize_attachments = attachment_ingest.normalize_attachments
sniff_mime_from_bytes = attachment_ingest.sniff_mime_from_bytes

_ELEVATED_MODES = frozenset({"on", "bypass", "full"})


def trusted_elevated_hint(is_owner: bool, source_hint: dict[str, Any]) -> str | None:
    """Return an operator-owned elevated hint, or None."""

    value = source_hint.get("elevated")
    if isinstance(value, str) and value in _ELEVATED_MODES and is_owner:
        return value
    return None


async def resolve_session_attachments(
    validated: list[dict[str, Any]],
    store: Any | None = None,
    *,
    material_root: Any | None = None,
    session_id: str | None = None,
    disk_budget_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Resolve validated upload references into runtime attachment payloads."""

    resolved, _consumed = await attachment_ingest.resolve_attachments(
        validated,
        store=store,
        material_root=material_root,
        session_id=session_id,
        disk_budget_bytes=disk_budget_bytes,
    )
    return resolved


def validate_session_attachments(
    raw_attachments: Any,
    *,
    logger: Any,
) -> list[dict[str, Any]]:
    """Validate attachment RPC payloads using the gateway ingest contract."""

    validated, _failures = attachment_ingest.validate_attachments(
        raw_attachments,
        logger=logger,
    )
    return validated


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _first_dict_value(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return None


def normalize_memory_capture_controls(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize RPC/chat memory-capture controls onto snake_case fields."""

    source_hint = params.get("_source")
    if not isinstance(source_hint, dict):
        source_hint = {}

    no_memory_capture = _coerce_optional_bool(
        params.get("no_memory_capture", params.get("noMemoryCapture"))
    )
    if no_memory_capture is None:
        no_memory_capture = _coerce_optional_bool(
            source_hint.get("no_memory_capture", source_hint.get("noMemoryCapture"))
        )

    input_provenance = _first_dict_value(
        params.get("input_provenance"),
        params.get("inputProvenance"),
        source_hint.get("input_provenance"),
        source_hint.get("inputProvenance"),
    )
    provenance_kind = (
        params.get("input_provenance_kind")
        or params.get("inputProvenanceKind")
        or params.get("provenance_kind")
        or source_hint.get("input_provenance_kind")
        or source_hint.get("inputProvenanceKind")
        or source_hint.get("provenance_kind")
    )
    if input_provenance is None and provenance_kind:
        input_provenance = {"kind": str(provenance_kind)}
    elif input_provenance is not None and "kind" not in input_provenance and provenance_kind:
        input_provenance["kind"] = str(provenance_kind)

    run_kind = params.get("run_kind", params.get("runKind"))
    if run_kind is None:
        run_kind = source_hint.get("run_kind", source_hint.get("runKind"))

    return {
        "no_memory_capture": bool(no_memory_capture),
        "input_provenance": input_provenance,
        "run_kind": str(run_kind) if run_kind is not None and str(run_kind) else None,
    }
