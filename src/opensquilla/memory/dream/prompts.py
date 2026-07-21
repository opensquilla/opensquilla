"""Dream provider prompts and constrained patch parsing."""

from __future__ import annotations

import json
from typing import Any

from opensquilla.memory.dream.models import (
    PromotionCandidate,
    PromotionPatch,
    PromotionPatchOperation,
)


def _iter_json_objects(text: str) -> list[str]:
    """Yield every brace-balanced ``{...}`` span in ``text``, outermost only.

    A depth counter that ignores braces inside JSON strings (respecting ``\\``
    escapes) isolates each top-level object. Unlike a greedy ``\\{.*\\}`` regex,
    trailing prose or a second block after the payload does not get swallowed into
    one unparseable span — the source of the recurrent "Extra data" apply errors
    when the promotion model appends commentary after its JSON.
    """
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start : index + 1])
                start = -1
    return spans


def promotion_patch_prompt(current_memory_md: str, candidates: list[PromotionCandidate]) -> str:
    candidate_lines = []
    for candidate in candidates:
        candidate_lines.append(
            "\n".join(
                [
                    f"- candidate_id: {candidate.candidate_id}",
                    f"  score: {candidate.score:.3f}",
                    f"  reasons: {', '.join(candidate.reasons)}",
                    f"  snippet: {candidate.snippet}",
                ]
            )
        )
    return (
        "You are updating OpenSquilla MEMORY.md as curated long-term memory.\n"
        "Return JSON only with an operations array. Do not write dated logs, scores, "
        "or source metadata into MEMORY.md.\n"
        "Preserve any inline-code token of the form `model:<id>` exactly as written, "
        "backticks and all. The prose around it may be reworded or merged freely, but "
        "that token is a machine-read marker: changing, splitting, or unquoting it "
        "silently drops a routing preference.\n\n"
        "Allowed operations:\n"
        '- {"op":"upsert","candidate_ids":["..."],"section":"User Preferences",'
        '"memory_id":"mem_short_stable_id","text":"- durable memory"}\n'
        '- {"op":"merge","candidate_ids":["..."],"section":"Project Practices",'
        '"memory_id":"mem_short_stable_id","text":"- consolidated memory"}\n'
        '- {"op":"skip","candidate_ids":["..."],"reason":"not durable"}\n\n'
        f"Current MEMORY.md:\n<<<\n{current_memory_md}\n>>>\n\n"
        "Ranked candidates:\n"
        + "\n\n".join(candidate_lines)
        + "\n\nJSON:"
    )


def _json_payload(text: str) -> dict[str, Any]:
    dicts: list[dict[str, Any]] = []
    for span in _iter_json_objects(text):
        try:
            parsed = json.loads(span)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            dicts.append(parsed)
    if not dicts:
        raise ValueError(f"Dream response did not contain JSON: {text[:300]}")
    # Prefer the patch object; preamble examples or trailing notes may parse too.
    for parsed in dicts:
        if "operations" in parsed:
            return parsed
    return dicts[0]


def parse_promotion_patch(text: str, candidates: list[PromotionCandidate]) -> PromotionPatch:
    payload = _json_payload(text)
    candidate_ids = {candidate.candidate_id for candidate in candidates}
    operations_raw = payload.get("operations") or []
    if not isinstance(operations_raw, list):
        raise ValueError("Dream operations must be a list")
    operations: list[PromotionPatchOperation] = []
    assigned_candidate_ids: set[str] = set()
    for raw in operations_raw:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "")
        if op not in {"upsert", "merge", "skip"}:
            continue
        ids_raw = raw.get("candidate_ids") or []
        ids = [str(value) for value in ids_raw if isinstance(value, str)]
        if ids == ["auto"]:
            ids = sorted(candidate_ids)
        ids = list(dict.fromkeys(value for value in ids if value in candidate_ids))
        if not ids:
            continue
        duplicate_ids = assigned_candidate_ids.intersection(ids)
        if duplicate_ids:
            raise ValueError(
                "Dream candidate assigned to multiple operations: "
                + ", ".join(sorted(duplicate_ids))
            )
        text_value = str(raw.get("text") or "")
        if op in {"upsert", "merge"} and not text_value.strip():
            raise ValueError(f"Dream {op} operation must contain non-empty text")
        assigned_candidate_ids.update(ids)
        operations.append(
            PromotionPatchOperation(
                op=op,
                candidate_ids=ids,
                section=str(raw.get("section") or "Long-Term Memory"),
                memory_id=str(raw.get("memory_id") or ""),
                text=text_value,
                replaces_memory_id=(
                    str(raw["replaces_memory_id"])
                    if isinstance(raw.get("replaces_memory_id"), str)
                    else None
                ),
                replaces_memory_ids=[
                    str(value)
                    for value in raw.get("replaces_memory_ids", [])
                    if isinstance(value, str)
                ],
                expected_old_text_sha256=(
                    str(raw["expected_old_text_sha256"])
                    if isinstance(raw.get("expected_old_text_sha256"), str)
                    else None
                ),
                reason=str(raw.get("reason")) if raw.get("reason") is not None else None,
            )
        )
    return PromotionPatch(operations=operations)
