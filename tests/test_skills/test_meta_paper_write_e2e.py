"""End-to-end test for meta-paper-write.

Runs the full 15-step DAG against a tmp workspace with the search step
shimmed to a tiny canned JSON, and asserts the pipeline produces a PDF.
Skips xelatex-dependent assertions when xelatex isn't installed.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from opensquilla.engine.types import AgentEvent, DoneEvent, TextDeltaEvent
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.executors.agent import run_step_with_skill_stream
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch, MetaResult, MetaStep
from opensquilla.skills.types import SkillSpec

REPO = Path(__file__).resolve().parents[2]
BUNDLED = REPO / "src" / "opensquilla" / "skills" / "bundled"


@pytest.mark.asyncio
async def test_meta_paper_write_runs_end_to_end(tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=snapshot)
    loader.invalidate_cache()
    specs = {s.name: s for s in loader.load_all()}

    plan_spec = specs.get("meta-paper-write")
    assert plan_spec is not None, "meta-paper-write skill not bundled"
    plan = parse_meta_plan(plan_spec)
    assert plan is not None and len(plan.steps) == 15
    steps = {step.id: step for step in plan.steps}
    assert steps["paper_preferences"].skill == "paper-preference-planner"
    assert steps["search_papers"].depends_on == ("paper_preferences",)
    assert steps["experiment"].depends_on == ("paper_preferences",)
    assert "source_pack" in steps
    assert "citation_plan" in steps
    assert "revised_body" in steps
    assert (
        steps["source_pack"].with_args["paper_preferences"]
        == "{{ outputs.paper_preferences | truncate(4000) }}"
    )
    assert steps["draft_abstract"].skill == "paper-abstract-author"
    assert steps["draft_abstract"].depends_on == ("revised_body", "citation_plan")
    assert steps["compile_latex"].depends_on == ("draft_abstract",)

    # Shim: replace multi-search-engine's entrypoint with a stub that
    # echoes a canned JSON. This keeps the test offline (no DuckDuckGo).
    stub_dir = tmp_path / "stub-search"
    stub_dir.mkdir()
    stub_script = stub_dir / "stub.py"
    stub_script.write_text(
        "import json\n"
        "results = [\n"
        "  {'title': f'Reference {i}', 'url': f'https://example.com/{i}', 'snippet': f'snippet {i}'}\n"
        "  for i in range(1, 26)\n"
        "]\n"
        "print(json.dumps({\n"
        "  'query': 'x',\n"
        "  'results': results,\n"
        "}))\n",
    )
    mse = specs["multi-search-engine"]
    mse.base_dir = str(stub_dir)
    mse.entrypoint = {
        "command": f"{sys.executable} {stub_script}",
        "args": [],
        "parse": "json",
        "timeout": 10,
    }

    # Sub-Agent runner that returns short canned fragments for the
    # outline + section steps. Deterministic; no LLM.
    def long_body(label: str, start_ref: int, count: int, pages: int) -> str:
        cites = " ".join(f"\\cite{{ref{i}}}" for i in range(start_ref, start_ref + count))
        paragraph = (
            f"{label} develops the evaluation argument with concrete operational "
            f"details, explicit assumptions, comparative baselines, and deployment "
            f"constraints {cites}. The repeated offline fixture text is intentionally "
            f"long enough to exercise the long-paper compilation contract without "
            f"calling a live LLM. "
        )
        return "\n\n".join([paragraph * 8 for _ in range(pages)])

    canned_fragments: dict[str, str] = {
        "paper-preference-planner": (
            "PAPER_PREFERENCES:\n"
            "MODE: DIRECT\n"
            "TOPIC: RAG in low-resource settings\n"
            "AUDIENCE: academic\n"
            "VENUE_STYLE: generic research paper\n"
            "LANGUAGE: English\n"
            "DEPTH: deep\n"
            "CITATION_STYLE: numeric\n"
            "EMPHASIS:\n- reliability\n"
            "MUST_INCLUDE:\n- 10+ pages\n"
            "AVOID:\n- unsupported claims\n"
            "DEFAULTS_USED:\n- academic audience\n"
        ),
        "paper-source-curator": (
            "SOURCE_PACK:\n"
            "PRIMARY_SOURCES:\n"
            + "\n".join(
                f"- ref{i} | Reference {i} | reliable source for claim {i}"
                for i in range(1, 21)
            )
            + "\nSUPPORTING_SOURCES:\n"
            + "\n".join(
                f"- ref{i} | Reference {i} | supporting context"
                for i in range(21, 26)
            )
            + "\nEXCLUDED_OR_WEAK_SOURCES:\nCOVERAGE_NOTES:\nCoverage is sufficient."
        ),
        "paper-outline-author": (
            "ABSTRACT: This paper studies X.\n"
            "INTRODUCTION: X is important [ref1-ref6].\n"
            "METHOD: We use Y [ref7-ref12].\n"
            "RESULTS: Y improves on baseline [ref13-ref16].\n"
            "DISCUSSION: Future work [ref17-ref20]."
        ),
        "paper-citation-planner": (
            "CITATION_PLAN:\n"
            "INTRODUCTION:\n"
            "- claim: background; cite: ref1, ref2, ref3, ref4, ref5, ref6; role: prior work\n"
            "METHOD:\n"
            "- claim: setup; cite: ref7, ref8, ref9, ref10, ref11, ref12; role: design\n"
            "RESULTS:\n"
            "- claim: comparison; cite: ref13, ref14, ref15, ref16; role: comparison\n"
            "DISCUSSION:\n"
            "- claim: implications; cite: ref17, ref18, ref19, ref20; role: limitation\n"
            "USAGE_RULES:\nUse citations only for supported claims."
        ),
        "abstract": r"\begin{abstract} This paper studies X \cite{ref1}. \end{abstract}",
        "introduction": "\\section{Introduction}\n" + long_body("Introduction", 1, 6, 3),
        "method": "\\section{Method}\n" + long_body("Method", 7, 6, 3),
        "results": (
            r"\section{Results} See Fig.~\ref{fig:1}. "
            r"\begin{figure}[t]\centering"
            r"\includegraphics[width=0.7\linewidth]{figure_1.pdf}"
            r"\caption{ours vs baseline}\label{fig:1}\end{figure}"
            + "\n"
            + long_body("Results", 13, 4, 2)
        ),
        "discussion": "\\section{Discussion}\n" + long_body("Discussion", 17, 4, 2),
    }
    canned_fragments["paper-revision-author"] = "\n\n".join(
        [
            canned_fragments["introduction"],
            canned_fragments["method"],
            canned_fragments["results"],
            canned_fragments["discussion"],
        ],
    )

    async def runner(system_prompt: str, user_message: str) -> AsyncIterator[AgentEvent]:
        if "paper-preference-planner" in system_prompt:
            yield TextDeltaEvent(text=canned_fragments["paper-preference-planner"])
            yield DoneEvent(text="")
            return
        if "paper-source-curator" in system_prompt:
            yield TextDeltaEvent(text=canned_fragments["paper-source-curator"])
            yield DoneEvent(text="")
            return
        if "paper-citation-planner" in system_prompt:
            yield TextDeltaEvent(text=canned_fragments["paper-citation-planner"])
            yield DoneEvent(text="")
            return
        if "paper-revision-author" in system_prompt:
            yield TextDeltaEvent(text=canned_fragments["paper-revision-author"])
            yield DoneEvent(text="")
            return
        if "paper-abstract-author" in system_prompt:
            yield TextDeltaEvent(text=canned_fragments["abstract"])
            yield DoneEvent(text="")
            return
        if "paper-section-author" in system_prompt:
            # The user message includes "section: <name>".
            for section in (
                "introduction", "method", "results", "discussion",
            ):
                if f"section: {section}" in user_message:
                    yield TextDeltaEvent(text=canned_fragments[section])
                    break
            else:
                yield TextDeltaEvent(text=r"\section{??}")
            yield DoneEvent(text="")
            return
        if "paper-outline-author" in system_prompt:
            yield TextDeltaEvent(text=canned_fragments["paper-outline-author"])
            yield DoneEvent(text="")
            return
        yield TextDeltaEvent(text="(unexpected sub-Agent invocation)")
        yield DoneEvent(text="")

    # Each skill_exec step writes relative paths like ``paper/results.csv``;
    # they must all anchor against the same workspace so a downstream step
    # can pick up an upstream artefact. Pass ``workspace_dir`` explicitly
    # (the production runtime does the same from ``_resolve_bootstrap_workspace_dir``).
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_PatchedLoader(loader, specs),
        workspace_dir=str(workdir),
    )
    final: MetaResult | None = None
    async for ev in orch.iter_events(
        MetaMatch(
            plan=plan,
            inputs={"user_message": "RAG in low-resource settings"},
        ),
    ):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None
    if shutil.which("xelatex") is None:
        # Without xelatex (or matplotlib for the plot step), the pipeline
        # fails before producing a PDF. Accept either of the two
        # missing-dep failure points — both are legitimate "the host lacks
        # the system dependency" branches, not contract violations.
        assert final.ok is False
        assert final.failed_step_id in {"plot", "compile_latex"}
        if final.failed_step_id == "compile_latex":
            assert "xelatex" in (final.error or "").lower()
        return

    assert final.ok, final.error
    pdf = workdir / "paper" / "paper.pdf"
    assert pdf.is_file()
    assert pdf.read_bytes()[:4] == b"%PDF"
    bib = workdir / "paper" / "references.bib"
    assert bib.is_file() and "@misc{ref1," in bib.read_text(encoding="utf-8")
    csv = workdir / "paper" / "results.csv"
    assert csv.is_file()
    fig = workdir / "paper" / "figure_1.pdf"
    assert fig.is_file()


@pytest.mark.asyncio
async def test_paper_section_author_step_output_uses_latex_fragment_only(
    tmp_path: Path,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    loader.load_all()
    step = MetaStep(
        id="draft_results",
        skill="paper-section-author",
        kind="agent",
        with_args={"section": "results"},
    )

    async def runner(_system_prompt: str, _user_message: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(
            text=(
                "The word count is low. Let me expand it.\n"
                "```latex\n"
                "\\section{Results}\n"
                "Clean result prose with Fig.~\\ref{fig:1}.\n"
                "```\n"
                "File written to: /tmp/results.tex"
            ),
        )
        yield DoneEvent(text="")

    events = [
        ev
        async for ev in run_step_with_skill_stream(
            step,
            "paper-section-author",
            {"user_message": "topic"},
            {},
            agent_runner=runner,
            skill_loader=loader,
        )
    ]
    done = [ev for ev in events if isinstance(ev, _StepDone)]
    assert len(done) == 1
    assert done[0].text == (
        "\\section{Results}\n"
        "Clean result prose with Fig.~\\ref{fig:1}."
    )


class _PatchedLoader:
    """Wrap a SkillLoader and return the patched specs by name."""

    def __init__(self, real: SkillLoader, specs: dict[str, SkillSpec]) -> None:
        self._real = real
        self._specs = specs

    def get_by_name(self, name: str) -> SkillSpec | None:
        return self._specs.get(name) or self._real.get_by_name(name)
