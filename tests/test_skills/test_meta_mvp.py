"""End-to-end MVP coverage for the Meta-Skill subsystem."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.steps.meta_resolution import meta_resolution
from opensquilla.engine.types import (
    AgentEvent,
    DoneEvent,
    TextDeltaEvent,
)
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.orchestrator import (
    MetaOrchestrator,
    format_step_prompt,
    render_with_args,
    resolve_route,
)
from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch, RouteCase
from opensquilla.skills.types import SkillLayer, SkillSpec

# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def _make_meta_spec(
    *,
    name: str = "meta-x",
    triggers: list[str] | None = None,
    composition: dict[str, Any] | None = None,
    kind: str = "meta",
    priority: int = 0,
    content: str = "fallback body text",
    final_text_mode: str = "raw",
) -> SkillSpec:
    # Default to "raw" in the test fixture so legacy unit tests that
    # count llm_chat calls don't get an extra invocation from the auto
    # final-text summariser. Tests that exercise the auto path opt in
    # explicitly with ``final_text_mode="auto"``.
    return SkillSpec(
        name=name,
        description="test meta skill",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=triggers or ["test trigger"],
        content=content,
        kind=kind,
        meta_priority=priority,
        composition_raw=composition,
        final_text_mode=final_text_mode,
    )


def test_parser_returns_none_for_regular_skill() -> None:
    spec = _make_meta_spec(kind="skill", composition=None)
    assert parse_meta_plan(spec) is None


def test_parser_happy_path() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "summarize", "with": {"text": "x"}},
                {"id": "b", "skill": "docx", "depends_on": ["a"], "with": {}},
            ],
        },
        triggers=["x report"],
        priority=42,
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.name == "meta-x"
    assert plan.priority == 42
    assert [s.id for s in plan.steps] == ["a", "b"]
    assert plan.steps[1].depends_on == ("a",)


def test_parser_rejects_cycle() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "x", "depends_on": ["b"]},
                {"id": "b", "skill": "y", "depends_on": ["a"]},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="cycle"):
        parse_meta_plan(spec)


def test_parser_rejects_duplicate_id() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "x"},
                {"id": "a", "skill": "y"},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="duplicate"):
        parse_meta_plan(spec)


def test_parser_rejects_undefined_depends_on() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "x", "depends_on": ["nonexistent"]},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="undefined step"):
        parse_meta_plan(spec)


# ---------------------------------------------------------------------------
# Template renderer
# ---------------------------------------------------------------------------


def test_render_with_args_xml_escape_and_truncate() -> None:
    rendered = render_with_args(
        {"q": "{{ inputs.topic | xml_escape | truncate(15) }}"},
        inputs={"topic": "Hello <world> & you"},
        outputs={},
    )
    assert rendered["q"] == "Hello &lt;world"


def test_render_with_args_unknown_variable_raises() -> None:
    with pytest.raises(ValueError, match="undefined template variable"):
        render_with_args(
            {"q": "{{ outputs.missing }}"},
            inputs={},
            outputs={},
        )


def test_format_step_prompt_includes_all_args() -> None:
    out = format_step_prompt("summarize", {"text": "hello", "max_words": 100})
    assert "summarize" in out
    assert "text: hello" in out
    assert "max_words: 100" in out


# ---------------------------------------------------------------------------
# Resolver (engine.steps.meta_resolution)
# ---------------------------------------------------------------------------


class _FakeLoader:
    def __init__(self, specs: list[SkillSpec]) -> None:
        self._specs = specs

    def load_all(self) -> list[SkillSpec]:
        return list(self._specs)

    def get_by_name(self, name: str) -> SkillSpec | None:
        for s in self._specs:
            if s.name == name:
                return s
        return None


@pytest.mark.asyncio
async def test_meta_resolution_matches_trigger() -> None:
    spec = _make_meta_spec(
        composition={"steps": [{"id": "a", "skill": "summarize"}]},
        triggers=["pdf briefing"],
        priority=10,
    )
    loader = _FakeLoader([spec])
    ctx = SimpleNamespace(
        message="please make me a PDF briefing on rust",
        semantic_message="please make me a PDF briefing on rust",
        metadata={"skill_loader": loader},
    )
    out = await meta_resolution(ctx)  # type: ignore[arg-type]
    match = out.metadata["meta_match"]
    assert match.plan.name == "meta-x"
    assert match.inputs["user_message"] == "please make me a PDF briefing on rust"


@pytest.mark.asyncio
async def test_meta_resolution_highest_priority_wins() -> None:
    lo = _make_meta_spec(
        name="meta-lo",
        composition={"steps": [{"id": "a", "skill": "summarize"}]},
        triggers=["report"],
        priority=10,
    )
    hi = _make_meta_spec(
        name="meta-hi",
        composition={"steps": [{"id": "a", "skill": "summarize"}]},
        triggers=["report"],
        priority=99,
    )
    loader = _FakeLoader([lo, hi])
    ctx = SimpleNamespace(
        message="produce a report",
        semantic_message="produce a report",
        metadata={"skill_loader": loader},
    )
    out = await meta_resolution(ctx)  # type: ignore[arg-type]
    assert out.metadata["meta_match"].plan.name == "meta-hi"


@pytest.mark.asyncio
async def test_meta_resolution_no_match_keeps_metadata_clean() -> None:
    spec = _make_meta_spec(
        composition={"steps": [{"id": "a", "skill": "summarize"}]},
        triggers=["nope"],
    )
    loader = _FakeLoader([spec])
    ctx = SimpleNamespace(
        message="hello world",
        semantic_message="hello world",
        metadata={"skill_loader": loader},
    )
    out = await meta_resolution(ctx)  # type: ignore[arg-type]
    assert "meta_match" not in out.metadata


# ---------------------------------------------------------------------------
# Orchestrator with stub Agent runner
# ---------------------------------------------------------------------------


def _make_skill_spec(name: str, content: str = "") -> SkillSpec:
    return SkillSpec(
        name=name,
        description=f"{name} description",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content=content,
        kind="skill",
    )


@pytest.mark.asyncio
async def test_orchestrator_runs_steps_in_topological_order() -> None:
    # Plan: a -> b -> c, sub-Agent echoes the system prompt back as final text
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "skill_a", "with": {"in": "alpha"}},
                {
                    "id": "b",
                    "skill": "skill_b",
                    "depends_on": ["a"],
                    "with": {"upstream": "{{ outputs.a }}"},
                },
                {
                    "id": "c",
                    "skill": "skill_c",
                    "depends_on": ["b"],
                    "with": {"upstream": "{{ outputs.b }}"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader(
        [
            _make_skill_spec("skill_a", content="A-skill"),
            _make_skill_spec("skill_b", content="B-skill"),
            _make_skill_spec("skill_c", content="C-skill"),
        ],
    )

    call_log: list[tuple[str, str]] = []

    async def stub_runner(system_prompt: str, user_message: str) -> AsyncIterator[AgentEvent]:
        call_log.append((system_prompt, user_message))
        # Each step returns a deterministic payload that the next can quote.
        if "A-skill" in system_prompt:
            yield TextDeltaEvent(text="OUT_A")
        elif "B-skill" in system_prompt:
            yield TextDeltaEvent(text="OUT_B(" + user_message.count("OUT_A").__str__() + ")")
        elif "C-skill" in system_prompt:
            yield TextDeltaEvent(text="OUT_C[" + user_message.count("OUT_B").__str__() + "]")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=stub_runner, skill_loader=loader)
    match = MetaMatch(plan=plan, inputs={"user_message": "trigger"})
    result = await orch.run(match)

    assert result.ok, result.error
    assert result.final_text == "OUT_C[1]"
    assert result.step_outputs == {
        "a": "OUT_A",
        "b": "OUT_B(1)",
        "c": "OUT_C[1]",
    }
    # 3 sub-Agent invocations, in dependency order
    assert len(call_log) == 3
    assert "A-skill" in call_log[0][0]
    assert "B-skill" in call_log[1][0]
    assert "C-skill" in call_log[2][0]


@pytest.mark.asyncio
async def test_orchestrator_returns_failure_when_step_skill_missing() -> None:
    spec = _make_meta_spec(
        composition={"steps": [{"id": "a", "skill": "nonexistent_skill"}]},
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader([])  # No skills registered

    async def stub_runner(_sys: str, _user: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="never")

    orch = MetaOrchestrator(agent_runner=stub_runner, skill_loader=loader)
    match = MetaMatch(plan=plan, inputs={"user_message": "x"})
    result = await orch.run(match)

    assert not result.ok
    assert result.failed_step_id == "a"
    assert "not found" in (result.error or "")


@pytest.mark.asyncio
async def test_orchestrator_refuses_meta_inside_meta() -> None:
    spec = _make_meta_spec(
        composition={"steps": [{"id": "a", "skill": "inner-meta"}]},
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    inner_meta = _make_meta_spec(
        name="inner-meta",
        composition={"steps": [{"id": "z", "skill": "summarize"}]},
    )
    loader = _FakeLoader([inner_meta])

    async def stub_runner(_sys: str, _user: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="never")

    orch = MetaOrchestrator(agent_runner=stub_runner, skill_loader=loader)
    match = MetaMatch(plan=plan, inputs={"user_message": "x"})
    result = await orch.run(match)

    assert not result.ok
    assert "cannot compose another meta-skill" in (result.error or "")


# ---------------------------------------------------------------------------
# Loader integration — make sure the bundled sample is picked up
# ---------------------------------------------------------------------------


def test_bundled_sample_loads(tmp_path: Path) -> None:
    bundled = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "bundled"
    snapshot = tmp_path / "snap.json"
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=snapshot)
    loader.invalidate_cache()
    specs = {s.name: s for s in loader.load_all()}
    meta = specs.get("meta-web-to-pdf-briefing")
    assert meta is not None
    assert meta.kind == "meta"
    plan = parse_meta_plan(meta)
    assert plan is not None
    assert [s.id for s in plan.steps] == ["search", "digest", "render"]


# ---------------------------------------------------------------------------
# Routing primitive
# ---------------------------------------------------------------------------


def test_parser_accepts_route() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "classify", "skill": "coding-agent"},
                {
                    "id": "ingest",
                    "skill": "deep-research",
                    "depends_on": ["classify"],
                    "route": [
                        {"when": "'URL' in outputs.classify", "to": "multi-search-engine"},
                        {"when": "'PDF' in outputs.classify", "to": "pdf-toolkit"},
                    ],
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    ingest = plan.steps[1]
    assert len(ingest.route) == 2
    assert ingest.route[0].to == "multi-search-engine"
    assert ingest.route[1].when.startswith("'PDF'")


def test_parser_rejects_malformed_route() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "x", "route": [{"when": "x"}]},  # missing 'to'
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="missing non-empty 'to'"):
        parse_meta_plan(spec)


def test_parser_rejects_route_not_a_list() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "x", "route": "not-a-list"},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="route must be a list"):
        parse_meta_plan(spec)


def test_resolve_route_first_match_wins() -> None:
    cases = (
        RouteCase(when="'PDF' in outputs.classify", to="pdf-toolkit"),
        RouteCase(when="'URL' in outputs.classify", to="multi-search-engine"),
    )
    routed = resolve_route(cases, inputs={}, outputs={"classify": "PDF"})
    assert routed == "pdf-toolkit"


def test_resolve_route_no_match_returns_none() -> None:
    cases = (
        RouteCase(when="'PDF' in outputs.classify", to="pdf-toolkit"),
    )
    routed = resolve_route(cases, inputs={}, outputs={"classify": "TEXT"})
    assert routed is None


def test_resolve_route_empty_returns_none() -> None:
    assert resolve_route((), inputs={}, outputs={}) is None


def test_resolve_route_undefined_var_raises_value_error() -> None:
    cases = (RouteCase(when="outputs.does_not_exist == 'x'", to="anything"),)
    with pytest.raises(ValueError, match="undefined variable"):
        resolve_route(cases, inputs={}, outputs={})


@pytest.mark.asyncio
async def test_orchestrator_route_overrides_skill() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "classify", "skill": "tagger", "with": {}},
                {
                    "id": "ingest",
                    "skill": "default-ingest",
                    "depends_on": ["classify"],
                    "route": [
                        {"when": "'URL' in outputs.classify", "to": "url-ingest"},
                        {"when": "'PDF' in outputs.classify", "to": "pdf-ingest"},
                    ],
                    "with": {},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader(
        [
            _make_skill_spec("tagger", content="TAGGER"),
            _make_skill_spec("default-ingest", content="DEFAULT-INGEST"),
            _make_skill_spec("url-ingest", content="URL-INGEST"),
            _make_skill_spec("pdf-ingest", content="PDF-INGEST"),
        ],
    )

    call_log: list[str] = []

    async def stub_runner(system_prompt: str, _user: str) -> AsyncIterator[AgentEvent]:
        call_log.append(system_prompt)
        if "TAGGER" in system_prompt:
            yield TextDeltaEvent(text="URL")
        elif "URL-INGEST" in system_prompt:
            yield TextDeltaEvent(text="url-ingested")
        else:
            yield TextDeltaEvent(text="other")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=stub_runner, skill_loader=loader)
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "go"}))

    assert result.ok, result.error
    assert result.step_outputs["classify"] == "URL"
    assert result.step_outputs["ingest"] == "url-ingested"
    # second invocation must be the routed-to skill, NOT default-ingest
    assert "URL-INGEST" in call_log[1]
    assert "DEFAULT-INGEST" not in call_log[1]


@pytest.mark.asyncio
async def test_orchestrator_route_fallthrough_uses_default_skill() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "classify", "skill": "tagger", "with": {}},
                {
                    "id": "ingest",
                    "skill": "default-ingest",
                    "depends_on": ["classify"],
                    "route": [
                        {"when": "'URL' in outputs.classify", "to": "url-ingest"},
                    ],
                    "with": {},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader(
        [
            _make_skill_spec("tagger", content="TAGGER"),
            _make_skill_spec("default-ingest", content="DEFAULT-INGEST"),
            _make_skill_spec("url-ingest", content="URL-INGEST"),
        ],
    )

    call_log: list[str] = []

    async def stub_runner(system_prompt: str, _user: str) -> AsyncIterator[AgentEvent]:
        call_log.append(system_prompt)
        if "TAGGER" in system_prompt:
            yield TextDeltaEvent(text="TEXT")  # no route case matches
        elif "DEFAULT-INGEST" in system_prompt:
            yield TextDeltaEvent(text="default-ingested")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=stub_runner, skill_loader=loader)
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "go"}))

    assert result.ok, result.error
    assert result.step_outputs["ingest"] == "default-ingested"
    assert "DEFAULT-INGEST" in call_log[1]


# ---------------------------------------------------------------------------
# Step kind dispatch (llm_classify / tool_call)
# ---------------------------------------------------------------------------


def test_parser_llm_classify_requires_choices() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "classify", "kind": "llm_classify", "with": {"text": "x"}},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="output_choices"):
        parse_meta_plan(spec)


def test_parser_llm_classify_accepts_with_choices() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "classify",
                    "kind": "llm_classify",
                    "output_choices": ["A", "B"],
                    "with": {"text": "x"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.steps[0].kind == "llm_classify"
    assert plan.steps[0].output_choices == ("A", "B")
    # skill defaults to step id when not specified for non-agent kinds
    assert plan.steps[0].skill == "classify"


def test_parser_llm_classify_rejects_duplicate_choices() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "c",
                    "kind": "llm_classify",
                    "output_choices": ["A", "A"],
                    "with": {"text": "x"},
                },
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="unique"):
        parse_meta_plan(spec)


def test_parser_tool_call_requires_tool_name() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "save", "kind": "tool_call", "tool_args": {"k": "v"}},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="tool"):
        parse_meta_plan(spec)


def test_parser_tool_call_accepts_full_spec() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "save",
                    "kind": "tool_call",
                    "tool": "memory_save",
                    "tool_args": {"content": "{{ inputs.user_message }}"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.steps[0].kind == "tool_call"
    assert plan.steps[0].tool == "memory_save"
    assert plan.steps[0].tool_args == {"content": "{{ inputs.user_message }}"}


def test_parser_tool_allowlist_must_contain_tool() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "save",
                    "kind": "tool_call",
                    "tool": "exec_command",
                    "tool_allowlist": ["memory_save", "memory_search"],
                    "tool_args": {"command": "rm -rf /"},
                },
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="not in tool_allowlist"):
        parse_meta_plan(spec)


def test_parser_tool_allowlist_accepts_matching_tool() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "save",
                    "kind": "tool_call",
                    "tool": "memory_save",
                    "tool_allowlist": ["memory_save"],
                    "tool_args": {"content": "x"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.steps[0].tool_allowlist == ("memory_save",)


def test_parser_tool_allowlist_only_valid_for_tool_call() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "a",
                    "skill": "summarize",
                    "tool_allowlist": ["foo"],
                    "with": {},
                },
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="tool_allowlist.*only valid"):
        parse_meta_plan(spec)


def test_parser_rejects_choices_on_non_classify_kind() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "a",
                    "skill": "summarize",
                    "output_choices": ["X"],
                    "with": {},
                },
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="only valid for kind=llm_classify"):
        parse_meta_plan(spec)


def test_parser_rejects_tool_on_non_tool_call_kind() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "a",
                    "skill": "summarize",
                    "tool": "memory_save",
                    "with": {},
                },
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="only valid for kind=tool_call"):
        parse_meta_plan(spec)


def test_parser_skill_exec_requires_skill() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "ingest", "kind": "skill_exec", "with": {}},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="missing skill"):
        parse_meta_plan(spec)


def test_parser_skill_exec_accepts_full_spec() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "ingest",
                    "kind": "skill_exec",
                    "skill": "multi-search-engine",
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.steps[0].kind == "skill_exec"
    assert plan.steps[0].skill == "multi-search-engine"


@pytest.mark.asyncio
async def test_orchestrator_skill_exec_invokes_subprocess(tmp_path: Path) -> None:
    """skill_exec must run the entrypoint as a real subprocess, no LLM."""

    # Synthesize a fake skill with a real entrypoint script that echoes its args.
    skill_dir = tmp_path / "fake_skill"
    skill_dir.mkdir()
    script = skill_dir / "echo.py"
    script.write_text(
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "print(json.dumps({'argv': args, 'ok': True}))\n",
    )

    fake_spec = _make_skill_spec("fake-echo", content="echo me")
    fake_spec.base_dir = str(skill_dir)
    fake_spec.entrypoint = {
        "command": "python {baseDir}/echo.py",
        "args": ["--query", "{{ inputs.user_message }}", "--n", "{{ with.n }}"],
        "parse": "json",
        "timeout": 15,
    }

    plan_spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "run",
                    "kind": "skill_exec",
                    "skill": "fake-echo",
                    "with": {"n": "3"},
                },
            ],
        },
    )
    plan = parse_meta_plan(plan_spec)
    assert plan is not None

    async def explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("skill_exec must not spawn a sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=explode_runner,
        skill_loader=_FakeLoader([fake_spec]),
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "hello"}))

    assert result.ok, result.error
    import json as _json

    parsed = _json.loads(result.step_outputs["run"])
    assert parsed["ok"] is True
    assert parsed["argv"] == ["--query", "hello", "--n", "3"]


@pytest.mark.asyncio
async def test_orchestrator_skill_exec_propagates_nonzero_exit(tmp_path: Path) -> None:
    skill_dir = tmp_path / "fail_skill"
    skill_dir.mkdir()
    script = skill_dir / "fail.py"
    script.write_text("import sys; sys.stderr.write('boom\\n'); sys.exit(7)\n")

    fake_spec = _make_skill_spec("fail-skill", content="x")
    fake_spec.base_dir = str(skill_dir)
    fake_spec.entrypoint = {"command": "python {baseDir}/fail.py", "args": []}

    plan_spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "x", "kind": "skill_exec", "skill": "fail-skill"},
            ],
        },
    )
    plan = parse_meta_plan(plan_spec)
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader([fake_spec]),
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={}))

    assert result.ok is False
    assert result.failed_step_id == "x"
    assert result.error and "exited 7" in result.error
    assert "boom" in result.error


@pytest.mark.asyncio
async def test_orchestrator_skill_exec_requires_entrypoint() -> None:
    """A skill with no entrypoint manifest cannot run as skill_exec."""

    bare = _make_skill_spec("bare", content="no entrypoint here")
    # No bare.entrypoint set — defaults to None.

    plan_spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "x", "kind": "skill_exec", "skill": "bare"},
            ],
        },
    )
    plan = parse_meta_plan(plan_spec)
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent")
        yield  # pragma: no cover

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=_FakeLoader([bare]))
    result = await orch.run(MetaMatch(plan=plan, inputs={}))

    assert result.ok is False
    assert result.failed_step_id == "x"
    assert result.error and "entrypoint manifest" in result.error


def test_parser_rejects_unknown_kind() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "kind": "python", "skill": "x"},
            ],
        },
    )
    with pytest.raises(MetaPlanError, match="kind="):
        parse_meta_plan(spec)


@pytest.mark.asyncio
async def test_orchestrator_llm_classify_uses_llm_chat_when_wired() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "classify",
                    "kind": "llm_classify",
                    "output_choices": ["URL", "PDF", "TEXT"],
                    "with": {"text": "Check: {{ inputs.user_message }}"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader([])

    chat_calls: list[tuple[str, str]] = []

    async def fake_chat(system_prompt: str, user_message: str) -> str:
        chat_calls.append((system_prompt, user_message))
        return "URL"

    async def explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        # Must NOT be invoked when llm_chat is wired.
        raise AssertionError("agent runner must not be called for llm_classify")
        yield  # pragma: no cover — make this an async generator

    orch = MetaOrchestrator(
        agent_runner=explode_runner,
        skill_loader=loader,
        llm_chat=fake_chat,
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "https://x"}))

    assert result.ok, result.error
    assert result.step_outputs["classify"] == "URL"
    assert len(chat_calls) == 1
    sys_prompt, user_msg = chat_calls[0]
    assert "URL | PDF | TEXT" in sys_prompt
    assert "https://x" in user_msg


@pytest.mark.asyncio
async def test_orchestrator_final_text_auto_runs_llm_summary() -> None:
    """``final_text_mode='auto'`` (default for new skills) replaces the
    scheduler-seeded last-step output with an LLM-generated Markdown
    summary so the WebUI doesn't display raw JSON/paths."""
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "render", "skill": "summarize", "with": {"text": "x"}},
            ],
        },
        final_text_mode="auto",
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    skill_spec = _make_skill_spec("summarize", "Summarise input briefly.")
    loader = _FakeLoader([skill_spec])

    chat_calls: list[tuple[str, str]] = []

    async def fake_chat(system_prompt: str, user_message: str) -> str:
        chat_calls.append((system_prompt, user_message))
        return "✅ Meta-skill `meta-x` finished. See `out.txt`."

    async def stub_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="raw-last-step-output-NOT-friendly")

    orch = MetaOrchestrator(
        agent_runner=stub_runner,
        skill_loader=loader,
        llm_chat=fake_chat,
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "u"}))
    assert result.ok, result.error
    assert result.final_text.startswith("✅")
    assert "raw-last-step-output" not in result.final_text
    # exactly one llm_chat call (no llm_classify in this spec → only summary)
    assert len(chat_calls) == 1
    summary_system, summary_user = chat_calls[0]
    assert "Markdown summary" in summary_system
    assert "meta-x" in summary_user
    assert "raw-last-step-output-NOT-friendly" in summary_user


