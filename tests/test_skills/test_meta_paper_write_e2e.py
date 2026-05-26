"""End-to-end test for meta-paper-write.

Runs the default compact DAG against a tmp workspace with external/search
steps shimmed to canned outputs. The default path returns a clean manuscript
package and compile-readiness note; producing a PDF is an explicit follow-up
through latex-compile.
"""

from __future__ import annotations

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
    assert plan is not None and len(plan.steps) == 14
    assert plan.final_text_mode == "step:final_manuscript_package"
    steps = {step.id: step for step in plan.steps}
    assert steps["paper_mode"].kind == "llm_classify"
    assert steps["paper_preferences"].kind == "llm_chat"
    assert steps["search_papers"].depends_on == ("paper_preferences",)
    assert steps["experiment"].depends_on == ("paper_preferences",)
    assert steps["search_papers"].kind == "skill_exec"
    assert steps["experiment"].kind == "skill_exec"
    assert steps["refbib"].kind == "skill_exec"
    assert steps["plot"].kind == "skill_exec"
    assert "source_pack" in steps
    assert "citation_plan" in steps
    assert "final_manuscript_package" in steps
    assert steps["paper_length_gate"].depends_on == (
        "final_manuscript_package", "citation_plan", "refbib",
    )
    assert steps["citation_integrity_gate"].depends_on == (
        "final_manuscript_package", "citation_plan", "refbib",
    )
    assert steps["latex_sanitizer"].depends_on == (
        "paper_length_gate", "citation_integrity_gate",
    )
    assert steps["compile_latex"].depends_on == ("latex_sanitizer",)
    assert steps["compile_latex"].kind == "llm_chat"

    # Shim: replace multi-search-engine's entrypoint with a stub that
    # echoes a canned JSON. This keeps the test offline (no DuckDuckGo).
    stub_dir = tmp_path / "stub-search"
    stub_dir.mkdir()
    stub_script = stub_dir / "stub.py"
    stub_script.write_text(
        "import json\n"
        "results = [\n"
        "  {'title': f'Reference {i}', "
        "'url': f'https://example.com/{i}', "
        "'snippet': f'snippet {i}'}\n"
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

    # Stub the plot step too, so the test does not depend on matplotlib.
    plot_stub = stub_dir / "plot_stub.py"
    plot_stub.write_text(
        "from pathlib import Path\n"
        "out = Path('paper/figure_1.pdf')\n"
        "out.parent.mkdir(parents=True, exist_ok=True)\n"
        "out.write_bytes(b'%PDF-1.4\\n% stub figure\\n')\n"
        "print(str(out))\n",
        encoding="utf-8",
    )
    plot = specs["paper-plot-stub"]
    plot.base_dir = str(stub_dir)
    plot.entrypoint = {
        "command": f"{sys.executable} {plot_stub}",
        "args": [],
        "parse": "text",
        "timeout": 10,
    }

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
        "paper_preferences": (
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
        "source_pack": (
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
        "outline": (
            "ABSTRACT: This paper studies X.\n"
            "INTRODUCTION: X is important [ref1-ref6].\n"
            "METHOD: We use Y [ref7-ref12].\n"
            "RESULTS: Y improves on baseline [ref13-ref16].\n"
            "DISCUSSION: Future work [ref17-ref20]."
        ),
        "citation_plan": (
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
    manuscript_body = "\n\n".join(
        [
            canned_fragments["abstract"],
            canned_fragments["introduction"],
            canned_fragments["method"],
            canned_fragments["results"],
            canned_fragments["discussion"],
        ],
    )
    canned_fragments["final_manuscript_package"] = (
        "MANUSCRIPT_TEX:\n"
        + manuscript_body
        + "\n\nREFERENCES_BIB:\n"
        + "\n".join(f"@misc{{ref{i}, title={{Reference {i}}}}}" for i in range(1, 26))
        + "\n\nCOMPILE_NOTES:\n- figure_1.pdf provided by plot step"
    )

    async def runner(_system_prompt: str, _user_message: str) -> AsyncIterator[AgentEvent]:
        yield TextDeltaEvent(text="(unexpected agent invocation)")
        yield DoneEvent(text="")

    async def llm_chat(system_prompt: str, _user_message: str) -> str:
        if "deterministic classifier" in system_prompt:
            return "FULL_MANUSCRIPT"
        if "academic-paper requirements" in system_prompt:
            return canned_fragments["paper_preferences"]
        if "curate paper sources" in system_prompt:
            return canned_fragments["source_pack"]
        if "long-form LaTeX paper outlines" in system_prompt:
            return canned_fragments["outline"]
        if "citation placement" in system_prompt:
            return canned_fragments["citation_plan"]
        if "clean LaTeX manuscripts" in system_prompt:
            return canned_fragments["final_manuscript_package"]
        if "manuscript length requirements" in system_prompt:
            return "PASS: estimated 10+ compiled pages"
        if "citation integrity" in system_prompt:
            return "PASS: 25 references available; 20+ cite keys used"
        if "sanitize LaTeX" in system_prompt:
            return "PASS: no markdown fences, process text, or debug logs detected"
        if "compile handoff" in system_prompt:
            return (
                "COMPILE_READY: yes\n"
                "NEXT_STEP: run latex-compile explicitly when the user asks for a PDF\n"
                "BLOCKERS:\n  - none"
            )
        raise AssertionError(f"unexpected llm_chat prompt: {system_prompt}")

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
        llm_chat=llm_chat,
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
    assert final.ok, final.error
    assert final.final_text.startswith("MANUSCRIPT_TEX:")
    assert "COMPILE_READY" not in final.final_text
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
