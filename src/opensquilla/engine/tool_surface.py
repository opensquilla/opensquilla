"""Request-scoped model-visible tool-surface selection.

The registry is deliberately small and provider-agnostic.  A contrib package
may register a deterministic selector for its durable agent id; prompt
assembly asks the registry once before rendering the tool-name block or
passing JSON schemas to the provider.  Selectors can only *remove* tools from
the already-authorized surface.  Returning ``None`` preserves the full
surface, which makes every selector fail open for unrecognised requests.

This is a context/latency optimization, not an authorization boundary.  Tool
policy remains owned by ``ToolContext`` and the dispatch policy chain.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class ToolSurfaceSelection:
    """A deterministic model-visible surface for one request.

    ``tool_names`` are intersected with the definitions that survived normal
    authorization.  ``skill_name`` optionally narrows the turn's visible skill
    catalog to one entry.  ``preload_skill`` moves that one selected skill into
    request-scoped context and removes the ``skill_view`` round trip.
    ``max_iterations`` is an optional request-specific upper bound on ordinary
    model/tool iterations; the agent's existing tool-free finalization pass is
    still available. ``repeat_call_threshold`` enables identical-call recovery
    for the selected tools. ``guidance`` is short, request-scoped routing
    context; it must never contain secrets or data values.
    """

    profile: str
    tool_names: tuple[str, ...]
    skill_name: str | None = None
    preload_skill: bool = False
    max_iterations: int | None = None
    repeat_call_threshold: int = 0
    guidance: str = ""


ToolSurfaceSelector = Callable[[str], ToolSurfaceSelection | None]

_SELECTORS: dict[str, ToolSurfaceSelector] = {}
_LOCK = RLock()


def register_tool_surface_selector(
    agent_id: str,
    selector: ToolSurfaceSelector,
) -> None:
    """Register or replace the selector for ``agent_id``.

    Registration is idempotent in the same way as tool registration: contrib
    imports may run more than once in tests or embedded gateways.
    """

    normalized = str(agent_id or "").strip()
    if not normalized:
        raise ValueError("agent_id must be non-empty")
    if not callable(selector):
        raise TypeError("selector must be callable")
    with _LOCK:
        _SELECTORS[normalized] = selector


def select_tool_surface(
    agent_id: str,
    query: str,
) -> ToolSurfaceSelection | None:
    """Return a registered request selection, or ``None`` for full surface."""

    with _LOCK:
        selector = _SELECTORS.get(str(agent_id or "").strip())
    if selector is None:
        return None
    return selector(query)


def filter_tool_definitions(
    tool_defs: Iterable[Any],
    selection: ToolSurfaceSelection | None,
) -> list[Any]:
    """Intersect ``selection`` with an already-authorized definition list.

    The original definition order is retained for stable provider cache
    prefixes.  A selected name that is absent from the authorized surface is
    ignored; selection can never add or resurrect a denied tool.
    """

    definitions = list(tool_defs)
    if selection is None:
        return definitions
    allowed = set(selection.tool_names)
    return [definition for definition in definitions if getattr(definition, "name", "") in allowed]


class _SkillCatalogView:
    """Fallback read view for catalog-like objects that are not dataclasses."""

    def __init__(self, source: Any, skills: tuple[Any, ...]) -> None:
        self._source = source
        self.skills = skills

    def load_all(self) -> list[Any]:
        return list(self.skills)

    def get_by_name(self, name: str) -> Any | None:
        return next((skill for skill in self.skills if skill.name == name), None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._source, name)


def filter_skill_catalog(
    catalog: Any | None,
    selection: ToolSurfaceSelection | None,
) -> Any | None:
    """Narrow a pinned catalog to the selection's zero-or-one visible skill."""

    if catalog is None or selection is None:
        return catalog
    skills = tuple(getattr(catalog, "skills", ()))
    selected = tuple(
        skill
        for skill in skills
        if selection.skill_name is not None and getattr(skill, "name", None) == selection.skill_name
    )
    try:
        return replace(catalog, skills=selected)
    except (TypeError, ValueError):
        return _SkillCatalogView(catalog, selected)


def empty_skill_catalog(catalog: Any | None) -> Any | None:
    """Return a catalog-shaped view with no skills.

    A deterministically preloaded skill must not also appear in the normal
    skill catalog, otherwise prompt injection asks the model to call
    ``skill_view`` for content it already has.
    """

    if catalog is None:
        return None
    try:
        return replace(catalog, skills=())
    except (TypeError, ValueError):
        return _SkillCatalogView(catalog, ())


def registered_tool_surface_agents() -> tuple[str, ...]:
    """Expose registry keys for diagnostics/tests without leaking callables."""

    with _LOCK:
        return tuple(sorted(_SELECTORS))


__all__ = [
    "ToolSurfaceSelection",
    "empty_skill_catalog",
    "filter_skill_catalog",
    "filter_tool_definitions",
    "register_tool_surface_selector",
    "registered_tool_surface_agents",
    "select_tool_surface",
]
