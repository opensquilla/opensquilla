"""Read-model helpers for persisted meta-skill runs.

Gateway RPC and CLI both consume these pure report builders. Keeping them
outside gateway transport code avoids coupling command-line inspection to RPC
registration and authorization glue.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from opensquilla.persistence.meta_run_writer import (
    RunRecord,
    StepRecord,
    summarize_run_record,
)
from opensquilla.skills.meta.plan_serde import from_jsonable
from opensquilla.skills.meta.types import MetaPlan

REPLAY_CONTEXT_MAX_CHARS = 4000


def json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def deserialize_plan(record: RunRecord) -> MetaPlan:
    return from_jsonable(json.loads(record.plan_snapshot_json))


def template_fields(request_template: dict[str, Any]) -> list[dict[str, Any]]:
    fields = request_template.get("fields", [])
    if not isinstance(fields, list):
        return []
    return [dict(item) for item in fields if isinstance(item, dict)]


def field_name(field: dict[str, Any]) -> str:
    name = field.get("name")
    return str(name).strip() if name is not None else ""


def template_field_names(request_template: dict[str, Any]) -> list[str]:
    return [
        name
        for field in template_fields(request_template)
        if (name := field_name(field))
    ]


def required_template_field_names(request_template: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for field in template_fields(request_template):
        name = field_name(field)
        if name and field.get("required") is True:
            names.append(name)
    return names


def filter_template_fields(
    request_template: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    allowed = set(template_field_names(request_template))
    return {
        key: value
        for key, value in fields.items()
        if key in allowed and value is not None and str(value).strip()
    }


def missing_required_fields(
    request_template: dict[str, Any],
    fields: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    for name in required_template_field_names(request_template):
        value = fields.get(name)
        if value is None or not str(value).strip():
            missing.append(name)
    return missing


def encode_preflight_fields(fields: dict[str, Any]) -> str:
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def confirmation_message(
    *,
    record: RunRecord,
    interpreted_request: str,
    fields: dict[str, Any],
) -> str:
    original_inputs = json_object(record.inputs_json)
    base = interpreted_request.strip() or str(original_inputs.get("user_message") or "").strip()
    lines = [base] if base else []
    if fields:
        lines.extend(["", "Confirmed request fields:"])
        for key in sorted(fields):
            value = fields[key]
            if value is not None and str(value).strip():
                lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "<!-- opensquilla:meta_preflight_confirmed=1 -->",
        f"<!-- opensquilla:meta_preflight_run_id={record.run_id} -->",
    ])
    if fields:
        lines.append(
            f"<!-- opensquilla:meta_preflight_fields={encode_preflight_fields(fields)} -->"
        )
    return "\n".join(lines).strip()


def _serialize_record_summary(record: RunRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "meta_skill_name": record.meta_skill_name,
        "triggered_by": record.triggered_by,
        "session_key": record.session_key,
        "turn_id": record.turn_id,
        "status": record.status,
        "started_at_ms": record.started_at_ms,
        "ended_at_ms": record.ended_at_ms,
        "failed_step_id": record.failed_step_id,
        "error_present": bool(record.error),
        "truncated_fields": list(record.truncated_fields),
        "summary": summarize_run_record(record),
    }


def _step_by_id(record: RunRecord) -> dict[str, StepRecord]:
    return {step.step_id: step for step in record.steps}


def _diff_step(left: StepRecord | None, right: StepRecord | None, step_id: str) -> dict[str, Any]:
    left_output_chars = len(left.output_text or "") if left else 0
    right_output_chars = len(right.output_text or "") if right else 0
    return {
        "step_id": step_id,
        "left_status": left.status if left else None,
        "right_status": right.status if right else None,
        "status_changed": (left.status if left else None) != (right.status if right else None),
        "output_chars_delta": right_output_chars - left_output_chars,
        "error_changed": bool(left.error if left else None) != bool(right.error if right else None),
        "declared_skill_changed": (left.declared_skill if left else None)
        != (right.declared_skill if right else None),
        "effective_skill_changed": (left.effective_skill if left else None)
        != (right.effective_skill if right else None),
    }


def build_run_diff(left: RunRecord, right: RunRecord) -> dict[str, Any]:
    left_steps = _step_by_id(left)
    right_steps = _step_by_id(right)
    step_ids = sorted(set(left_steps) | set(right_steps))
    return {
        "left": _serialize_record_summary(left),
        "right": _serialize_record_summary(right),
        "status_changed": left.status != right.status,
        "failed_step_changed": left.failed_step_id != right.failed_step_id,
        "final_text_chars_delta": len(right.final_text or "") - len(left.final_text or ""),
        "step_count_delta": len(right.steps) - len(left.steps),
        "metadata": {
            "meta_skill_digest_changed": left.meta_skill_digest != right.meta_skill_digest,
            "trigger_changed": left.triggered_by != right.triggered_by,
        },
        "steps": [
            _diff_step(left_steps.get(step_id), right_steps.get(step_id), step_id)
            for step_id in step_ids
        ],
    }


def _bounded_text(text: str, limit: int = REPLAY_CONTEXT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 25].rstrip() + "\n...[truncated for replay]"


def build_replay_request(record: RunRecord, *, mode: str = "run") -> dict[str, Any]:
    inputs = json_object(record.inputs_json)
    failed_step_id = record.failed_step_id or ""
    successful = [
        step for step in record.steps
        if step.status in {"ok", "substituted"} and step.output_text
    ]
    failed = next((step for step in record.steps if step.step_id == failed_step_id), None)
    context_lines = [
        f"Replay meta-skill run {record.run_id} ({record.meta_skill_name}).",
        f"Replay mode: {mode}.",
    ]
    user_message = str(inputs.get("user_message") or "").strip()
    if user_message:
        context_lines.append(f"Original request: {user_message}")
    if failed_step_id:
        context_lines.append(f"The prior failed step was {failed_step_id}.")
    if failed and failed.error:
        context_lines.append(f"Prior failure: {failed.error}")
    if successful:
        context_lines.append("Prior successful outputs:")
        for step in successful:
            context_lines.append(
                f"- {step.step_id}: {_bounded_text(step.output_text or '', 800)}"
            )
    return {
        "run_id": record.run_id,
        "meta_skill_name": record.meta_skill_name,
        "mode": mode,
        "failed_step_id": failed_step_id or None,
        "request": inputs,
        "message": _bounded_text("\n".join(context_lines)),
        "replay_kind": "draft",
        "live_replay": {
            "available": False,
            "reason": (
                "gateway RPC returns a replay draft; execution is started "
                "by the chat surface"
            ),
        },
    }


def _unavailable_usage() -> dict[str, Any]:
    return {
        "available": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "cost_source": "unavailable",
        "reason": "meta run persistence does not store historical usage yet",
    }


def _aggregate_summaries_usage(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    usages: list[dict[str, Any]] = []
    for summary in summaries:
        raw_usage = summary.get("usage")
        if isinstance(raw_usage, dict) and raw_usage.get("available") is True:
            usages.append(raw_usage)
    if not usages:
        return _unavailable_usage()
    cost_sources = {
        str(usage.get("cost_source") or "").strip()
        for usage in usages
        if str(usage.get("cost_source") or "").strip()
    }

    def int_total(key: str) -> int:
        return sum(int(usage.get(key) or 0) for usage in usages)

    def float_total(key: str) -> float:
        return round(sum(float(usage.get(key) or 0.0) for usage in usages), 6)

    return {
        "available": True,
        "input_tokens": int_total("input_tokens"),
        "output_tokens": int_total("output_tokens"),
        "total_tokens": int_total("total_tokens"),
        "cache_read_tokens": int_total("cache_read_tokens"),
        "cache_write_tokens": int_total("cache_write_tokens"),
        "cost_usd": float_total("cost_usd"),
        "billed_cost_usd": float_total("billed_cost_usd"),
        "estimated_cost_usd": float_total("estimated_cost_usd"),
        "cost_source": next(iter(cost_sources)) if len(cost_sources) == 1 else "mixed",
        "run_count": len(usages),
    }


def build_cost_summary(records: list[RunRecord]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_meta_skill: dict[str, int] = {}
    summaries = [summarize_run_record(record) for record in records]
    for record in records:
        by_status[record.status] = by_status.get(record.status, 0) + 1
        by_meta_skill[record.meta_skill_name] = by_meta_skill.get(record.meta_skill_name, 0) + 1
    return {
        "aggregate": {
            "run_count": len(records),
            "by_status": by_status,
            "by_meta_skill": by_meta_skill,
            "usage": _aggregate_summaries_usage(summaries),
        },
        "runs": [
            {
                "run_id": record.run_id,
                "meta_skill_name": record.meta_skill_name,
                "status": record.status,
                "started_at_ms": record.started_at_ms,
                "usage": summary["usage"],
                "steps": [
                    {
                        "step_id": step.step_id,
                        "status": step.status,
                        "effective_skill": step.effective_skill,
                        "usage": summary["steps"][index]["usage"],
                    }
                    for index, step in enumerate(record.steps)
                ],
            }
            for record, summary in zip(records, summaries, strict=True)
        ],
    }


def build_validation_summary(record: RunRecord) -> dict[str, Any]:
    plan = deserialize_plan(record)
    request_template = dict(plan.request_template)
    fields = template_fields(request_template)
    output_contract = dict(plan.output_contract)
    multimodal = output_contract.get("modalities") or output_contract.get("media")
    return {
        "run_id": record.run_id,
        "meta_skill_name": record.meta_skill_name,
        "request_template": {
            "present": bool(request_template),
            "outcome": request_template.get("outcome"),
            "field_names": [field_name(field) for field in fields if field_name(field)],
            "required_fields": required_template_field_names(request_template),
            "fields": fields,
        },
        "output_contract": output_contract,
        "eval_prompts": [dict(item) for item in plan.eval_prompts],
        "preference_keys": list(plan.preference_keys),
        "policy_tags": list(plan.policy_tags),
        "multimodal": {
            "declared": bool(multimodal),
            "modalities": multimodal if isinstance(multimodal, list) else [],
        },
    }


def build_validation_availability(record: RunRecord) -> dict[str, Any]:
    try:
        plan = deserialize_plan(record)
    except Exception:  # noqa: BLE001 - list views should fail open
        return {
            "available": False,
            "request_template": False,
            "output_contract": False,
            "eval_baseline": False,
            "field_count": 0,
            "required_field_count": 0,
            "eval_prompt_count": 0,
            "reason": "plan snapshot could not be parsed",
        }
    request_template = dict(plan.request_template)
    fields = template_fields(request_template)
    output_contract = dict(plan.output_contract)
    eval_prompt_count = len(plan.eval_prompts)
    return {
        "available": bool(request_template or output_contract or eval_prompt_count),
        "request_template": bool(request_template),
        "output_contract": bool(output_contract),
        "eval_baseline": eval_prompt_count > 0,
        "field_count": len(fields),
        "required_field_count": len(required_template_field_names(request_template)),
        "eval_prompt_count": eval_prompt_count,
    }


def build_eval_baseline(record: RunRecord) -> dict[str, Any]:
    plan = deserialize_plan(record)
    items = []
    for item in plan.eval_prompts:
        prompt = str(item.get("prompt") or "")
        rubric = item.get("rubric", [])
        if isinstance(rubric, str):
            rubric_items = [rubric]
        elif isinstance(rubric, list):
            rubric_items = [str(entry) for entry in rubric]
        else:
            rubric_items = []
        items.append({
            "name": str(item.get("name") or "eval"),
            "prompt_chars": len(prompt),
            "rubric": rubric_items,
            "judge": {
                "mode": "deterministic_metadata",
                "status": "not_run",
                "reason": "live LLM judge execution is not available in gateway history RPC",
            },
        })
    return {
        "run_id": record.run_id,
        "meta_skill_name": record.meta_skill_name,
        "available": bool(items),
        "items": items,
        "drift": {
            "status": "not_run",
            "reason": (
                "baseline metadata is exposed; scheduled judge execution is "
                "outside this local RPC"
            ),
        },
    }
