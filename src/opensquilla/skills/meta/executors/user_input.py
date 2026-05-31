"""Executor for the user_input meta-skill step.

Behavior (design §8.1):
  1. If skip_if (Jinja boolean) evaluates truthy against inputs + outputs,
     return immediately with an empty output ("" markdown). The step is
     treated like a successfully-completed pass-through.
  2. Otherwise, try to claim awaiting_user state via the injected DAO.
     On success, raise MetaPaused — the scheduler catches it ahead of
     CancelledError and emits a paused MetaResult.
     On failure (CAS rowcount==0 or partial unique index conflict),
     raise RuntimeError to signal normal step failure; on_failure
     substitute may then fire.

The executor itself is async to fit the scheduler's contract; DAO calls
are sync (MetaRunWriter holds a sync sqlite3 connection) and run off
the event loop via `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol

from opensquilla.skills.meta.templating import evaluate_when, render_with_args
from opensquilla.skills.meta.types import (
    ClarifyField,
    ClarifyStepConfig,
    MetaPaused,
    MetaStep,
)

log = logging.getLogger(__name__)

_EN_INTRO = (
    "A few required details are still missing. Please provide the fields "
    "below so I can continue."
)


def _contains_cjk(text: str) -> bool:
    return any("\u3400" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff" for ch in text)


def _english_field_prompt(field: ClarifyField) -> str:
    prompt = (field.prompt or "").strip()
    if not prompt:
        return field.name.replace("_", " ").title()
    for delimiter in (" / ", "/", " | ", "|"):
        if delimiter in prompt:
            candidates = [part.strip() for part in prompt.split(delimiter)]
            for candidate in reversed(candidates):
                if candidate and not _contains_cjk(candidate):
                    return candidate
    if _contains_cjk(prompt):
        return field.name.replace("_", " ").title()
    return prompt


def _localize_clarify_config(
    cfg: ClarifyStepConfig,
    inputs: dict[str, Any],
) -> ClarifyStepConfig:
    if str(inputs.get("user_language") or "").lower() != "en":
        return cfg
    fields = tuple(
        ClarifyField(
            name=field.name,
            type=field.type,
            required=field.required,
            prompt=_english_field_prompt(field),
            choices=field.choices,
            default=field.default,
            min=field.min,
            max=field.max,
            max_chars=field.max_chars,
        )
        for field in cfg.fields
    )
    intro = cfg.intro
    if not intro.strip() or _contains_cjk(intro):
        intro = _EN_INTRO
    return ClarifyStepConfig(
        mode=cfg.mode,
        fields=fields,
        skip_if=cfg.skip_if,
        cancel_keywords=tuple(kw for kw in cfg.cancel_keywords if not _contains_cjk(kw)),
        timeout_hours=cfg.timeout_hours,
        intro=intro,
        nl_extract=cfg.nl_extract,
        nl_extract_tier=cfg.nl_extract_tier,
    )


class _DAOProto(Protocol):
    """Minimal DAO surface this executor depends on (PR2 MetaRunWriter)."""

    def try_claim_awaiting(
        self,
        *,
        run_id: str,
        step_id: str,
        schema_json: str,
        session_id: str,
        inputs_json: str,
        step_outputs_json: str,
        awaiting_since: float,
    ) -> bool: ...


async def run_user_input_step(
    step: MetaStep,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, str],
    run_id: str,
    session_id: str,
    dao: _DAOProto,
    now: Callable[[], float],
) -> str:
    """Either pass through (skip_if true) or raise MetaPaused.

    Returns empty str on the pass-through path so downstream depends_on
    consumers see a defined output value. Never returns a non-empty
    string: the only "filled" content comes from the resume path,
    which writes via ``MetaOrchestrator.resume``.
    """

    cfg = step.clarify_config
    if cfg is None:
        # parser.py guarantees this won't happen for kind=user_input.
        raise RuntimeError(
            f"user_input step {step.id!r} missing clarify_config "
            f"(parser invariant violated)",
        )

    if cfg.skip_if:
        try:
            should_skip = evaluate_when(
                cfg.skip_if, inputs=inputs, outputs=outputs,
            )
        except ValueError as exc:
            # Per design §10: skip_if raising UndefinedError is treated
            # as "skip-not-applicable" — proceed to pause.
            log.warning(
                "meta_user_input.skip_if_error",
                extra={"step": step.id, "error": str(exc)},
            )
            should_skip = False
        if should_skip:
            log.info("meta_user_input.skipped", extra={"step": step.id})
            return ""

    rendered_cfg = _render_clarify_config(cfg, inputs=inputs, outputs=outputs)
    rendered_cfg = _localize_clarify_config(rendered_cfg, inputs)
    schema_json = _serialize_schema(rendered_cfg)
    inputs_json = json.dumps(inputs, ensure_ascii=False, sort_keys=True)
    step_outputs_json = json.dumps(outputs, ensure_ascii=False, sort_keys=True)

    awaiting_since = now()

    # CancelledError MUST propagate so the scheduler can tear down
    # sibling tasks consistently — see design §8.1.
    try:
        claimed = await asyncio.to_thread(
            dao.try_claim_awaiting,
            run_id=run_id,
            step_id=step.id,
            schema_json=schema_json,
            session_id=session_id,
            inputs_json=inputs_json,
            step_outputs_json=step_outputs_json,
            awaiting_since=awaiting_since,
        )
    except asyncio.CancelledError:
        raise

    if not claimed:
        raise RuntimeError(
            f"awaiting claim rejected for run_id={run_id!r} step={step.id!r} "
            f"(run is no longer 'running' or partial unique index conflict)",
        )

    raise MetaPaused(
        run_id=run_id,
        step_id=step.id,
        schema=rendered_cfg,
        intro=rendered_cfg.intro,
        language=str(inputs.get("user_language") or ""),
    )


def _render_clarify_config(
    cfg: ClarifyStepConfig,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, str],
) -> ClarifyStepConfig:
    """Render user-facing clarify copy against the live meta context.

    The parser keeps clarify schemas static, but language-sensitive forms need
    access to earlier extraction steps (for example ``LANGUAGE: en`` vs
    ``LANGUAGE: zh``). Only copy is rendered; field names, types, choices,
    defaults, and validation limits remain the parsed contract.
    """

    rendered = render_with_args(
        {
            "intro": cfg.intro,
            "fields": [
                {"prompt": field.prompt}
                for field in cfg.fields
            ],
        },
        inputs=inputs,
        outputs=outputs,
    )
    rendered_fields: list[ClarifyField] = []
    rendered_prompts = rendered.get("fields", [])
    for index, field in enumerate(cfg.fields):
        prompt = field.prompt
        if isinstance(rendered_prompts, list) and index < len(rendered_prompts):
            rendered_prompt = rendered_prompts[index].get("prompt")
            if isinstance(rendered_prompt, str):
                prompt = rendered_prompt
        rendered_fields.append(replace(field, prompt=prompt))

    intro = rendered.get("intro", cfg.intro)
    return replace(
        cfg,
        intro=intro if isinstance(intro, str) else cfg.intro,
        fields=tuple(rendered_fields),
    )


def _serialize_schema(cfg: ClarifyStepConfig) -> str:
    """JSON-serialize ClarifyStepConfig for persistence (DAO + surface renderers).

    Format mirrors clarify_config sub-tree in plan_serde.to_jsonable
    (PR2). The full meta-skill envelope is not needed here — only the
    awaiting_user row's schema column."""
    from opensquilla.skills.meta.plan_serde import clarify_config_to_jsonable

    payload = clarify_config_to_jsonable(cfg)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = ["run_user_input_step"]
