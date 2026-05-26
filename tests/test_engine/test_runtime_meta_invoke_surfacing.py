"""TurnRunner._build_tools surfaces meta_invoke when meta-skills are loaded.

meta_invoke is registered with ``exposed_by_default=False`` so the tool
catalogue stays clean in deployments that don't ship meta-skills. When
at least one ``kind=meta`` skill IS loaded, ``_build_tools`` must add
``"meta_invoke"`` to ``ctx.surfaced_tools`` so the registry's visibility
check at :func:`ToolRegistry._is_visible` lets it through.
"""

from __future__ import annotations

from pathlib import Path

import inspect

from opensquilla.engine.runtime import TurnRunner
from opensquilla.skills.loader import SkillLoader
from opensquilla.tools.registry import get_default_registry
from opensquilla.tools.types import ToolContext


def _make_loader_with_meta(
    tmp_path: Path,
    *,
    disable_model_invocation: bool = False,
) -> SkillLoader:
    bundled = tmp_path / "skills" / "bundled"
    bundled.mkdir(parents=True)
    skill_dir = bundled / "meta-tiny"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        '---\n'
        'name: meta-tiny\n'
        'kind: meta\n'
        'description: tiny meta-skill\n'
        f'disable-model-invocation: {str(disable_model_invocation).lower()}\n'
        'triggers: [tiny-meta-trigger]\n'
        'composition:\n'
        '  steps:\n'
        '    - id: c\n'
        '      kind: llm_classify\n'
        '      output_choices: [A, B]\n'
        '      with: {text: "x"}\n'
        '---\n'
        '# meta-tiny\n',
        encoding="utf-8",
    )
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    loader.load_all()
    return loader


def _make_loader_without_meta(tmp_path: Path) -> SkillLoader:
    bundled = tmp_path / "skills" / "bundled"
    bundled.mkdir(parents=True)
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    loader.load_all()
    return loader


def test_build_tools_surfaces_meta_invoke_when_meta_skill_present(
    tmp_path: Path,
) -> None:
    registry = get_default_registry()
    loader = _make_loader_with_meta(tmp_path)
    runner = TurnRunner(provider_selector=None, config=None)
    runner._tool_registry = registry
    runner._skill_loader = loader

    ctx = ToolContext(is_owner=True, workspace_dir=str(tmp_path))
    tool_defs, _handler = runner._build_tools(ctx)
    names = {getattr(td, "name", "") for td in tool_defs}

    assert "meta_invoke" in names, (
        f"meta_invoke should be surfaced when meta-skills present; got {sorted(names)[:20]}"
    )
    assert ctx.surfaced_tools is not None
    assert "meta_invoke" in ctx.surfaced_tools


def test_build_tools_does_not_surface_meta_invoke_without_meta_skills(
    tmp_path: Path,
) -> None:
    """When no meta-skills are loaded, meta_invoke stays hidden — its
    ``exposed_by_default=False`` keeps the catalogue tight for deployments
    that don't ship meta-skills."""
    registry = get_default_registry()
    loader = _make_loader_without_meta(tmp_path)
    runner = TurnRunner(provider_selector=None, config=None)
    runner._tool_registry = registry
    runner._skill_loader = loader

    ctx = ToolContext(is_owner=True, workspace_dir=str(tmp_path))
    tool_defs, _handler = runner._build_tools(ctx)
    names = {getattr(td, "name", "") for td in tool_defs}

    assert "meta_invoke" not in names, (
        f"meta_invoke should be hidden when no meta-skills present; got {sorted(names)[:20]}"
    )
    # surfaced_tools may stay None (no mutation) — either way meta_invoke
    # must not be inside it
    assert ctx.surfaced_tools is None or "meta_invoke" not in ctx.surfaced_tools


def test_build_tools_does_not_surface_meta_invoke_for_disabled_meta_skill(
    tmp_path: Path,
) -> None:
    registry = get_default_registry()
    loader = _make_loader_with_meta(tmp_path, disable_model_invocation=True)
    runner = TurnRunner(provider_selector=None, config=None)
    runner._tool_registry = registry
    runner._skill_loader = loader

    ctx = ToolContext(is_owner=True, workspace_dir=str(tmp_path))
    tool_defs, _handler = runner._build_tools(ctx)
    names = {getattr(td, "name", "") for td in tool_defs}

    assert "meta_invoke" not in names
    assert ctx.surfaced_tools is None or "meta_invoke" not in ctx.surfaced_tools


def test_build_tools_preserves_existing_surfaced_tools(tmp_path: Path) -> None:
    """If the caller pre-populates ctx.surfaced_tools (e.g. for a custom
    per-request tool surface), _build_tools must add to it, not overwrite."""
    registry = get_default_registry()
    loader = _make_loader_with_meta(tmp_path)
    runner = TurnRunner(provider_selector=None, config=None)
    runner._tool_registry = registry
    runner._skill_loader = loader

    ctx = ToolContext(
        is_owner=True,
        workspace_dir=str(tmp_path),
        surfaced_tools={"some_other_tool"},
    )
    runner._build_tools(ctx)
    assert ctx.surfaced_tools is not None
    assert "meta_invoke" in ctx.surfaced_tools
    assert "some_other_tool" in ctx.surfaced_tools, (
        "must extend existing surfaced_tools, not replace it"
    )


def test_runtime_does_not_hard_auto_invoke_meta_match() -> None:
    """Meta trigger matches must go through the outer LLM prompt/tool path.

    The meta_resolution step already injects a system-prompt hint and exposes
    meta_invoke. Runtime must not bypass that prompt by directly calling
    _run_one_streaming when metadata["meta_match"] is present.
    """
    source = inspect.getsource(TurnRunner._run_turn)

    assert "meta_resolution.auto_invoke" not in source
    assert "auto_meta_invoke_" not in source
