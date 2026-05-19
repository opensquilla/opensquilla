"""Tests for meta_invoke tool registration and Agent dispatch interception.

This file accumulates tests across Tasks 1, 3, 5, 6 of the
meta_invoke-soft-activation plan. Task 1 covers registration only.
"""

from __future__ import annotations

import pytest


def test_meta_invoke_registered_in_default_registry() -> None:
    """meta_invoke appears in the registry after importing the builtin
    module."""
    # Importing the builtin package triggers all registrations.
    from opensquilla.tools.builtin import meta_tools  # noqa: F401 — import side-effect
    from opensquilla.tools.registry import get_default_registry

    assert get_default_registry().get("meta_invoke") is not None


def test_meta_invoke_spec_shape() -> None:
    """meta_invoke advertises a single required string parameter 'name',
    and the description mentions meta-skill semantics."""
    from opensquilla.tools.builtin import meta_tools  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registered = get_default_registry().get("meta_invoke")
    assert registered is not None
    spec = registered.spec
    assert spec.name == "meta_invoke"
    assert "name" in spec.parameters
    assert spec.required == ["name"]
    # Description must mention meta-skill semantics for the LLM
    desc = spec.description.lower()
    assert "meta-skill" in desc
    assert "playbook" in desc or "multi-step" in desc


def test_meta_invoke_not_exposed_by_default() -> None:
    """meta_invoke must not appear in default tool catalogues. It is
    conditionally surfaced by SkillInjector when meta-skills are present."""
    from opensquilla.tools.builtin import meta_tools  # noqa: F401
    from opensquilla.tools.registry import get_default_registry

    registered = get_default_registry().get("meta_invoke")
    assert registered is not None  # exists in registry
    assert registered.spec.exposed_by_default is False, (
        "meta_invoke should be conditionally surfaced, not always exposed"
    )


@pytest.mark.asyncio
async def test_meta_invoke_handler_raises_routing_error() -> None:
    """If the standard dispatcher ever invokes the meta_invoke handler,
    that's a configuration bug — the Agent's dispatch loop should have
    intercepted it. Raise a clear RuntimeError naming the expected
    interception point."""
    from opensquilla.tools.builtin.meta_tools import meta_invoke

    with pytest.raises(RuntimeError) as exc_info:
        await meta_invoke(name="any")
    msg = str(exc_info.value).lower()
    assert "agent" in msg or "_run_one_streaming" in msg or "intercept" in msg
