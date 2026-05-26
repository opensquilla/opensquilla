"""Parse SkillSpec.composition_raw into MetaPlan; provide topological iteration."""

from __future__ import annotations

from collections.abc import Iterator
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING, Any

from opensquilla.skills.meta.types import MetaPlan, MetaStep, RouteCase

if TYPE_CHECKING:
    from opensquilla.skills.types import SkillSpec


_SUPPORTED_KINDS = frozenset(
    {"agent", "llm_classify", "llm_chat", "tool_call", "skill_exec"},
)


class MetaPlanError(ValueError):
    """Raised when a meta-skill's composition is malformed."""


def parse_meta_plan(spec: SkillSpec) -> MetaPlan | None:
    """Return a MetaPlan if ``spec`` is a meta-skill with a valid composition.

    Returns ``None`` for non-meta skills.
    Raises :class:`MetaPlanError` for meta-skills whose composition is malformed
    (missing keys, cycles, duplicate ids).
    """

    if getattr(spec, "kind", "skill") != "meta":
        return None

    composition = getattr(spec, "composition_raw", None)
    if not isinstance(composition, dict):
        raise MetaPlanError(f"meta-skill {spec.name!r}: missing or non-dict composition")

    raw_steps = composition.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise MetaPlanError(f"meta-skill {spec.name!r}: composition.steps must be a non-empty list")

    seen_ids: set[str] = set()
    steps: list[MetaStep] = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise MetaPlanError(
                f"meta-skill {spec.name!r}: step[{index}] must be a mapping",
            )
        step_id = raw.get("id")
        if not isinstance(step_id, str) or not step_id:
            raise MetaPlanError(f"meta-skill {spec.name!r}: step[{index}] missing id")
        if step_id in seen_ids:
            raise MetaPlanError(f"meta-skill {spec.name!r}: duplicate step id {step_id!r}")
        seen_ids.add(step_id)

        kind = raw.get("kind", "agent")
        if not isinstance(kind, str) or kind not in _SUPPORTED_KINDS:
            raise MetaPlanError(
                f"meta-skill {spec.name!r}: step {step_id!r} kind={kind!r} not in "
                f"{sorted(_SUPPORTED_KINDS)}",
            )

        skill_name = raw.get("skill", "")
        if kind in ("agent", "skill_exec"):
            if not isinstance(skill_name, str) or not skill_name:
                raise MetaPlanError(
                    f"meta-skill {spec.name!r}: step {step_id!r} (kind={kind}) "
                    f"missing skill",
                )
        else:
            # Informational only for llm_classify / llm_chat / tool_call;
            # default to step_id.
            if not isinstance(skill_name, str):
                raise MetaPlanError(
                    f"meta-skill {spec.name!r}: step {step_id!r} skill must be a string",
                )
            if not skill_name:
                skill_name = step_id

        depends_on_raw = raw.get("depends_on") or []
        if not isinstance(depends_on_raw, list):
            raise MetaPlanError(
                f"meta-skill {spec.name!r}: step {step_id!r} depends_on must be a list",
            )
        with_args = raw.get("with") or {}
        if not isinstance(with_args, dict):
            raise MetaPlanError(
                f"meta-skill {spec.name!r}: step {step_id!r} with must be a mapping",
            )
        route = _parse_route(spec.name, step_id, raw.get("route") or [])
        when = _parse_when(spec.name, step_id, raw.get("when"))

        output_choices = _parse_output_choices(spec.name, step_id, kind, raw.get("output_choices"))
        tool, tool_args = _parse_tool_call(
            spec.name,
            step_id,
            kind,
            raw.get("tool"),
            raw.get("tool_args"),
        )
        tool_allowlist = _parse_tool_allowlist(
            spec.name,
            step_id,
            kind,
            raw.get("tool_allowlist"),
            tool,
        )

        on_failure_raw = raw.get("on_failure")
        if on_failure_raw is None or on_failure_raw == "":
            on_failure = ""
        elif isinstance(on_failure_raw, str) and on_failure_raw.strip():
            on_failure = on_failure_raw.strip()
        else:
            raise MetaPlanError(
                f"meta-skill {spec.name!r}: step {step_id!r} on_failure must be "
                f"a non-empty string (target step id) or omitted",
            )

        steps.append(
            MetaStep(
                id=step_id,
                skill=skill_name,
                with_args=dict(with_args),
                depends_on=tuple(str(d) for d in depends_on_raw),
                when=when,
                route=route,
                kind=kind,
                output_choices=output_choices,
                tool=tool,
                tool_args=tool_args,
                tool_allowlist=tool_allowlist,
                on_failure=on_failure,
            ),
        )

    _ensure_acyclic(spec.name, steps)
    _ensure_on_failure_valid(spec.name, steps)

    triggers_raw: Any = getattr(spec, "triggers", None) or []
    if not isinstance(triggers_raw, list):
        triggers_raw = [str(triggers_raw)]
    priority = int(getattr(spec, "meta_priority", 0) or 0)
    fallback_body = getattr(spec, "content", "") or ""

    final_text_mode = str(
        getattr(spec, "final_text_mode", "auto") or "auto",
    ).strip() or "auto"

    return MetaPlan(
        name=spec.name,
        triggers=tuple(str(t) for t in triggers_raw),
        priority=priority,
        steps=tuple(steps),
        fallback_body=fallback_body,
        final_text_mode=final_text_mode,
    )