@pytest.mark.asyncio
async def test_orchestrator_final_text_raw_preserves_last_output() -> None:
    """``final_text_mode='raw'`` skips the summariser."""
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "render", "skill": "summarize", "with": {"text": "x"}},
            ],
        },
        final_text_mode="raw",
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader([_make_skill_spec("summarize", "")])

    chat_calls: list[tuple[str, str]] = []

    async def fake_chat(s: str, u: str) -> str:
        chat_calls.append((s, u))
        return "should-not-be-used"

    async def stub_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="raw-deliverable")

    orch = MetaOrchestrator(
        agent_runner=stub_runner,
        skill_loader=loader,
        llm_chat=fake_chat,
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "u"}))
    assert result.ok
    assert result.final_text == "raw-deliverable"
    assert chat_calls == []  # no summariser invocation


@pytest.mark.asyncio
async def test_orchestrator_final_text_step_picks_named_output() -> None:
    """``final_text_mode='step:<id>'`` picks a specific step output."""
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "first", "skill": "summarize", "with": {"text": "x"}},
                {"id": "second", "skill": "summarize", "depends_on": ["first"],
                 "with": {"text": "y"}},
            ],
        },
        final_text_mode="step:first",
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader([_make_skill_spec("summarize", "")])

    call_count = {"n": 0}

    async def numbered_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        call_count["n"] += 1
        yield TextDeltaEvent(text=f"output-from-call-{call_count['n']}")

    orch = MetaOrchestrator(
        agent_runner=numbered_runner,
        skill_loader=loader,
        llm_chat=None,  # not needed; "step:" mode never calls llm_chat
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "u"}))
    assert result.ok
    # first runs first → output-from-call-1; second runs second → call-2;
    # final_text should pick `first`, not the last step.
    assert result.final_text == "output-from-call-1"


