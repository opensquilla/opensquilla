"""Offline unit tests for the meta-paper-write bundled scripts.

Tests run bundled paper CLIs or their deterministic operation functions
directly, with no LLM. The point is to catch syntax bugs and confirm the
contract (output files exist + look right) so the meta-skill composition can
rely on them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from pypdf import PdfReader, PdfWriter

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.executors.skill_exec import run_skill_exec_step
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.runtime_env import managed_skill_env

ROOT = Path(__file__).resolve().parents[2]

BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
EXP = ROOT / "src" / "opensquilla" / "skills" / "exp"
TEST_META_RUN_ID = "run-test-paper"


@pytest.fixture(autouse=True)
def _runtime_owned_paper_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_RUN_ID", TEST_META_RUN_ID)


def _paper_run_dir(workspace: Path) -> Path:
    return workspace / "paper" / TEST_META_RUN_ID


def _load_paper_artifact_runtime() -> ModuleType:
    script = BUNDLED / "paper-artifact-runtime" / "scripts" / "run.py"
    spec = spec_from_file_location("paper_artifact_runtime_script", script)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PAPER_ARTIFACT_RUNTIME = _load_paper_artifact_runtime()


def _run_paper_operation(operation: str, **overrides: Any) -> str:
    payload: dict[str, Any] = {
        "operation": operation,
        "meta_run_id": os.environ.get("META_RUN_ID", ""),
    }
    if operation == "persist_sections":
        payload["sections"] = {name: "" for name in PAPER_ARTIFACT_RUNTIME._SECTION_NAMES}
    elif operation == "assemble_manuscript_tex":
        payload.update(bib_text="", writing_plan="", topic="Untitled Manuscript")
    elif operation == "citation_map":
        payload.update(manifest="", refbib="")
    elif operation == "compile_pdf":
        payload.update(
            manuscript_package=os.environ.get("MANUSCRIPT_PKG", ""),
            paper_contract=os.environ.get("PAPER_CONTRACT", ""),
        )
    payload.update(overrides)
    output = PAPER_ARTIFACT_RUNTIME.execute(payload)
    print(output)
    return output


def _meta_paper_steps() -> dict[str, dict[str, object]]:
    skill_md = BUNDLED / "meta-paper-write" / "SKILL.md"
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    end = next(index for index, line in enumerate(lines[1:], start=1) if line == "---")
    frontmatter = yaml.safe_load("\n".join(lines[1:end])) or {}
    steps = (frontmatter.get("composition") or {}).get("steps") or []
    return {str(step["id"]): step for step in steps}


def _skill_frontmatter(name: str) -> dict[str, Any]:
    skill_md = BUNDLED / name / "SKILL.md"
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    end = next(index for index, line in enumerate(lines[1:], start=1) if line == "---")
    loaded = yaml.safe_load("\n".join(lines[1:end])) or {}
    assert isinstance(loaded, dict)
    return loaded


def test_meta_paper_artifact_steps_have_no_shell_or_heredoc_dependency() -> None:
    steps = _meta_paper_steps()
    for operation in (
        "persist_sections",
        "assemble_manuscript_tex",
        "citation_map",
        "compile_pdf",
    ):
        step = steps[operation]
        assert step["kind"] == "skill_exec"
        assert step["skill"] == "paper-artifact-runtime"
        assert step.get("tool") is None
        assert step.get("tool_args") is None
        assert f'"operation": "{operation}"' in str(step["with"])

    raw = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    assert "<<'PY'" not in raw
    assert "python3 - <<" not in raw

    runtime = _skill_frontmatter("paper-artifact-runtime")
    entrypoint = runtime["entrypoint"]
    assert entrypoint["command"] == "python"
    assert entrypoint["args"] == ["{baseDir}/scripts/run.py"]
    assert not any(token in str(entrypoint) for token in ("<<", "| python", "cmd /c"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ("persist_sections", "assemble_manuscript_tex", "citation_map", "compile_pdf"),
)
async def test_meta_paper_artifact_operations_spawn_platform_neutral_python_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    loader.invalidate_cache()
    spec = loader.get_by_name("meta-paper-write")
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None
    step = next(candidate for candidate in plan.steps if candidate.id == operation)
    captured: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, b"fixture output\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    outputs = {
        "section_abstract": "abstract",
        "section_introduction": "introduction",
        "section_related_work": "related work",
        "section_method": "method",
        "section_experiments": "experiments",
        "section_discussion": "discussion",
        "section_conclusion": "conclusion",
        "refbib": "@misc{ref1, title={Fixture}}",
        "writing_plan": "TITLE: Fixture",
        "paper_contract": "TARGET_PAGES: 1",
        "latex_sanitizer": "MANUSCRIPT_TEX: fixture",
    }

    result = await run_skill_exec_step(
        step,
        effective_skill="paper-artifact-runtime",
        inputs={"meta_run_id": TEST_META_RUN_ID},
        outputs=outputs,
        skill_loader=loader,
        workspace_dir=str(tmp_path),
    )

    runtime_spec = loader.get_by_name("paper-artifact-runtime")
    assert runtime_spec is not None
    assert captured["argv"] == [
        sys.executable,
        str(Path(runtime_spec.base_dir) / "scripts" / "run.py"),
    ]
    kwargs = captured["kwargs"]
    assert "shell" not in kwargs
    payload = json.loads(kwargs["input"].decode("utf-8"))
    assert payload["operation"] == operation
    assert payload["meta_run_id"] == TEST_META_RUN_ID
    assert result == "fixture output"


def test_paper_artifact_runtime_persists_assembles_and_maps_citations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sections = {
        "abstract": "```latex\n\\begin{abstract}Summary.\\end{abstract}\n```",
        "introduction": r"\section{Introduction} Evidence \cite{ref1}.",
        "related_work": r"\section{Related Work} Prior work \cite{ref2}.",
        "method": r"\section{Method} Method.",
        "experiments": r"\section{Experiments} Planned evaluation.",
        "discussion": r"\section{Discussion} Discussion.",
        "conclusion": r"\section{Conclusion} Conclusion.",
    }
    persisted = _run_paper_operation("persist_sections", sections=sections)
    assert "SECTION_ARTIFACTS:" in persisted
    assert "TOTAL_SECTION_CHARS:" in persisted

    bibliography = (
        "@misc{ref1,\n"
        "  title = {Reference One},\n"
        "  url = {https://arxiv.org/abs/1700.00001}\n"
        "}\n"
        "@article{ref2,\n"
        "  title = {Reference Two},\n"
        "  doi = {10.1000/fixture}\n"
        "}\n"
    )
    assembled = _run_paper_operation(
        "assemble_manuscript_tex",
        bib_text=bibliography,
        writing_plan="TITLE: Safe & Cross-Platform Paper",
        topic="fallback",
    )
    run_dir = _paper_run_dir(tmp_path)
    assert f"MANUSCRIPT_PATH: {(run_dir / 'paper.tex').resolve()}" in assembled
    assert f"REFERENCES_PATH: {(run_dir / 'references.bib').resolve()}" in assembled
    tex = (run_dir / "paper.tex").read_text(encoding="utf-8")
    assert r"\title{Safe \& Cross-Platform Paper}" in tex
    assert "```latex" not in tex

    mapped = _run_paper_operation(
        "citation_map",
        manifest=assembled,
        refbib=bibliography,
    )
    assert "| ref1 | 1 | Reference One |" in mapped
    assert "| ref2 | 1 | Reference Two |" in mapped
    assert "SUMMARY: total_cite_keys=2, strong=2, ok=0, weak=0, invalid=0, unused=0" in mapped


def test_paper_artifact_runtime_adds_dependency_free_cjk_line_breaking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    sections = {name: "" for name in PAPER_ARTIFACT_RUNTIME._SECTION_NAMES}
    sections["introduction"] = (
        r"\section{引言}"
        "这是一段没有人工空格的连续中文正文，用于验证真实论文在页面边界处可以自然换行，"
        "而不是依赖一个碰巧能够放进单行的短句。"
    )
    _run_paper_operation("persist_sections", sections=sections)
    _run_paper_operation(
        "assemble_manuscript_tex",
        writing_plan="TITLE: 中文论文交付验证",
    )

    tex = (_paper_run_dir(tmp_path) / "paper.tex").read_text(encoding="utf-8")
    locale = r'\XeTeXlinebreaklocale "zh"'
    glue = r"\XeTeXlinebreakskip = 0pt plus 1pt"
    assert tex.count(locale) == 1
    assert tex.count(glue) == 1
    assert tex.index(locale) < tex.index(r"\begin{document}")
    assert tex.index(glue) < tex.index(r"\begin{document}")
    assert "xeCJK" not in tex
    assert "ctex" not in tex

    minimal = (
        r"\documentclass{article}"
        "\n"
        r"\begin{document}连续中文正文必须自然换行。\end{document}"
    )
    prepared = PAPER_ARTIFACT_RUNTIME._prepare_tex(minimal)
    assert prepared.count(locale) == 1
    assert prepared.count(glue) == 1
    assert PAPER_ARTIFACT_RUNTIME._prepare_tex(prepared) == prepared

    partially_configured = minimal.replace(
        r"\begin{document}",
        r'\XeTeXlinebreaklocale "ja"' + "\n" + r"\begin{document}",
    )
    normalized = PAPER_ARTIFACT_RUNTIME._prepare_tex(partially_configured)
    assert normalized.count(r"\XeTeXlinebreaklocale") == 1
    assert normalized.count(r"\XeTeXlinebreakskip") == 1
    assert locale in normalized
    assert r'\XeTeXlinebreaklocale "ja"' not in normalized


def test_paper_artifact_runtime_cli_reads_json_from_stdin(tmp_path: Path) -> None:
    script = BUNDLED / "paper-artifact-runtime" / "scripts" / "run.py"
    payload = {
        "operation": "persist_sections",
        "meta_run_id": TEST_META_RUN_ID,
        "sections": {
            name: f"\\section{{{name}}}"
            for name in PAPER_ARTIFACT_RUNTIME._SECTION_NAMES
        },
    }

    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "SECTION_ARTIFACTS:" in result.stdout
    assert (_paper_run_dir(tmp_path) / "sections" / "abstract.tex").is_file()


def test_meta_paper_artifacts_are_namespaced_by_runtime_owned_run_id() -> None:
    steps = _meta_paper_steps()
    for step_id in (
        "persist_sections",
        "assemble_manuscript_tex",
        "citation_map",
        "compile_pdf",
    ):
        with_args = steps[step_id]["with"]
        assert isinstance(with_args, dict)
        assert "inputs.meta_run_id | tojson" in str(with_args["payload"])
    publish_args = steps["publish_pdf"]["tool_args"]
    assert isinstance(publish_args, dict)
    assert publish_args["path"] == "paper/{{ inputs.meta_run_id }}/paper.pdf"
    raw = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    assert "Path('paper') / 'sections'" not in raw
    assert "Path('paper'); paper.mkdir" not in raw
    assert "cwd='paper'" not in raw
    assert 'path: "paper/paper.pdf"' not in raw
    runtime_script = (
        BUNDLED / "paper-artifact-runtime" / "scripts" / "run.py"
    ).read_text(encoding="utf-8")
    assert "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$" in runtime_script


def _compile_fixture_package() -> str:
    return (
        "MANUSCRIPT_TEX:\n"
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Fixture manuscript.\n"
        "\\end{document}\n"
        "REFERENCES_BIB:\n"
        "@misc{fixture, title={Fixture}, year={2026}}\n"
    )


def _fake_tex_run(
    calls: list[list[str]],
    *,
    page_count: int,
    fail_at: int | None = None,
    final_xelatex_output: str = "",
):
    def run(
        command: list[str],
        *,
        cwd: str | Path,
        capture_output: bool,
        text: bool,
        env: dict[str, str],
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert check is False
        assert 0 < timeout <= 110
        assert env["openin_any"] == "p"
        assert env["openout_any"] == "p"
        assert env["TEXINPUTS"] == f".{os.pathsep}"
        assert env["BIBINPUTS"] == f".{os.pathsep}"
        assert env["BSTINPUTS"] == f".{os.pathsep}"
        calls.append(list(command))
        if fail_at == len(calls):
            return subprocess.CompletedProcess(command, 17, "", "fixture compiler failed")
        if Path(command[0]).name == "xelatex":
            paper_dir = Path(cwd)
            writer = PdfWriter()
            for _ in range(page_count):
                writer.add_blank_page(width=612, height=792)
            with (paper_dir / "paper.pdf").open("wb") as handle:
                writer.write(handle)
        stdout = "fixture compiler ok"
        if len(calls) == 4 and Path(command[0]).name == "xelatex":
            stdout = final_xelatex_output or stdout
        return subprocess.CompletedProcess(command, 0, stdout, "")

    return run


# The paper-experiment-stub and paper-plot-stub skills were removed
# when meta-paper-write was rewritten to design experiments at the
# LLM level and render zero-dependency LaTeX placeholder figures /
# tables. The unit tests that exercised those stubs (fake CSV +
# matplotlib chart) are gone with them.


def test_paper_refbib_stub_emits_bibtex_from_stdin_json(tmp_path: Path) -> None:
    payload = {
        "query": "asyncio",
        "results": [
            {
                "title": "asyncio docs",
                "url": "https://docs.python.org/3/library/asyncio.html",
                "snippet": "Asynchronous I/O.",
            },
            {
                "title": "Real Python on asyncio",
                "url": "https://realpython.com/async-io-python/",
                "snippet": "Hands-on walkthrough.",
            },
        ],
    }
    out = tmp_path / "references.bib"
    script = BUNDLED / "paper-refbib-stub" / "scripts" / "json_to_bib.py"
    result = subprocess.run(
        [sys.executable, str(script), "--out", str(out)],
        input=json.dumps(payload),
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.is_file()
    bib = out.read_text(encoding="utf-8")
    assert "@misc{ref1," in bib
    assert "@misc{ref2," in bib
    assert "docs.python.org" in bib
    # stdout mirrors the file for easy piping/inspection.
    assert "@misc{ref1," in result.stdout


def test_meta_paper_write_declares_long_paper_generation_contract() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    search = (BUNDLED / "multi-search-engine" / "SKILL.md").read_text(encoding="utf-8")
    outline = (BUNDLED / "paper-outline-author" / "SKILL.md").read_text(encoding="utf-8")
    section = (BUNDLED / "paper-section-author" / "SKILL.md").read_text(encoding="utf-8")

    assert "{{ with.max_results | default(25) }}" in search
    assert "10+ page" in outline
    assert "20+ distinct citation keys" in outline
    assert "writing-plan-derived" in section
    assert "Do not impose a fixed page count" in section
    assert "Write only the assigned section" in section
    assert "lower-bound delivery budget" in section
    assert "related_work" in section
    assert "conclusion" in section
    assert "Do not call tools" in section
    assert "organize by methodology or claim axis" in section
    assert "no invented results" in section
    assert "{{ outputs.refbib | truncate(8000) }}" in meta


def test_paper_section_author_preserves_math_delimiters() -> None:
    section = (BUNDLED / "paper-section-author" / "SKILL.md").read_text(encoding="utf-8")

    assert "Do NOT escape math delimiter dollars" in section
    assert "\\( ... \\)" in section


def test_meta_paper_write_declares_quality_pipeline_stages() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")

    # Search + bibliography pipeline.
    assert "multi-search-engine" in meta
    assert "paper-refbib-stub" in meta
    assert "engines: [crossref, brave, tavily]" in meta
    assert "max_results: 30" in meta
    assert "site:arxiv.org OR" not in meta
    assert "paper-source-readiness-gate" in meta
    assert "SOURCE_STATUS: <sufficient|insufficient>" in meta
    assert "USABLE_REFERENCE_COUNT:" in meta
    assert "USABLE_KEYS:" in meta
    # Core LLM-driven design stages.
    assert "paper_preferences" in meta
    assert "{{ outputs.paper_preferences | truncate(2000) }}" in meta
    assert "source_pack" in meta
    assert "experiment_design" in meta
    assert "FIGURE_PLAN:" in meta
    assert "TABLE_PLAN:" in meta
    assert "ANALYSIS_DIMENSIONS:" in meta
    assert "figure_placeholders" in meta
    assert "table_placeholders" in meta
    assert "analysis_outline" in meta
    assert "citation_plan" in meta
    assert "final_manuscript_package" in meta
    # Citation provenance audit + strict citation contract.
    assert "citation_map" in meta
    assert "DO NOT invent cite keys" in meta
    assert "Source Quality" in meta
    # Quality bar / mode behavior.
    assert "CITATION_TARGET" in meta
    assert "LENGTH_STRATEGY" in meta
    assert "do not enforce a fixed count" in meta
    assert "default path is COMPACT_SKELETON" in meta
    assert "Explicit full/PDF/long-form requests use" in meta
    assert "compiled PDF" in meta
    assert "refuses to create degraded PDF" in meta
    assert "paper-quality-gate" in meta
    assert "paper-length-gate" in meta
    assert "paper-citation-integrity-gate" in meta
    assert "publication_quality_gate" in meta
    assert "depends_on: [latex_sanitizer, publication_quality_gate" in meta


def test_meta_paper_write_plans_user_requested_page_target_up_front() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    runtime = (
        BUNDLED / "paper-artifact-runtime" / "scripts" / "run.py"
    ).read_text(encoding="utf-8")

    assert "TARGET_PAGES:" in meta
    assert "This writing plan is the length-control point" in meta
    assert "allocating enough section scope" in meta
    assert "minimum total target_words" in meta
    assert "PER_SECTION_BLUEPRINT.*.target_words" in meta
    assert "target_words from writing_plan" in meta
    assert "PDF_PAGE_TARGET_NOT_MET" in runtime
    assert "PDF_TARGET_PAGES:" in runtime
    assert "LENGTH_GATE: fail" not in meta


def test_meta_paper_write_pushes_length_into_plan_and_section_prompts() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    section = (BUNDLED / "paper-section-author" / "SKILL.md").read_text(encoding="utf-8")

    assert "TARGET_PAGES × 820" in meta
    assert "TARGET_PAGES × 760" in meta
    assert "target_words is a lower-bound writing budget" in meta
    assert "at least 90% of target_words" in meta
    assert "Do not return an undersized section" in meta
    assert "lower-bound delivery budget" in section
    assert "below 90% of target_words" in section
    assert "Expand before replying" in section
    assert "short, complete, well-cited section" not in section
    assert "repeated context compaction" not in section


def test_meta_paper_write_forbids_fabricated_result_numbers() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    section = (BUNDLED / "paper-section-author" / "SKILL.md").read_text(encoding="utf-8")

    assert "PLACEHOLDER_RESULT_TOKEN" in meta
    assert "Do not invent empirical numbers" in meta
    assert "Do not state exact numeric improvements" in meta
    assert "headline_result_number" not in meta
    assert "main_result_number" not in meta
    assert "no invented results" in section
    assert "quantitative values must remain placeholders" in section
    assert "EVIDENCE_STATUS" in meta
    assert "No empirical results were supplied" in meta
    assert "first experimental evidence" in meta
    assert "evidence_contract (authoritative even if writing_plan is truncated)" in meta
    assert "interpretation_criteria" in meta
    assert "Do not invent" in meta
    assert "forecast magnitude when evidence is not supplied" in section


def test_meta_paper_write_sanitizes_artifact_before_strict_publication_gate() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")

    sanitizer = meta.index("    - id: latex_sanitizer")
    length_gate = meta.index("    - id: paper_length_gate")
    quality_gate = meta.index("    - id: publication_quality_gate")
    assert sanitizer < length_gate < quality_gate
    assert "skill: paper-latex-sanitizer" in meta[sanitizer:length_gate]
    assert '"manuscript_package": {{ outputs.latex_sanitizer | tojson }}' in meta
    assert '"manuscript_package": {{ outputs.latex_sanitizer | tojson }}' in meta[
        quality_gate:
    ]


def test_meta_paper_write_prevents_silent_latex_glyph_and_layout_degradation() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    runtime = (
        BUNDLED / "paper-artifact-runtime" / "scripts" / "run.py"
    ).read_text(encoding="utf-8")
    section = (BUNDLED / "paper-section-author" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "literal Unicode Greek" in meta
    assert r"\(\varepsilon\)" in meta
    assert "Unicode U+2011, U+2013, or U+2014" in meta
    assert r"\resizebox{\linewidth}{!}" in meta
    assert "LATEX_OUTPUT_QUALITY_GATE" in runtime
    assert "literal Unicode Greek" in section
    assert "C1--C5" in section


def test_meta_paper_write_frames_evidence_free_captions_as_plans_or_hypotheses() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")

    assert "EVIDENCE_STATUS: <copy supplied|not_supplied from paper facts verbatim>" in meta
    assert '"Planned evaluation placeholder:" / "计划评估占位："' in meta
    assert "categorical observed finding" in meta
    assert "Concrete setup values and predefined metric thresholds may appear" in meta
    assert "This is the only case where you" in meta
    assert "MUST rewrite a noncompliant caption_hint" in meta


def test_meta_paper_write_keeps_explicit_citation_targets_machine_readable() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")

    assert '"at least 15 references"' in meta
    assert '"至少15篇参考文献"' in meta
    assert "MUST produce CITATION_TARGET: 15" in meta
    assert "CITATION_TARGET: <integer only:" in meta
    assert "never output AUTO, ≥, prose, or units" in meta
    assert "citation_target" in meta


def test_meta_paper_write_scrubs_numeric_table_cells_before_compile() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")
    runtime = (
        BUNDLED / "paper-artifact-runtime" / "scripts" / "run.py"
    ).read_text(encoding="utf-8")

    assert "def _scrub_placeholder_table_cells" in runtime
    assert "Scrub numeric-looking data cells" in runtime
    assert "tex = _scrub_placeholder_table_cells(tex)" in runtime
    assert "return _scrub_placeholder_table_cells(tex_body)" in runtime
    assert "Every non-label data cell MUST be a placeholder" in meta


def test_paper_preference_planner_declares_two_generation_modes() -> None:
    planner = (
        BUNDLED / "paper-preference-planner" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "MODE: DIRECT | PREFERENCE_DRIVEN" in planner
    assert "direct generation" in planner
    assert "ask the user" in planner
    assert "do not invent preferences" in planner


def test_bundled_meta_skills_do_not_exec_prompt_only_memory_skill() -> None:
    offenders: list[str] = []
    for skill_md in sorted([*BUNDLED.glob("meta-*/SKILL.md"), *EXP.glob("meta-*/SKILL.md")]):
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        lines = text.splitlines()
        end = next(
            (index for index, line in enumerate(lines[1:], start=1) if line == "---"),
            None,
        )
        assert end is not None, f"{skill_md}: missing YAML frontmatter terminator"
        frontmatter = "\n".join(lines[1:end])
        data = yaml.safe_load(frontmatter) or {}
        for step in (data.get("composition") or {}).get("steps") or []:
            if step.get("kind") == "skill_exec" and step.get("skill") == "memory":
                offenders.append(f"{data.get('name')}:{step.get('id')}")
            if (
                step.get("kind", "agent") == "agent"
                and step.get("skill") == "memory"
            ):
                offenders.append(f"{data.get('name')}:{step.get('id')}")

    assert offenders == []


def test_latex_compile_produces_pdf(tmp_path: Path) -> None:
    pytest = __import__("pytest")
    if shutil.which("xelatex") is None:
        pytest.skip("xelatex not installed")

    tex = tmp_path / "paper.tex"
    tex.write_text(
        r"""\documentclass{article}
