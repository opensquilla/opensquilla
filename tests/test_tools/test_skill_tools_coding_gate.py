"""skill_list / skill_view honor coding-mode gating (codex BLOCKER #2)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.tools.builtin import skill_tools


@pytest.fixture(autouse=True)
def _reset_module_state():
    saved_loader = skill_tools._loader
    saved_getter = skill_tools._skills_cfg_getter
    yield
    skill_tools._loader = saved_loader
    skill_tools._skills_cfg_getter = saved_getter


def _install(coding_mode: bool, disabled=None):
    skill_tools._skills_cfg_getter = lambda: SimpleNamespace(
        disabled=disabled or [], coding_mode=coding_mode
    )


def test_skill_available_off_gates_codetask():
    _install(coding_mode=False)
    assert skill_tools._skill_available("code-task") is False
    assert skill_tools._skill_available("git-diff") is True


def test_skill_available_on_allows_codetask():
    _install(coding_mode=True)
    assert skill_tools._skill_available("code-task") is True


def test_skill_available_no_getter_allows_all():
    skill_tools._skills_cfg_getter = None
    assert skill_tools._skill_available("code-task") is True


class _FakeLoader:
    def __init__(self, specs):
        self._specs = specs

    def load_all(self):
        return self._specs

    def get_by_name(self, name):
        for s in self._specs:
            if s.name == name:
                return s
        return None


def _spec(name):
    return SimpleNamespace(name=name, description=f"{name} desc", content=f"body of {name}")


def _skill_view_handler():
    from opensquilla.tools.registry import get_default_registry

    return get_default_registry().get("skill_view").handler


@pytest.mark.asyncio
async def test_skill_view_blocks_codetask_when_off():
    # skill_view must NOT return code-task content when coding mode is off,
    # even though it exists in the loader (the bypass codex flagged).
    skill_tools.create_skill_tools(
        _FakeLoader([_spec("code-task"), _spec("git-diff")]),
        skills_cfg_getter=lambda: SimpleNamespace(disabled=[], coding_mode=False),
    )
    view = _skill_view_handler()
    out = await view("code-task")
    assert "body of code-task" not in out
    assert "not found" in out.lower()
    # A normal skill still works.
    assert "body of git-diff" in await view("git-diff")


@pytest.mark.asyncio
async def test_skill_view_allows_codetask_when_on():
    skill_tools.create_skill_tools(
        _FakeLoader([_spec("code-task")]),
        skills_cfg_getter=lambda: SimpleNamespace(disabled=[], coding_mode=True),
    )
    out = await _skill_view_handler()("code-task")
    assert "body of code-task" in out