@pytest.mark.asyncio
async def test_orchestrator_final_text_auto_falls_back_when_llm_missing() -> None:
    """``auto`` mode without an ``llm_chat`` instance preserves the
    scheduler-seeded text (degraded mode used by older tests / CLI)."""
    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "render", "skill": "summarize", "with": {"text": "x"}},
            ],
        },
        final_text_mode="auto",
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    loader = _FakeLoader([_make_skill_spec("summarize", "")])

    async def stub_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="fallback-deliverable")

    orch = MetaOrchestrator(
        agent_runner=stub_runner,
        skill_loader=loader,
        llm_chat=None,  # not wired
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "u"}))
    assert result.ok
    assert result.final_text == "fallback-deliverable"


@pytest.mark.asyncio
async def test_orchestrator_llm_classify_coerces_noisy_reply() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "classify",
                    "kind": "llm_classify",
                    "output_choices": ["URL", "PDF", "GIT", "TEXT"],
                    "with": {"text": "{{ inputs.user_message }}"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def noisy_chat(_s: str, _u: str) -> str:
        return 'Answer: "URL".'

    async def explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("should not run")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=explode_runner,
        skill_loader=_FakeLoader([]),
        llm_chat=noisy_chat,
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "x"}))

    assert result.ok
    assert result.step_outputs["classify"] == "URL"


