"""DSL extension tests: entrypoint.stdin and entrypoint.assemble."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from opensquilla.engine.types import AgentEvent
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch, MetaResult
from opensquilla.skills.types import SkillLayer, SkillSpec


def _meta_spec(steps: list[dict[str, object]]) -> SkillSpec:
    return SkillSpec(
        name="meta-test",
        description="t",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=["t"],
        content="fallback",
        kind="meta",
        composition_raw={"steps": steps},
    )


class _Loader:
    def __init__(self, specs: list[SkillSpec]) -> None:
        self._by_name = {s.name: s for s in specs}

    def get_by_name(self, name: str) -> SkillSpec | None:
        return self._by_name.get(name)


@pytest.mark.asyncio
async def test_skill_exec_pipes_rendered_stdin_to_subprocess(tmp_path: Path) -> None:
    """entrypoint.stdin is rendered through Jinja then piped to stdin."""

    script = tmp_path / "passthrough.py"
    script.write_text(
        "import sys\n"
        "data = sys.stdin.read()\n"
        "print('GOT:' + data)\n",
    )
    skill = SkillSpec(
        name="stdin-skill",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="x",
        kind="skill",
        base_dir=str(tmp_path),
        entrypoint={
            "command": "python {baseDir}/passthrough.py",
            "args": [],
            "stdin": "hello {{ inputs.user_message }}",
            "parse": "text",
        },
    )
    plan_spec = _meta_spec(
        [{"id": "p", "kind": "skill_exec", "skill": "stdin-skill"}],
    )
    plan = parse_meta_plan(plan_spec)
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=_Loader([skill]))
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={"user_message": "world"})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None and final.ok, final.error if final else "no result"
    assert final.step_outputs["p"] == "GOT:hello world"


@pytest.mark.asyncio
async def test_skill_exec_assemble_writes_template_files_before_exec(
    tmp_path: Path,
) -> None:
    """entrypoint.assemble pre-renders files before the subprocess starts."""

    script = tmp_path / "read_template.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "print(Path(sys.argv[1]).read_text(), end='')\n",
    )
    target = tmp_path / "assembled.txt"
    skill = SkillSpec(
        name="assemble-skill",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="x",
        kind="skill",
        base_dir=str(tmp_path),
        entrypoint={
            "command": "python {baseDir}/read_template.py",
            "args": [str(target)],
            "assemble": [
                {
                    "into": str(target),
                    "from_template": "value={{ inputs.value }}\n",
                },
            ],
            "parse": "text",
        },
    )
    plan = parse_meta_plan(
        _meta_spec([{"id": "a", "kind": "skill_exec", "skill": "assemble-skill"}]),
    )
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=_Loader([skill]))
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={"value": "42"})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None and final.ok, final.error if final else "no result"
    assert final.step_outputs["a"].strip() == "value=42"
    # The assembled file should have survived on disk.
    assert target.read_text().strip() == "value=42"


@pytest.mark.asyncio
async def test_skill_exec_stdin_non_string_raises_gracefully(tmp_path: Path) -> None:
    """entrypoint.stdin of a non-string type makes the step fail cleanly."""
    skill = SkillSpec(
        name="bad-stdin-skill",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="x",
        kind="skill",
        base_dir=str(tmp_path),
        entrypoint={
            "command": "python -c 'pass'",
            "args": [],
            "stdin": 42,  # integer — invalid
            "parse": "text",
        },
    )
    plan_spec = _meta_spec([{"id": "q", "kind": "skill_exec", "skill": "bad-stdin-skill"}])
    plan = parse_meta_plan(plan_spec)
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=_Loader([skill]))
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None and final.ok is False
    assert "string template" in (final.error or "")


@pytest.mark.asyncio
async def test_assemble_path_traversal_rejected(tmp_path: Path) -> None:
    """assemble.into must not escape workspace_dir via path traversal."""

    workspace = tmp_path / "ws"
    workspace.mkdir()
    escape_target = tmp_path / "outside.txt"

    script = workspace / "noop.py"
    script.write_text("pass\n")

    skill = SkillSpec(
        name="evil-skill",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="x",
        kind="skill",
        base_dir=str(workspace),
        entrypoint={
            "command": "python {baseDir}/noop.py",
            "args": [],
            "assemble": [
                {
                    "into": str(escape_target),  # absolute, outside workspace
                    "from_template": "PWND\n",
                },
            ],
            "parse": "text",
        },
    )
    plan = parse_meta_plan(
        _meta_spec([{"id": "x", "kind": "skill_exec", "skill": "evil-skill"}]),
    )
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_Loader([skill]),
        workspace_dir=str(workspace),
    )
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None and final.ok is False
    assert "escapes allowed root" in (final.error or "")
    assert not escape_target.exists(), "file outside workspace must NOT be written"


@pytest.mark.asyncio
async def test_assemble_relative_path_inside_workspace_allowed(tmp_path: Path) -> None:
    """Normal relative paths under workspace_dir still work."""

    workspace = tmp_path / "ws"
    workspace.mkdir()

    script = workspace / "echo.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\nprint(Path(sys.argv[1]).read_text(), end='')\n",
    )

    skill = SkillSpec(
        name="ok-skill",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="x",
        kind="skill",
        base_dir=str(workspace),
        entrypoint={
            "command": "python {baseDir}/echo.py",
            "args": ["paper/out.txt"],
            "assemble": [
                {
                    "into": "paper/out.txt",  # relative — anchors to workspace
                    "from_template": "ok={{ inputs.value }}\n",
                },
            ],
            "parse": "text",
        },
    )
    plan = parse_meta_plan(
        _meta_spec([{"id": "y", "kind": "skill_exec", "skill": "ok-skill"}]),
    )
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_Loader([skill]),
        workspace_dir=str(workspace),
    )
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={"value": "42"})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None and final.ok, final.error
    assert (workspace / "paper" / "out.txt").read_text().strip() == "ok=42"
