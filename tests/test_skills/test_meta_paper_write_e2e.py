"""End-to-end test for meta-paper-write.

Runs the full 11-step DAG against a tmp workspace with the search step
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
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch, MetaResult
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
    assert plan is not None and len(plan.steps) == 11

    # Shim: replace multi-search-engine's entrypoint with a stub that
    # echoes a canned JSON. This keeps the test offline (no DuckDuckGo).
    stub_dir = tmp_path / "stub-search"
    stub_dir.mkdir()
    stub_script = stub_dir / "stub.py"
    stub_script.write_text(
        "import json\n"
        "print(json.dumps({\n"
        "  'query': 'x',\n"
        "  'results': [\n"
        "    {'title': 'Foo', 'url': 'https://example.com/a', 'snippet': 'foo s'},\n"
        "    {'title': 'Bar', 'url': 'https://example.com/b', 'snippet': 'bar s'},\n"
        "  ],\n"
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
    canned_fragments: dict[str, str] = {
        "paper-outline-author": (
            "ABSTRACT: This paper studies X.\n"
            "INTRODUCTION: X is important [ref1].\n"
            "METHOD: We use Y.\n"
            "RESULTS: Y improves on baseline.\n"
            "DISCUSSION: Future work."
        ),
        "abstract": r"\begin{abstract} This paper studies X \cite{ref1}. \end{abstract}",
        "introduction": r"\section{Introduction} X is important \cite{ref1}.",
        "method": r"\section{Method} We use Y.",
        "results": (
            r"\section{Results} See Fig.~\ref{fig:1}. "
            r"\begin{figure}[t]\centering"
            r"\includegraphics[width=0.7\linewidth]{figure_1.pdf}"
            r"\caption{ours vs baseline}\label{fig:1}\end{figure}"
        ),
        "discussion": r"\section{Discussion} Future work.",
    }

    async def runner(system_prompt: str, user_message: str) -> AsyncIterator[AgentEvent]:
        if "paper-outline-author" in system_prompt:
            yield TextDeltaEvent(text=canned_fragments["paper-outline-author"])
            yield DoneEvent(text="")
            return
        if "paper-section-author" in system_prompt:
            # The user message includes "section: <name>".
            for section in (
                "abstract", "introduction", "method", "results", "discussion",
            ):
                if f"section: {section}" in user_message:
                    yield TextDeltaEvent(text=canned_fragments[section])
                    break
            else:
                yield TextDeltaEvent(text=r"\section{??}")
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


class _PatchedLoader:
    """Wrap a SkillLoader and return the patched specs by name."""

    def __init__(self, real: SkillLoader, specs: dict[str, SkillSpec]) -> None:
        self._real = real
        self._specs = specs

    def get_by_name(self, name: str) -> SkillSpec | None:
        return self._specs.get(name) or self._real.get_by_name(name)