@pytest.mark.asyncio
async def test_orchestrator_llm_classify_falls_back_to_agent_runner() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "classify",
                    "kind": "llm_classify",
                    "output_choices": ["A", "B"],
                    "with": {"text": "x"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    runner_calls: list[tuple[str, str]] = []

    async def fallback_runner(system_prompt: str, user_message: str) -> AsyncIterator[AgentEvent]:
        runner_calls.append((system_prompt, user_message))
        yield TextDeltaEvent(text="B")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=fallback_runner,
        skill_loader=_FakeLoader([]),
        llm_chat=None,  # no fast path → degraded mode
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "x"}))

    assert result.ok
    assert result.step_outputs["classify"] == "B"
    assert len(runner_calls) == 1
    assert "EXACTLY ONE of: A | B" in runner_calls[0][0]


@pytest.mark.asyncio
async def test_orchestrator_tool_call_invokes_tool_directly() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "save",
                    "kind": "tool_call",
                    "tool": "memory_save",
                    "tool_args": {
                        "content": "Topic: {{ inputs.topic }}",
                        "mode": "append",
                    },
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    tool_calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_invoker(tool_name: str, args: dict[str, Any]) -> str:
        tool_calls.append((tool_name, args))
        return "saved to memory/2026-05-18.md"

    async def explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("agent runner must not be called for tool_call")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=explode_runner,
        skill_loader=_FakeLoader([]),
        tool_invoker=fake_invoker,
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"topic": "kb"}))

    assert result.ok, result.error
    assert result.step_outputs["save"] == "saved to memory/2026-05-18.md"
    assert tool_calls == [
        ("memory_save", {"content": "Topic: kb", "mode": "append"}),
    ]


