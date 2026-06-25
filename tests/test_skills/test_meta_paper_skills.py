"""Offline unit tests for the meta-paper-write bundled scripts.

Each test runs the wrapped CLI directly via subprocess, no LLM, no
orchestrator. The point is to catch syntax bugs and confirm the
contract (output files exist + look right) so the meta-skill
composition can rely on them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
EXP = ROOT / "src" / "opensquilla" / "skills" / "exp"


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
    assert "site:arxiv.org" in meta  # academic-site bias on search query
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


def test_meta_paper_write_plans_user_requested_page_target_up_front() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")

    assert "TARGET_PAGES:" in meta
    assert "This writing plan is the length-control point" in meta
    assert "allocating enough section scope" in meta
    assert "minimum total target_words" in meta
    assert "PER_SECTION_BLUEPRINT.*.target_words" in meta
    assert "target_words from writing_plan" in meta
    assert "PDF_PAGE_TARGET_NOT_MET" not in meta
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


def test_meta_paper_write_scrubs_numeric_table_cells_before_compile() -> None:
    meta = (BUNDLED / "meta-paper-write" / "SKILL.md").read_text(encoding="utf-8")

    assert "def scrub_placeholder_table_cells" in meta
    assert "Scrub numeric-looking data cells" in meta
    assert "tex = scrub_placeholder_table_cells(tex)" in meta
    assert "tex_body = scrub_placeholder_table_cells(tex_body)" in meta
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