\begin{document}
Hello, world.
\end{document}
""",
        encoding="utf-8",
    )
    script = BUNDLED / "latex-compile" / "scripts" / "compile.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(tex)],
        check=True,
        capture_output=True,
        text=True,
    )
    pdf = tmp_path / "paper.pdf"
    assert pdf.is_file()
    assert pdf.read_bytes()[:4] == b"%PDF"
    # stdout is the clean user-facing deliverable line (PDF path + size).
    # The verbose xelatex log tail is routed to stderr so it survives for
    # debugging without polluting the meta-skill's final_text payload.
    assert "paper.pdf" in proc.stdout.lower()
    assert "successfully" in proc.stdout.lower()


def test_latex_compile_reassembles_clean_cjk_paper_from_section_files(
    tmp_path: Path,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    script = BUNDLED / "latex-compile" / "scripts" / "compile.py"
    spec = spec_from_file_location("latex_compile_script", script)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    workspace = tmp_path / "workspace"
    paper_dir = workspace / "paper"
    paper_dir.mkdir(parents=True)
    tex = paper_dir / "paper.tex"
    tex.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Let me write the paper first. ```latex\\n"
        "\\section{Method} 污染内容\\n```"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (workspace / "abstract.tex").write_text(
        "\\begin{abstract} 中文摘要。\\end{abstract}\n",
        encoding="utf-8",
    )
    (workspace / "introduction.tex").write_text(
        "\\section{Introduction} Clean intro.\n",
        encoding="utf-8",
    )
    (paper_dir / "method.tex").write_text(
        "\\section{实验方法} 中文方法。\n",
        encoding="utf-8",
    )
    (workspace / "results.tex").write_text(
        "\\section{Results} Clean results.\n",
        encoding="utf-8",
    )
    (workspace / "discussion.tex").write_text(
        "\\section{Discussion} Clean discussion.\n",
        encoding="utf-8",
    )
    (paper_dir / "references.bib").write_text("", encoding="utf-8")

    assert mod._prepare_tex_for_compile(tex) is True
    rewritten = tex.read_text(encoding="utf-8")
    assert "\\usepackage{xeCJK}" in rewritten
    assert "\\setCJKmainfont" in rewritten
    assert "\\section{实验方法} 中文方法。" in rewritten
    assert "Let me write the paper first" not in rewritten
    assert "```latex" not in rewritten


def test_latex_compile_uses_managed_pinned_cjk_font(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    script = BUNDLED / "latex-compile" / "scripts" / "compile.py"
    spec = spec_from_file_location("latex_compile_managed_font", script)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    fonts = tmp_path / "managed-fonts"
    fonts.mkdir()
    (fonts / "NotoSansCJK-Regular.ttc").write_bytes(b"synthetic-font")
    monkeypatch.setenv("OSFONTDIR", str(fonts))

    preamble = mod._cjk_preamble("中文标题", "中文正文")

    assert "\\usepackage{fontspec}" in preamble
    assert "\\setmainfont[FontIndex=2]{NotoSansCJK-Regular.ttc}" in preamble
    assert "xeCJK" not in preamble


def test_latex_compile_keeps_clean_revised_body_over_section_files(
    tmp_path: Path,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    script = BUNDLED / "latex-compile" / "scripts" / "compile.py"
    spec = spec_from_file_location("latex_compile_script", script)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    workspace = tmp_path / "workspace"
    paper_dir = workspace / "paper"
    paper_dir.mkdir(parents=True)
    tex = paper_dir / "paper.tex"
    tex.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{abstract} Final abstract.\\end{abstract}\n"
        "\\section{Introduction} Revised intro.\n"
        "\\section{Method} Revised method.\n"
        "\\section{Results} Revised results.\n"
        "\\section{Discussion} Revised discussion.\n"
        "\\bibliography{references}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (workspace / "introduction.tex").write_text(
        "\\section{Introduction} Stale intro.\n",
        encoding="utf-8",
    )
    (paper_dir / "method.tex").write_text(
        "\\section{Method} Stale method.\n",
        encoding="utf-8",
    )
    (workspace / "results.tex").write_text(
        "\\section{Results} Stale results.\n",
        encoding="utf-8",
    )
    (workspace / "discussion.tex").write_text(
        "\\section{Discussion} Stale discussion.\n",
        encoding="utf-8",
    )
    (workspace / "abstract.tex").write_text(
        "\\begin{abstract} Stale abstract.\\end{abstract}\n",
        encoding="utf-8",
    )

    assert mod._prepare_tex_for_compile(tex) is False
    rewritten = tex.read_text(encoding="utf-8")
    assert "Revised intro" in rewritten
    assert "Stale intro" not in rewritten


def test_latex_compile_validates_long_paper_citation_contract(
    tmp_path: Path,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    script = BUNDLED / "latex-compile" / "scripts" / "compile.py"
    spec = spec_from_file_location("latex_compile_script", script)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    tex = tmp_path / "paper.tex"
    tex.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Introduction} Too few refs \\cite{ref1,ref2}.\n"
        "\\bibliography{references}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "references.bib").write_text(
        "\n".join(
            f"@misc{{ref{i}, title={{Reference {i}}}, year={{2026}}}}"
            for i in range(1, 25)
        ),
        encoding="utf-8",
    )

    errors = mod._validate_citation_contract(tex, min_cited_refs=20)
    assert any("at least 20 cited references" in error for error in errors)

    tex.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Introduction} "
        + " ".join(f"\\cite{{ref{i}}}" for i in range(1, 21))
        + " \\cite{missing_ref}.\n"
        "\\bibliography{references}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    errors = mod._validate_citation_contract(tex, min_cited_refs=20)
    assert any("undefined citation keys: missing_ref" in error for error in errors)

    tex.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Introduction} "
        + " ".join(f"\\cite{{ref{i}}}" for i in range(1, 21))
        + ".\n"
        "\\bibliography{references}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    assert mod._validate_citation_contract(tex, min_cited_refs=20) == []


def test_latex_compile_parses_minimum_page_contract() -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    script = BUNDLED / "latex-compile" / "scripts" / "compile.py"
    spec = spec_from_file_location("latex_compile_script", script)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    short_log = "Output written on paper.pdf (9 pages, 12345 bytes)."
    long_log = "Output written on paper.pdf (11 pages, 67890 bytes)."
    assert mod._validate_page_contract(short_log, min_pages=10) == [
        "paper must be at least 10 pages; compiled PDF has 9 pages"
    ]
    assert mod._validate_page_contract(long_log, min_pages=10) == []


def test_meta_compile_pdf_reads_real_pdf_and_enforces_requested_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 3\n",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_tex_run(calls, page_count=3))

    _run_paper_operation("compile_pdf")

    pdf = _paper_run_dir(tmp_path) / "paper.pdf"
    reader = PdfReader(pdf)
    assert len(reader.pages) == 3
    assert [Path(command[0]).name for command in calls] == [
        "xelatex",
        "bibtex",
        "xelatex",
        "xelatex",
    ]
    assert all("-halt-on-error" in command for command in calls if command[0] == "xelatex")
    output = capsys.readouterr().out
    assert f"PDF_PATH: {pdf.resolve()}" in output
    assert "PDF_PAGES: 3" in output
    assert "PDF_TARGET_PAGES: 3" in output


def test_two_paper_sessions_do_not_overwrite_cleanup_or_publish_each_other(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two session-owned run ids share a workspace without sharing artifacts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 3\n",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_tex_run(calls, page_count=3))
    run_a = "run-session-a"
    run_b = "run-session-b"
    monkeypatch.setenv("META_RUN_ID", run_a)
    _run_paper_operation("compile_pdf")
    run_a_dir = tmp_path / "paper" / run_a
    run_a_pdf = run_a_dir / "paper.pdf"
    run_a_bytes = run_a_pdf.read_bytes()
    survivor = run_a_dir / "paper.aux"
    survivor.write_text("belongs-to-run-a", encoding="utf-8")

    monkeypatch.setenv("META_RUN_ID", run_b)
    _run_paper_operation("compile_pdf")
    run_b_dir = tmp_path / "paper" / run_b
    run_b_pdf = run_b_dir / "paper.pdf"

    assert len(calls) == 8
    assert run_a_pdf.read_bytes() == run_a_bytes
    assert survivor.read_text(encoding="utf-8") == "belongs-to-run-a"
    assert len(PdfReader(run_a_pdf).pages) == 3
    assert len(PdfReader(run_b_pdf).pages) == 3
    assert run_a_pdf.resolve() != run_b_pdf.resolve()
    output = capsys.readouterr().out
    assert f"PDF_PATH: {run_a_pdf.resolve()}" in output
    assert f"PDF_PATH: {run_b_pdf.resolve()}" in output


@pytest.mark.parametrize("run_id", ["", "../escape", "run/escape", "x" * 65])
def test_meta_compile_pdf_rejects_untrusted_run_id_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_id: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("META_RUN_ID", run_id)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 3\n",
    )

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError):
        _run_paper_operation("compile_pdf")
    assert not (tmp_path / "paper").exists()


@pytest.mark.parametrize(
    "step_id",
    ["persist_sections", "assemble_manuscript_tex", "citation_map", "compile_pdf"],
)
@pytest.mark.parametrize("link_level", ["paper-root", "run-directory"])
def test_meta_paper_artifact_operations_reject_symlinked_run_ancestors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    step_id: str,
    link_level: str,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    paper_root = workspace / "paper"
    try:
        if link_level == "paper-root":
            paper_root.symlink_to(outside, target_is_directory=True)
        else:
            paper_root.mkdir()
            (paper_root / TEST_META_RUN_ID).symlink_to(
                outside,
                target_is_directory=True,
            )
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    monkeypatch.chdir(workspace)

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError):
        _run_paper_operation(step_id)

    assert list(outside.iterdir()) == []


def test_meta_paper_assemble_rejects_symlinked_section_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    sections = workspace / "paper" / TEST_META_RUN_ID / "sections"
    sections.mkdir(parents=True)
    outside = tmp_path / "outside.tex"
    original = "outside section content"
    outside.write_text(original, encoding="utf-8")
    try:
        (sections / "abstract.tex").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")
    monkeypatch.chdir(workspace)

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError):
        _run_paper_operation("assemble_manuscript_tex")

    assert outside.read_text(encoding="utf-8") == original


def test_meta_paper_persist_rejects_symlinked_section_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    sections = workspace / "paper" / TEST_META_RUN_ID / "sections"
    sections.mkdir(parents=True)
    outside = tmp_path / "outside.tex"
    original = "outside section content"
    outside.write_text(original, encoding="utf-8")
    try:
        (sections / "abstract.tex").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")
    monkeypatch.chdir(workspace)

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError, match="section path"):
        _run_paper_operation("persist_sections")

    assert outside.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("operation", ["citation_map", "compile_pdf"])
def test_meta_paper_artifact_runtime_rejects_manifest_paths_from_another_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    other_run = tmp_path / "paper" / "run-other"
    other_run.mkdir(parents=True)
    other_tex = other_run / "paper.tex"
    other_bib = other_run / "references.bib"
    other_tex.write_text(r"\documentclass{article}", encoding="utf-8")
    other_bib.write_text("@misc{other, title={Other}}", encoding="utf-8")
    manifest = (
        f"MANUSCRIPT_PATH: {other_tex.resolve()}\n"
        f"REFERENCES_PATH: {other_bib.resolve()}"
    )

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError, match="this meta run"):
        if operation == "citation_map":
            _run_paper_operation("citation_map", manifest=manifest)
        else:
            _run_paper_operation(
                "compile_pdf",
                manuscript_package=manifest,
                paper_contract="TARGET_PAGES: 1",
            )

    assert other_tex.read_text(encoding="utf-8") == r"\documentclass{article}"


def test_meta_compile_pdf_repairs_standard_algorithm_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "MANUSCRIPT_PKG",
        (
            "MANUSCRIPT_TEX:\n"
            "\\documentclass{article}\n"
            "\\usepackage{hyperref}\n"
            "\\begin{document}\n"
            "\\begin{algorithm}\n"
            "\\begin{algorithmic}\n"
            "\\STATE Fixture step\n"
            "\\end{algorithmic}\n"
            "\\end{algorithm}\n"
            "\\end{document}\n"
            "REFERENCES_BIB:\n"
            "% none\n"
        ),
    )
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 1\n",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_tex_run(calls, page_count=1))

    _run_paper_operation("compile_pdf")

    tex = (_paper_run_dir(tmp_path) / "paper.tex").read_text(encoding="utf-8")
    assert "\\usepackage{algorithm}" in tex
    assert "\\usepackage{algorithmic}" in tex
    assert "\\usepackage[hidelinks]{hyperref}" in tex
    assert "\\usepackage{hyperref}" not in tex
    assert tex.index("\\usepackage{algorithm}") < tex.index("\\begin{document}")
    assert tex.index("\\usepackage{algorithmic}") < tex.index("\\begin{document}")


@pytest.mark.parametrize("input_kind", ["absolute", "parent-relative"])
def test_tex_paranoid_open_policy_rejects_out_of_workspace_input(
    tmp_path: Path,
    input_kind: str,
) -> None:
    runtime_env = managed_skill_env(os.environ)
    xelatex = shutil.which("xelatex", path=runtime_env.get("PATH"))
    if xelatex is None:
        pytest.skip("xelatex is required for the live restricted-open contract")

    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    outside = tmp_path / "private.txt"
    private_text = "PRIVATE-CONTENT-MUST-NOT-ENTER-PDF"
    outside.write_text(private_text, encoding="utf-8")
    target = outside.resolve().as_posix() if input_kind == "absolute" else "../private.txt"
    (paper_dir / "paper.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        f"\\input{{{target}}}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    runtime_env.update(
        {
            "openin_any": "p",
            "openout_any": "p",
            "TEXINPUTS": f".{os.pathsep}",
            "BIBINPUTS": f".{os.pathsep}",
            "BSTINPUTS": f".{os.pathsep}",
        }
    )

    result = subprocess.run(
        [
            xelatex,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "paper.tex",
        ],
        cwd=paper_dir,
        capture_output=True,
        text=True,
        env=runtime_env,
        check=False,
        timeout=60,
    )

    assert result.returncode != 0
    assert not (paper_dir / "paper.pdf").exists()
    assert private_text not in result.stdout
    assert private_text not in result.stderr


def test_meta_compile_pdf_rejects_real_pdf_below_requested_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 3\n",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_tex_run(calls, page_count=2))

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError) as exc_info:
        _run_paper_operation("compile_pdf")
    assert len(PdfReader(_paper_run_dir(tmp_path) / "paper.pdf").pages) == 2
    error = str(exc_info.value)
    assert "PDF_PAGE_TARGET_NOT_MET" in error
    assert "requested at least 3 pages; compiled PDF has 2" in error
    assert "PDF_PATH:" not in error


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_meta_compile_pdf_checks_every_tex_command_return_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_at: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 3\n",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_tex_run(calls, page_count=3, fail_at=fail_at),
    )

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError) as exc_info:
        _run_paper_operation("compile_pdf")
    assert len(calls) == fail_at
    error = str(exc_info.value)
    assert "COMPILE_FAILED:" in error
    assert "status 17" in error
    assert "PDF_PATH:" not in error


def test_meta_compile_pdf_bounds_each_child_process_within_outer_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 1\n",
    )

    def time_out(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", time_out)

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError) as exc_info:
        _run_paper_operation("compile_pdf")

    assert "xelatex" in str(exc_info.value)
    assert "timed out within the 110-second compile budget" in str(exc_info.value)
    assert not (_paper_run_dir(tmp_path) / "paper.pdf").exists()


@pytest.mark.parametrize(
    "filename",
    ["paper.tex", "references.bib", "paper.pdf", "paper.aux", "paper.log"],
)
def test_meta_compile_pdf_refuses_paper_file_symlinks_without_unlinking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 1\n",
    )
    run_dir = _paper_run_dir(tmp_path)
    run_dir.mkdir(parents=True)
    outside = tmp_path / f"outside-{filename}"
    original = "must survive"
    outside.write_text(original, encoding="utf-8")
    try:
        (run_dir / filename).symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    def must_not_compile(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("TeX compiler must not run for a symlinked output")

    monkeypatch.setattr(subprocess, "run", must_not_compile)

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError, match="must not be symlinks"):
        _run_paper_operation("compile_pdf")

    assert (run_dir / filename).is_symlink()
    assert outside.read_text(encoding="utf-8") == original


def test_meta_compile_pdf_rejects_missing_glyph_warning_from_final_xelatex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 3\n",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_tex_run(
            calls,
            page_count=3,
            final_xelatex_output=(
                "Missing character: There is no ε (U+03B5) in font lmroman10-regular!"
            ),
        ),
    )

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError) as exc_info:
        _run_paper_operation("compile_pdf")
    error = str(exc_info.value)
    assert "COMPILE_FAILED: LATEX_OUTPUT_QUALITY_GATE" in error
    assert "LATEX_MISSING_GLYPHS: 1" in error
    assert "ε (U+03B5)" in error
    assert "PDF_PATH:" not in error


def test_meta_compile_pdf_rejects_severe_layout_overflow_from_final_xelatex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANUSCRIPT_PKG", _compile_fixture_package())
    monkeypatch.setenv(
        "PAPER_CONTRACT",
        "PAPER_MODE: FULL_MANUSCRIPT\nTARGET_PAGES: 3\n",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_tex_run(
            calls,
            page_count=3,
            final_xelatex_output=(
                r"Overfull \hbox (64.04889pt too wide) in paragraph at lines 10--20"
            ),
        ),
    )

    with pytest.raises(PAPER_ARTIFACT_RUNTIME.PaperArtifactError) as exc_info:
        _run_paper_operation("compile_pdf")
    error = str(exc_info.value)
    assert "COMPILE_FAILED: LATEX_OUTPUT_QUALITY_GATE" in error
    assert "LATEX_LAYOUT_OVERFLOW: max=64.05pt threshold=20.00pt" in error
    assert "PDF_PATH:" not in error