@pytest.mark.asyncio
async def test_orchestrator_tool_call_falls_back_to_agent_runner() -> None:
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "save",
                    "kind": "tool_call",
                    "tool": "memory_save",
                    "tool_args": {"content": "hello"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    runner_calls: list[tuple[str, str]] = []

    async def fallback_runner(system_prompt: str, user_message: str) -> AsyncIterator[AgentEvent]:
        runner_calls.append((system_prompt, user_message))
        yield TextDeltaEvent(text="ok")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=fallback_runner,
        skill_loader=_FakeLoader([]),
        tool_invoker=None,
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={}))

    assert result.ok
    assert result.step_outputs["save"] == "ok"
    assert "memory_save" in runner_calls[0][0]
    assert '"content": "hello"' in runner_calls[0][1]


@pytest.mark.asyncio
async def test_orchestrator_mixed_kinds_pipeline() -> None:
    """End-to-end: llm_classify → agent → tool_call, with routing."""
    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "classify",
                    "kind": "llm_classify",
                    "output_choices": ["URL", "TEXT"],
                    "with": {"text": "{{ inputs.user_message }}"},
                },
                {
                    "id": "ingest",
                    "skill": "deep-research",
                    "depends_on": ["classify"],
                    "route": [
                        {"when": "'URL' in outputs.classify", "to": "fetch-url"},
                    ],
                    "with": {"q": "{{ inputs.user_message }}"},
                },
                {
                    "id": "save",
                    "kind": "tool_call",
                    "tool": "memory_save",
                    "depends_on": ["ingest"],
                    "tool_args": {"content": "{{ outputs.ingest }}"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def fake_chat(_s: str, _u: str) -> str:
        return "URL"

    saved: list[dict[str, Any]] = []

    async def fake_invoker(tool: str, args: dict[str, Any]) -> str:
        # skill_view is now called by the orchestrator as the real-tool
        # preface for every skill-loading step — handle it explicitly so the
        # mixed-pipeline assertion only inspects the actual save tool below.
        if tool == "skill_view":
            return f"REAL skill_view: {args['name']}"
        saved.append(args)
        return "saved-ok"

    async def runner(system_prompt: str, _u: str) -> AsyncIterator[AgentEvent]:
        if "FETCH-URL" in system_prompt:
            yield TextDeltaEvent(text="fetched-content")
        else:
            yield TextDeltaEvent(text="other")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader(
            [
                _make_skill_spec("deep-research", content="DEEP-RESEARCH"),
                _make_skill_spec("fetch-url", content="FETCH-URL"),
            ],
        ),
        llm_chat=fake_chat,
        tool_invoker=fake_invoker,
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={"user_message": "https://x"}))

    assert result.ok, result.error
    assert result.step_outputs["classify"] == "URL"
    assert result.step_outputs["ingest"] == "fetched-content"
    assert result.step_outputs["save"] == "saved-ok"
    assert saved == [{"content": "fetched-content"}]


