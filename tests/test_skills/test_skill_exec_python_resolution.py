"""skill_exec resolves bare ``python``/``python3`` to ``sys.executable``.

Without this, a wrapped-CLI skill whose ``entrypoint.command`` starts
with bare ``python`` (a common pattern in the bundled meta-skills) would
fail to spawn in any environment where ``python`` is not on PATH — e.g.
uv-managed venvs (which symlink only ``.venv/bin/python``) when the
gateway process runs without ``.venv/bin`` prepended.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opensquilla.skills.meta.executors import skill_exec
from opensquilla.skills.meta.executors.skill_exec import run_skill_exec_step
from opensquilla.skills.meta.types import MetaStep
from opensquilla.skills.types import SkillLayer, SkillSpec


def _spec(base_dir: Path, command: str) -> SkillSpec:
    return SkillSpec(
        name="bare-python-skill",
        description="test",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="",
        base_dir=str(base_dir),
        entrypoint={"command": command, "parse": "text", "timeout": 10.0},
    )


def test_split_entrypoint_command_preserves_windows_backslashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(skill_exec.os, "name", "nt")

    assert skill_exec._split_entrypoint_command(
        r'python "C:\Users\runner admin\AppData\Local\Temp\hello.py"',
    ) == ["python", r"C:\Users\runner admin\AppData\Local\Temp\hello.py"]


class _Loader:
    def __init__(self, spec: SkillSpec) -> None:
        self._spec = spec

    def get_by_name(self, name: str) -> SkillSpec | None:
        return self._spec if name == self._spec.name else None


@pytest.mark.asyncio
async def test_skill_exec_resolves_bare_python_to_sys_executable(
    tmp_path: Path,
) -> None:
    """``command: python -c '...'`` must succeed even when the gateway
    process has no plain ``python`` on PATH — skill_exec auto-resolves it
    to the current ``sys.executable``."""
    script = tmp_path / "hello.py"
    script.write_text("print('hi from skill_exec')\n", encoding="utf-8")
    spec = _spec(tmp_path, f"python {script}")
    step = MetaStep(
        id="s1",
        kind="skill_exec",
        skill="bare-python-skill",
    )
    out = await run_skill_exec_step(
        step,
        effective_skill="bare-python-skill",
        inputs={},
        outputs={},
        skill_loader=_Loader(spec),
        workspace_dir=str(tmp_path),
    )
    assert "hi from skill_exec" in out


@pytest.mark.asyncio
async def test_skill_exec_resolves_bare_python3_too(tmp_path: Path) -> None:
    """``python3`` gets the same treatment as ``python``."""
    script = tmp_path / "hi3.py"
    script.write_text("print('hi3')\n", encoding="utf-8")
    spec = _spec(tmp_path, f"python3 {script}")
    step = MetaStep(id="s2", kind="skill_exec", skill="bare-python-skill")
    out = await run_skill_exec_step(
        step,
        effective_skill="bare-python-skill",
        inputs={},
        outputs={},
        skill_loader=_Loader(spec),
        workspace_dir=str(tmp_path),
    )
    assert "hi3" in out


@pytest.mark.asyncio
async def test_skill_exec_does_not_rewrite_absolute_interpreter(
    tmp_path: Path,
) -> None:
    """If the author pinned an absolute interpreter path, leave it alone
    — author intent wins over auto-resolution."""
    script = tmp_path / "hi.py"
    script.write_text("print('via-absolute')\n", encoding="utf-8")
    # sys.executable is itself an absolute path; the rewrite logic must
    # only fire on bare names, not on already-absolute interpreters.
    spec = _spec(tmp_path, f"{sys.executable} {script}")
    step = MetaStep(id="s3", kind="skill_exec", skill="bare-python-skill")
    out = await run_skill_exec_step(
        step,
        effective_skill="bare-python-skill",
        inputs={},
        outputs={},
        skill_loader=_Loader(spec),
        workspace_dir=str(tmp_path),
    )
    assert "via-absolute" in out