def _parse_when(skill_name: str, step_id: str, raw: object) -> str:
    """Validate an optional step-level ``when`` expression."""

    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str) or not raw.strip():
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} when must be "
            f"a non-empty string or omitted",
        )
    return raw.strip()


def topological_order(steps: tuple[MetaStep, ...]) -> Iterator[MetaStep]:
    """Yield steps in a valid topological order (depends_on satisfied first).

    Cycles or undefined deps raise :class:`MetaPlanError` (also caught at parse time).
    """

    by_id = {s.id: s for s in steps}
    graph: dict[str, list[str]] = {s.id: list(s.depends_on) for s in steps}
    try:
        sorter = TopologicalSorter(graph)
        order = list(sorter.static_order())
    except CycleError as exc:
        raise MetaPlanError(f"composition has dependency cycle: {exc.args[1]}") from exc
    for sid in order:
        if sid not in by_id:
            raise MetaPlanError(f"composition references undefined step id {sid!r}")
        yield by_id[sid]


def _parse_route(
    skill_name: str,
    step_id: str,
    raw: object,
) -> tuple[RouteCase, ...]:
    """Validate and convert a step's raw ``route`` list into RouteCase tuple.

    Each entry must be a mapping with non-empty string ``when`` + ``to``.
    Empty/missing route returns an empty tuple (no branching).
    """

    if not isinstance(raw, list):
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} route must be a list",
        )
    cases: list[RouteCase] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} route[{index}] "
                f"must be a mapping",
            )
        when = item.get("when")
        to = item.get("to")
        if not isinstance(when, str) or not when.strip():
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} route[{index}] "
                f"missing non-empty 'when' string",
            )
        if not isinstance(to, str) or not to.strip():
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} route[{index}] "
                f"missing non-empty 'to' string",
            )
        cases.append(RouteCase(when=when, to=to))
    return tuple(cases)


def _parse_output_choices(
    skill_name: str,
    step_id: str,
    kind: str,
    raw: object,
) -> tuple[str, ...]:
    """Validate ``output_choices`` for llm_classify steps.

    Required (non-empty list of non-empty strings) when kind == "llm_classify";
    must be empty/absent otherwise.
    """

    if kind == "llm_classify":
        if not isinstance(raw, list) or not raw:
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} (kind=llm_classify) "
                f"requires non-empty output_choices list",
            )
        choices: list[str] = []
        for index, item in enumerate(raw):
            if not isinstance(item, str) or not item.strip():
                raise MetaPlanError(
                    f"meta-skill {skill_name!r}: step {step_id!r} output_choices[{index}] "
                    f"must be a non-empty string",
                )
            choices.append(item)
        if len(set(choices)) != len(choices):
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} output_choices must be unique",
            )
        return tuple(choices)
    if raw not in (None, [], ()):
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} output_choices only valid "
            f"for kind=llm_classify",
        )
    return ()