def test_coerce_to_choice_helper() -> None:
    from opensquilla.skills.meta.orchestrator import _coerce_to_choice

    choices = ["URL", "PDF", "GIT", "TEXT"]
    assert _coerce_to_choice("URL", choices) == "URL"
    assert _coerce_to_choice('"URL"', choices) == "URL"
    assert _coerce_to_choice("Answer: URL.", choices) == "URL"
    assert _coerce_to_choice("url", choices) == "URL"  # case-insensitive
    assert _coerce_to_choice("the answer is GIT here", choices) == "GIT"
    # No match → return stripped raw
    assert _coerce_to_choice("definitely something else", choices) == "definitely something else"
    # Empty choices → identity (stripped)
    assert _coerce_to_choice("  hello  ", []) == "hello"


@pytest.mark.asyncio
async def test_iter_events_invokes_real_skill_view_for_skill_steps(
    tmp_path: Path,
) -> None:
    """Each skill_exec / agent step routes through the registered skill_view tool.

    The orchestrator must call ``self._tool_invoker("skill_view", {name: ...})``
    so the request goes through the parent's tool boundary (audit log, sandbox,
    usage tracking). The emitted ``ToolResultEvent`` carries whatever the tool
    actually returned — NOT a pre-computed SKILL.md preview.

    llm_classify and tool_call kinds do not load a SKILL.md, so they MUST NOT
    trigger skill_view.
    """

    from opensquilla.engine.types import ToolResultEvent, ToolUseStartEvent
    from opensquilla.skills.meta.types import MetaResult

    script = tmp_path / "echo.py"
    script.write_text("print('{\"ok\": true}')\n")
    exec_spec = _make_skill_spec("scripty", content="Run the wrapped CLI.")
    exec_spec.base_dir = str(tmp_path)
    exec_spec.entrypoint = {
        "command": "python {baseDir}/echo.py",
        "args": [],
        "parse": "json",
    }
    agent_spec = _make_skill_spec("brainy", content="Sub-agent skill body.")

    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "classify",
                    "kind": "llm_classify",
                    "output_choices": ["A"],
                    "with": {"text": "x"},
                },
                {
                    "id": "ingest",
                    "kind": "skill_exec",
                    "skill": "scripty",
                    "depends_on": ["classify"],
                },
                {
                    "id": "summarise",
                    "skill": "brainy",
                    "depends_on": ["ingest"],
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    invoker_calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_invoker(tool_name: str, args: dict[str, Any]) -> str:
        invoker_calls.append((tool_name, args))
        if tool_name == "skill_view":
            return f"REAL SKILL_VIEW OUTPUT for {args['name']}"
        return "unhandled-tool"

    async def chat(_s: str, _u: str) -> str:
        return "A"

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="summary")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader([exec_spec, agent_spec]),
        llm_chat=chat,
        tool_invoker=fake_invoker,
    )

    skill_view_starts: list[ToolUseStartEvent] = []
    skill_view_results: list[ToolResultEvent] = []
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={"user_message": "x"})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolUseStartEvent) and ev.tool_name == "skill_view":
            skill_view_starts.append(ev)
        elif isinstance(ev, ToolResultEvent) and ev.tool_name == "skill_view":
            skill_view_results.append(ev)

    assert final is not None and final.ok, final.error if final else "no result"
    # The orchestrator must have actually invoked skill_view via the tool
    # boundary, not synthesised the result locally.
    skill_view_invocations = [c for c in invoker_calls if c[0] == "skill_view"]
    assert skill_view_invocations == [
        ("skill_view", {"name": "scripty"}),
        ("skill_view", {"name": "brainy"}),
    ]
    assert len(skill_view_starts) == 2
    assert len(skill_view_results) == 2
    # Result is whatever the tool returned — not a SKILL.md preview.
    assert skill_view_results[0].result == "REAL SKILL_VIEW OUTPUT for scripty"
    assert skill_view_results[1].result == "REAL SKILL_VIEW OUTPUT for brainy"


