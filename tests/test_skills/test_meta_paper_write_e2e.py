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
    # Pipeline rewrite: experiment/plot (skill_exec stubs) → 4 LLM
    # steps that design the experiments and render LaTeX placeholder
    # figures/tables/analysis. Plus a citation_map audit step.
    # paper_collect extracts a same-turn contract instead of pausing on a
    # form. search_query_translation then turns non-English topics into an
    # arXiv-friendly query before hitting Brave/DDG/Tavily.
    assert plan is not None and len(plan.steps) == 18
    assert plan.final_text_mode == "step:final_manuscript_package"
    steps = {step.id: step for step in plan.steps}
    # paper_collect stays in the same model turn; it extracts a visible
    # contract instead of pausing on a form.
    assert steps["paper_collect"].kind == "user_input"
    assert steps["paper_preferences"].kind == "llm_chat"
    assert steps["paper_preferences"].depends_on == ("paper_collect",)
    assert steps["search_query_translation"].kind == "llm_chat"
    assert steps["search_query_translation"].depends_on == ("paper_collect",)
    assert steps["search_papers"].depends_on == (
        "paper_preferences", "search_query_translation",
    )
    # No more skill_exec experiment/plot stubs.
    assert "experiment" not in steps
    assert "plot" not in steps
    # New experiment design + placeholder pipeline.
    assert steps["experiment_design"].kind == "llm_chat"
    assert steps["experiment_design"].depends_on == (
        "paper_preferences", "source_pack",
    )
    assert steps["figure_placeholders"].kind == "llm_chat"
    assert steps["figure_placeholders"].depends_on == ("experiment_design",)
    assert steps["table_placeholders"].kind == "llm_chat"
    assert steps["table_placeholders"].depends_on == ("experiment_design",)
    assert steps["analysis_outline"].kind == "llm_chat"
    assert set(steps["analysis_outline"].depends_on) == {
        "experiment_design", "figure_placeholders", "table_placeholders",
    }
    # Citation provenance audit.
    assert steps["citation_map"].kind == "llm_chat"
    assert steps["citation_map"].depends_on == (
        "final_manuscript_package", "refbib",
    )
    assert steps["search_papers"].kind == "skill_exec"
    assert steps["refbib"].kind == "skill_exec"
    assert "source_pack" in steps
    assert "citation_plan" in steps
    assert "final_manuscript_package" in steps
    # final_manuscript_package now also depends on the placeholder /
    # analysis blocks so they can be inlined verbatim.
    assert set(steps["final_manuscript_package"].depends_on) >= {
        "outline", "citation_plan", "refbib",
        "figure_placeholders", "table_placeholders", "analysis_outline",
    }
    assert steps["paper_length_gate"].depends_on == (
        "final_manuscript_package", "citation_plan", "refbib",
    )
    # citation_integrity_gate now reads citation_map too.
    assert set(steps["citation_integrity_gate"].depends_on) == {
        "final_manuscript_package", "citation_plan", "refbib", "citation_map",
    }
    assert steps["latex_sanitizer"].depends_on == (
        "paper_length_gate", "citation_integrity_gate",
    )
    assert steps["compile_latex"].depends_on == ("latex_sanitizer",)
    assert steps["compile_latex"].kind == "llm_chat"

    # Shim: replace multi-search-engine's entrypoint with a stub that
    # echoes a canned JSON. This keeps the test offline (no DuckDuckGo).
    # Use real arxiv URLs so the upgraded refbib stub emits eprint /
    # archivePrefix fields and the downstream citation_map sees a
    # STRONG source quality classification.
    stub_dir = tmp_path / "stub-search"
    stub_dir.mkdir()
    stub_script = stub_dir / "stub.py"
    stub_script.write_text(
        "import json\n"
        "# 1700.0000N is a deterministic placeholder arxiv id; the stub\n"
        "# only needs the URL pattern to match _ARXIV_RE so eprint is\n"
        "# emitted.\n"
        "results = [\n"
        "  {'title': f'Reference {i}', "
        "'url': f'https://arxiv.org/abs/1700.{i:05d}', "
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
        "experiment_design": (
            "RESEARCH_QUESTIONS:\n"
            "  - id: RQ1; question: Does retrieval improve low-resource QA?\n"
            "  - id: RQ2; question: How does corpus size affect retrieval quality?\n"
            "  - id: RQ3; question: What are the efficiency tradeoffs?\n"
            "HYPOTHESES:\n"
            "  - id: H1; supports: RQ1; statement: RAG outperforms dense baselines.\n"
            "  - id: H2; supports: RQ2; statement: Quality plateaus past 10k docs.\n"
            "VARIABLES:\n"
            "  independent: corpus_size, retriever\n"
            "  dependent: EM, F1, latency\n"
            "  controlled: prompt, model\n"
            "DATASETS:\n"
            "  - HotpotQA-low; 1000; dev; CC BY 4.0; primary benchmark\n"
            "BASELINES:\n"
            "  - DPR; common dense retriever; ref3; ablation\n"
            "METRICS:\n"
            "  - EM; exact-match accuracy; supports: RQ1\n"
            "FIGURE_PLAN:\n"
            "  - id: fig1; type: line; x_axis: corpus size; y_axis: EM; "
            "comparison_groups: DPR / Ours; supports: RQ1; "
            "caption_hint: EM vs corpus size\n"
            "  - id: fig2; type: bar; x_axis: model; y_axis: F1; "
            "comparison_groups: 3 baselines; supports: RQ2; "
            "caption_hint: F1 by model\n"
            "TABLE_PLAN:\n"
            "  - id: tab1; columns: [Method, EM, F1, Latency]; "
            "rows_shape: 3 baselines + Ours + 1 ablation; supports: RQ1; "
            "caption_hint: main results\n"
            "ANALYSIS_DIMENSIONS:\n"
            "  - dimension: performance; figures: [fig1]; tables: [tab1]; "
            "coverage_note: headline result\n"
            "  - dimension: ablation; figures: [fig2]; tables: []; "
            "coverage_note: module contribution\n"
            "  - dimension: efficiency; figures: []; tables: [tab1]; "
            "coverage_note: latency column\n"
        ),
        "figure_placeholders": (
            "% BEGIN_FIGURE_PLACEHOLDERS\n"
            "\\begin{figure}[t]\n  \\centering\n"
            "  \\fbox{\\parbox{0.8\\linewidth}{\\textbf{[Placeholder] fig1}"
            "\\\\x: corpus size; y: EM\\\\groups: DPR / Ours\\\\supports: RQ1}}\n"
            "  \\caption{EM vs corpus size}\n  \\label{fig:fig1}\n"
            "\\end{figure}\n\n"
            "\\begin{figure}[t]\n  \\centering\n"
            "  \\fbox{\\parbox{0.8\\linewidth}{\\textbf{[Placeholder] fig2}"
            "\\\\x: model; y: F1}}\n"
            "  \\caption{F1 by model}\n  \\label{fig:fig2}\n"
            "\\end{figure}\n"
            "% END_FIGURE_PLACEHOLDERS"
        ),
        "table_placeholders": (
            "% BEGIN_TABLE_PLACEHOLDERS\n"
            "\\begin{table}[t]\n  \\centering\n"
            "  \\begin{tabular}{lccc}\n    \\toprule\n"
            "    Method & EM & F1 & Latency \\\\\n    \\midrule\n"
            "    DPR & --- & --- & --- \\\\\n"
            "    BM25 & --- & --- & --- \\\\\n"
            "    Ours & --- & --- & --- \\\\\n"
            "    Ours w/o reranker & --- & --- & --- \\\\\n"
            "    \\bottomrule\n  \\end{tabular}\n"
            "  \\caption{main results}\n  \\label{tab:tab1}\n"
            "\\end{table}\n"
            "% END_TABLE_PLACEHOLDERS"
        ),
        "analysis_outline": (
            "% BEGIN_ANALYSIS_OUTLINE\n"
            "\\subsection{Performance}\n\\label{sec:analysis-performance}\n"
            "References: \\ref{fig:fig1}, \\ref{tab:tab1}.\n"
            "Potential findings: \\begin{itemize}\\item ours wins on EM"
            "\\end{itemize}\n"
            "\\subsection{Ablation}\n"
            "References: \\ref{fig:fig2}.\n"
            "Potential findings: \\begin{itemize}\\item reranker matters"
            "\\end{itemize}\n"
            "% END_ANALYSIS_OUTLINE"
        ),
        "citation_map": (
            "CITATION_MAP:\n\n"
            "| Cite Key | Cited Times | Title | URL / DOI / arXiv | Source Quality |\n"
            "|---|---|---|---|---|\n"
            + "\n".join(
                f"| ref{i} | 1 | Reference {i} | "
                f"https://arxiv.org/abs/1700.{i:05d} (arXiv:1700.{i:05d}) | STRONG |"
                for i in range(1, 21)
            )
            + "\n\nSUMMARY: total_cite_keys=20, strong=20, ok=0, weak=0, "
            "invalid=0, unused=0"
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
        if "paper-drafting requirements" in system_prompt:
            return (
                "TOPIC: RAG in low-resource settings\n"
                "PAPER_MODE: FULL_MANUSCRIPT\n"
                "LANGUAGE: en\n"
                "TARGET_PAGES: 10\n"
                "AUDIENCE: academic\n"
                "MIN_REFERENCES: 20\n"
                "SEARCH_QUERY: RAG low-resource benchmark\n"
                "ASSUMPTIONS:\n  - offline fixture"
            )
        if "paper requirements" in system_prompt:
            return canned_fragments["paper_preferences"]
        if "translate paper topics" in system_prompt:
            # search_query_translation stub: echo a clean English query
            # (the real LLM picks up canonical jargon; here we keep it
            # deterministic for the offline test).
            return "RAG low-resource benchmark"
        if "curate paper sources" in system_prompt:
            return canned_fragments["source_pack"]
        if "design rigorous, falsifiable experiments" in system_prompt:
            return canned_fragments["experiment_design"]
        if "placeholder figure environments" in system_prompt:
            return canned_fragments["figure_placeholders"]
        if "placeholder table environments" in system_prompt:
            return canned_fragments["table_placeholders"]
        if "analysis-chapter outlines" in system_prompt:
            return canned_fragments["analysis_outline"]
        if "long-form LaTeX paper outlines" in system_prompt:
            return canned_fragments["outline"]
        if "citation placement" in system_prompt:
            return canned_fragments["citation_plan"]
        if "clean LaTeX manuscripts" in system_prompt:
            return canned_fragments["final_manuscript_package"]
        if "audit citation provenance" in system_prompt:
            return canned_fragments["citation_map"]
        if "manuscript length requirements" in system_prompt:
            return "PASS: estimated 10+ compiled pages"
        if "citation integrity" in system_prompt:
            return (
                "INTEGRITY: pass\nINVALID_COUNT: 0\nWEAK_PRIMARY_COUNT: 0\n"
                "UNUSED_COUNT: 0\nBLOCKERS:\n  - none\nWARNINGS:\n  - none"
            )
        if "sanitize LaTeX" in system_prompt:
            return "PASS: no markdown fences, process text, or debug logs detected"
        if "compile handoff" in system_prompt:
            return "COMPILE_READY: yes\nNEXT_STEP: run latex-compile explicitly when the user asks for a PDF\nBLOCKERS:\n  - none"
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
            inputs={
                "user_message": "RAG in low-resource settings",
            },
        ),
    ):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None
    assert final.ok, final.error
    assert final.final_text.startswith("MANUSCRIPT_TEX:")
    assert "COMPILE_READY" not in final.final_text
    bib = workdir / "paper" / "references.bib"
    assert bib.is_file()
    bib_text = bib.read_text(encoding="utf-8")
    assert "@misc{ref1," in bib_text
    # Upgraded refbib stub: arxiv URLs → eprint + source domain tag.
    assert "eprint = {1700.00001}" in bib_text
    assert "archivePrefix = {arXiv}" in bib_text
    assert "source: arxiv.org" in bib_text
    # The placeholder/analysis blocks were inlined verbatim into
    # the final manuscript so users see them in the deliverable.
    assert "BEGIN_FIGURE_PLACEHOLDERS" in final.step_outputs["figure_placeholders"]
    assert "BEGIN_TABLE_PLACEHOLDERS" in final.step_outputs["table_placeholders"]
    assert "BEGIN_ANALYSIS_OUTLINE" in final.step_outputs["analysis_outline"]
    # Citation provenance audit ran and produced a markdown table.
    assert "CITATION_MAP:" in final.step_outputs["citation_map"]
    assert "STRONG" in final.step_outputs["citation_map"]
    # No more results.csv / figure_1.pdf artefacts — the placeholder
    # pipeline is purely LaTeX.


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