def _parse_tool_call(
    skill_name: str,
    step_id: str,
    kind: str,
    tool_raw: object,
    tool_args_raw: object,
) -> tuple[str, dict[str, Any]]:
    """Validate ``tool`` + ``tool_args`` for tool_call steps."""

    if kind == "tool_call":
        if not isinstance(tool_raw, str) or not tool_raw.strip():
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} (kind=tool_call) "
                f"requires non-empty 'tool' string",
            )
        args = tool_args_raw or {}
        if not isinstance(args, dict):
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} tool_args must be a mapping",
            )
        return tool_raw, dict(args)
    if tool_raw not in (None, ""):
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} 'tool' only valid for kind=tool_call",
        )
    if tool_args_raw not in (None, {}, ()):
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} 'tool_args' only valid "
            f"for kind=tool_call",
        )
    return "", {}


def _parse_tool_allowlist(
    skill_name: str,
    step_id: str,
    kind: str,
    raw: object,
    tool: str,
) -> tuple[str, ...]:
    """Validate optional ``tool_allowlist`` for tool_call steps.

    Empty/absent ⇒ no allowlist (pre-existing behaviour). When non-empty:
    items must be non-empty strings; the step's ``tool`` must appear in
    the list; and the step's ``kind`` must be ``tool_call`` (the field
    has no meaning for other kinds).
    """

    if raw in (None, [], ()):
        return ()
    if not isinstance(raw, list):
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} tool_allowlist must "
            f"be a list of strings",
        )
    items: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise MetaPlanError(
                f"meta-skill {skill_name!r}: step {step_id!r} "
                f"tool_allowlist[{index}] must be a non-empty string",
            )
        items.append(item)
    if not items:
        return ()
    if kind != "tool_call":
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} tool_allowlist is "
            f"only valid for kind=tool_call (got kind={kind!r})",
        )
    if tool not in items:
        raise MetaPlanError(
            f"meta-skill {skill_name!r}: step {step_id!r} tool {tool!r} "
            f"not in tool_allowlist {items!r}",
        )
    return tuple(items)


def _ensure_on_failure_valid(name: str, steps: list[MetaStep]) -> None:
    """Cross-validate ``on_failure`` references after all steps are parsed.

    Five rules (minimum subset for Step A.3):

    1. The target step id must exist in the same plan.
    2. A step cannot name itself as its own substitute.
    3. A substitute step cannot itself have ``on_failure`` (no chains).
    4. Each substitute step may be designated by at most ONE primary
       (no shared substitutes) — otherwise concurrent failovers would
       overwrite the alias and silently strand one parent's output slot.
    5. A substitute step cannot declare ``depends_on`` — the scheduler
       force-clears its pending deps on failover, so honouring them would
       require a more elaborate semantic than the minimum subset offers.
    """

    by_id = {s.id: s for s in steps}
    designated_by: dict[str, str] = {}
    for s in steps:
        if not s.on_failure:
            continue
        if s.on_failure == s.id:
            raise MetaPlanError(
                f"meta-skill {name!r}: step {s.id!r} on_failure cannot "
                f"target itself",
            )
        if s.on_failure not in by_id:
            raise MetaPlanError(
                f"meta-skill {name!r}: step {s.id!r} on_failure target "
                f"{s.on_failure!r} is not a step in this plan",
            )
        substitute = by_id[s.on_failure]
        if substitute.on_failure:
            raise MetaPlanError(
                f"meta-skill {name!r}: step {s.id!r} on_failure target "
                f"{s.on_failure!r} may not have its own on_failure "
                f"(nested substitution is not supported)",
            )
        if substitute.depends_on:
            raise MetaPlanError(
                f"meta-skill {name!r}: step {s.id!r} on_failure target "
                f"{s.on_failure!r} must not declare depends_on "
                f"(substitute steps are dispatched on failover, not by "
                f"dependency resolution)",
            )
        prior = designated_by.get(s.on_failure)
        if prior is not None:
            raise MetaPlanError(
                f"meta-skill {name!r}: step {s.on_failure!r} is already "
                f"designated as on_failure substitute by step {prior!r}; "
                f"a substitute may only be referenced by one primary",
            )
        designated_by[s.on_failure] = s.id


def _ensure_acyclic(name: str, steps: list[MetaStep]) -> None:
    ids = {s.id for s in steps}
    graph: dict[str, list[str]] = {}
    for s in steps:
        for dep in s.depends_on:
            if dep not in ids:
                raise MetaPlanError(
                    f"meta-skill {name!r}: step {s.id!r} depends on undefined step {dep!r}",
                )
        graph[s.id] = list(s.depends_on)
    try:
        list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise MetaPlanError(
            f"meta-skill {name!r}: dependency cycle: {exc.args[1]}",
        ) from exc