@pytest.mark.asyncio
async def test_iter_events_skill_view_skipped_when_tool_invoker_absent() -> None:
    """Without a tool_invoker, the orchestrator skips the preface entirely
    rather than fabricating an event. Step execution still proceeds."""

    from opensquilla.engine.types import ToolResultEvent, ToolUseStartEvent
    from opensquilla.skills.meta.types import MetaResult

    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "x", "skill": "brainy", "with": {}},
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="done")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader([_make_skill_spec("brainy", content="B")]),
        tool_invoker=None,
    )

    saw_skill_view = False
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, (ToolUseStartEvent, ToolResultEvent)):
            if ev.tool_name == "skill_view":
                saw_skill_view = True

    assert final is not None and final.ok
    assert saw_skill_view is False


@pytest.mark.asyncio
async def test_iter_events_skill_view_surfaces_tool_invoker_errors() -> None:
    """If skill_view raises, the orchestrator emits an error card and continues
    to the real step executor (which then surfaces its own canonical error)."""

    from opensquilla.engine.types import ToolResultEvent
    from opensquilla.skills.meta.types import MetaResult

    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "x", "skill": "nope", "with": {}},
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def boom_invoker(tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "skill_view":
            raise RuntimeError(f"skill_view: {args['name']!r} not found")
        return ""

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("loader fails first")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader([]),
        tool_invoker=boom_invoker,
    )

    skill_view_results: list[ToolResultEvent] = []
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolResultEvent) and ev.tool_name == "skill_view":
            skill_view_results.append(ev)

    assert final is not None and final.ok is False
    assert len(skill_view_results) == 1
    assert skill_view_results[0].is_error is True
    assert "not found" in skill_view_results[0].result


@pytest.mark.asyncio
async def test_iter_events_emits_step_boundaries() -> None:
    """Each step appears as a ToolUseStart + ToolResult pair so the UI can render it."""

    from opensquilla.engine.types import ToolResultEvent, ToolUseStartEvent
    from opensquilla.skills.meta.types import MetaResult

    spec = _make_meta_spec(
        composition={
            "steps": [
                {
                    "id": "classify",
                    "kind": "llm_classify",
                    "output_choices": ["A", "B"],
                    "with": {"text": "{{ inputs.user_message }}"},
                },
                {
                    "id": "save",
                    "kind": "tool_call",
                    "tool": "memory_save",
                    "depends_on": ["classify"],
                    "tool_args": {"content": "{{ outputs.classify }}"},
                },
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def fake_chat(_s: str, _u: str) -> str:
        return "A"

    saved: list[dict[str, Any]] = []

    async def fake_invoker(_tool: str, args: dict[str, Any]) -> str:
        saved.append(args)
        return "saved"

    async def explode_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("no sub-Agent should be spawned")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=explode_runner,
        skill_loader=_FakeLoader([]),
        llm_chat=fake_chat,
        tool_invoker=fake_invoker,
    )

    starts: list[ToolUseStartEvent] = []
    results: list[ToolResultEvent] = []
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={"user_message": "x"})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolUseStartEvent):
            starts.append(ev)
        elif isinstance(ev, ToolResultEvent):
            results.append(ev)

    assert final is not None and final.ok
    assert [s.tool_name for s in starts] == ["meta-step:classify", "meta-step:save"]
    assert [r.tool_name for r in results] == ["meta-step:classify", "meta-step:save"]
    # Each result includes step metadata so the UI can label the card.
    classify_args = results[0].arguments or {}
    assert classify_args.get("kind") == "llm_classify"
    assert classify_args.get("skill") == "classify"
    save_args = results[1].arguments or {}
    assert save_args.get("kind") == "tool_call"
    # Results carry a preview of the step output.
    assert results[0].result == "A"
    assert results[1].result == "saved"


@pytest.mark.asyncio
async def test_iter_events_forwards_subagent_tool_events_but_folds_text() -> None:
    """For ``agent`` kind steps, sub-Agent's tool events stream through to the
    outer UI (so users see inner tool-call cards), but its TextDeltaEvent is
    folded into the parent meta-step:<id> card and surfaces only through the
    closing ToolResultEvent.result preview. Reduces UI noise for text-heavy
    skills (paper-section-author etc.). Design: docs/proposals/meta-skills/
    MECHANISM.md §17 single user-visible channel."""

    from opensquilla.engine.types import ToolResultEvent, ToolUseStartEvent
    from opensquilla.skills.meta.types import MetaResult

    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "x", "skill": "deep-thinker", "with": {}},
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def inner_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        # Simulate a sub-Agent that calls skill_view then writes a summary.
        yield ToolUseStartEvent(tool_use_id="inner_1", tool_name="skill_view")
        yield ToolResultEvent(
            tool_use_id="inner_1",
            tool_name="skill_view",
            result="loaded SKILL.md content",
        )
        yield TextDeltaEvent(text="final answer is 42")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=inner_runner,
        skill_loader=_FakeLoader([_make_skill_spec("deep-thinker", content="THINK")]),
    )

    forwarded_tool_names: list[str] = []
    text_chunks: list[str] = []
    step_close_previews: list[str] = []
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolUseStartEvent):
            forwarded_tool_names.append(ev.tool_name)
        elif isinstance(ev, TextDeltaEvent):
            text_chunks.append(ev.text)
        elif isinstance(ev, ToolResultEvent) and ev.tool_name.startswith("meta-step:"):
            step_close_previews.append(ev.result or "")

    assert final is not None and final.ok
    # Outer step boundary + inner skill_view both appear (nested cards visible).
    assert "meta-step:x" in forwarded_tool_names
    assert "skill_view" in forwarded_tool_names
    # Sub-Agent's TextDelta is NOT forwarded to outer stream — folded.
    assert "".join(text_chunks) == "", \
        f"sub-Agent TextDelta should not reach outer stream, got: {text_chunks!r}"
    # Final text shows up only in the meta-step closing card preview + MetaResult.
    assert any("final answer is 42" in p for p in step_close_previews), \
        f"final text should appear in step close preview, got: {step_close_previews!r}"
    assert "final answer is 42" in final.final_text


@pytest.mark.asyncio
async def test_iter_events_emits_error_result_on_step_failure() -> None:
    from opensquilla.engine.types import ToolResultEvent
    from opensquilla.skills.meta.types import MetaResult

    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "broken", "skill": "missing-skill", "with": {}},
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        raise AssertionError("loader should fail before reaching runner")
        yield  # pragma: no cover

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader([]),  # missing-skill not registered
    )

    errored: list[ToolResultEvent] = []
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolResultEvent) and ev.is_error:
            errored.append(ev)

    assert final is not None
    assert final.ok is False
    assert len(errored) == 1
    assert "missing-skill" in errored[0].result


def test_expand_skill_placeholders_substitutes_basedir() -> None:
    from opensquilla.skills.meta.orchestrator import _expand_skill_placeholders

    spec = SkillSpec(
        name="multi-search-engine",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="Run `python {baseDir}/scripts/search.py --query X`",
        kind="skill",
        base_dir="/opt/skills/multi-search-engine",
    )
    out = _expand_skill_placeholders(spec)
    assert "{baseDir}" not in out
    assert "/opt/skills/multi-search-engine/scripts/search.py" in out


def test_expand_skill_placeholders_no_base_dir_passes_through() -> None:
    from opensquilla.skills.meta.orchestrator import _expand_skill_placeholders

    spec = SkillSpec(
        name="bare",
        description="d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content="Body with {baseDir} unresolved",
        kind="skill",
        base_dir="",
    )
    # Body unchanged when base_dir is empty.
    assert _expand_skill_placeholders(spec) == "Body with {baseDir} unresolved"


@pytest.mark.asyncio
async def test_drain_agent_runner_does_not_swallow_tool_errors() -> None:
    """A trailing error-result must surface as RuntimeError, not poison downstream steps."""

    from opensquilla.engine.types import ToolResultEvent

    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "broken", "with": {}},
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def error_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        # Sub-Agent calls a tool that errors; emits NO closing plain text.
        yield ToolResultEvent(
            tool_use_id="t1",
            tool_name="glob_search",
            result="No files matched pattern '**/broken/**'",
            is_error=True,
        )
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=error_runner,
        skill_loader=_FakeLoader([_make_skill_spec("broken", content="BROKEN")]),
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={}))

    assert result.ok is False
    assert result.failed_step_id == "a"
    assert result.error and "no plain-text output" in result.error


@pytest.mark.asyncio
async def test_drain_agent_runner_fails_when_sub_agent_produces_no_text() -> None:
    """No plain text from sub-Agent ⇒ step fails — even if a tool returned OK.

    Tool output is not a substitute for the sub-Agent's plain-text deliverable;
    the SKILL.md prompt explicitly asks the sub-Agent to summarise. Promoting
    a tool result silently hides the case where the sub-Agent never wrote a
    summary and the printed bytes are unrelated noise.
    """

    from opensquilla.engine.types import ToolResultEvent

    spec = _make_meta_spec(
        composition={
            "steps": [
                {"id": "a", "skill": "ok-skill", "with": {}},
            ],
        },
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def silent_ok_runner(_s: str, _u: str) -> AsyncIterator[AgentEvent]:
        yield ToolResultEvent(
            tool_use_id="t1",
            tool_name="exec_command",
            result="exit_code=0\nsome_unrelated_output",
            is_error=False,
        )
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=silent_ok_runner,
        skill_loader=_FakeLoader([_make_skill_spec("ok-skill", content="OK-SKILL")]),
    )
    result = await orch.run(MetaMatch(plan=plan, inputs={}))

    assert result.ok is False
    assert result.failed_step_id == "a"
    assert result.error and "no plain-text output" in result.error


def test_bundled_kb_bootstrap_has_routes() -> None:
    bundled = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "bundled"
    skill_path = bundled / "meta-knowledge-base-bootstrap" / "SKILL.md"
    assert skill_path.is_file()
    loader = SkillLoader(
        bundled_dir=bundled,
        snapshot_path=Path("/tmp/_kb_bootstrap_snap.json"),
    )
    loader.invalidate_cache()
    specs = {s.name: s for s in loader.load_all()}
    kb = specs["meta-knowledge-base-bootstrap"]
    plan = parse_meta_plan(kb)
    assert plan is not None
    by_id = {s.id: s for s in plan.steps}
    assert {"classify", "ingest", "memorize", "index"} <= set(by_id)
    # classify must use the lightweight llm_classify executor, not a sub-Agent.
    assert by_id["classify"].kind == "llm_classify"
    assert set(by_id["classify"].output_choices) == {"URL", "PDF", "GIT", "TEXT"}
    # ingest must run multi-search-engine deterministically via skill_exec
    # (no sub-Agent in the loop for the wrapped-CLI step).
    assert by_id["ingest"].kind == "skill_exec"
    assert by_id["ingest"].skill == "multi-search-engine"
    # memorize must call memory_save directly — no LLM in the loop.
    assert by_id["memorize"].kind == "tool_call"
    assert by_id["memorize"].tool == "memory_save"


def test_bundled_migration_assistant_has_routes() -> None:
    bundled = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "bundled"
    skill_path = bundled / "meta-migration-assistant" / "SKILL.md"
    assert skill_path.is_file()
    loader = SkillLoader(
        bundled_dir=bundled,
        snapshot_path=Path("/tmp/_migration_snap.json"),
    )
    loader.invalidate_cache()
    specs = {s.name: s for s in loader.load_all()}
    skill = specs["meta-migration-assistant"]
    plan = parse_meta_plan(skill)
    assert plan is not None
    assert [s.id for s in plan.steps] == ["classify", "fetch_guide", "write_plan"]
    classify = plan.steps[0]
    assert classify.kind == "llm_classify"
    assert "OPENAI_V0_TO_V1" in classify.output_choices
    fetch = plan.steps[1]
    routes_to = {case.to for case in fetch.route}
    assert routes_to == {"github", "multi-search-engine"}
    # Default fallthrough must be deep-research (for OTHER verdict)
    assert fetch.skill == "deep-research"
