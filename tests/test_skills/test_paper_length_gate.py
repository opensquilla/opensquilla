"""Offline contracts for the artifact-backed paper length gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "src"
    / "opensquilla"
    / "skills"
    / "bundled"
    / "paper-length-gate"
    / "scripts"
    / "audit.py"
)


def _manuscript(*, repeats: int = 100, citations: bool = True) -> str:
    cite = r" \cite{ref1,ref2}" if citations else ""
    paragraph = (
        "This synthetic section explains assumptions, method boundaries, evaluation design, "
        "and reproducible limitations without claiming completed empirical results. "
        f"{cite}\n"
    )
    return "\n".join(
        [
            r"\documentclass{article}",
            r"\begin{document}",
            r"\begin{abstract}A synthetic readiness fixture.\end{abstract}",
            r"\section{Introduction}",
            paragraph * repeats,
            r"\section{Related Work}",
            paragraph,
            r"\section{Method}",
            paragraph,
            r"\section{Experiments}",
            paragraph,
            r"\section{Discussion}",
            paragraph,
            r"\section{Conclusion}",
            paragraph,
            r"\bibliography{references}",
            r"\end{document}",
        ]
    )


def _payload(path: str, *, pages: str = "8", mode: str = "FULL_MANUSCRIPT") -> dict[str, str]:
    return {
        "paper_contract": f"PAPER_MODE: {mode}\nTARGET_PAGES: {pages}",
        "manuscript_package": (
            f"MANUSCRIPT_PATH: {path}\n"
            "CONTEXT_POLICY: artifact-only; full manuscript omitted from prompt/output"
        ),
    }


def _run(payload: dict[str, str], workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        cwd=workspace,
    )


def test_length_gate_reads_artifact_only_manifest_without_blocking(tmp_path: Path) -> None:
    paper = tmp_path / "paper" / "paper.tex"
    paper.parent.mkdir()
    paper.write_text(_manuscript(), encoding="utf-8")

    result = _run(_payload(str(paper), pages="8"), tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LENGTH_GATE: warn" in result.stdout
    assert "TARGET_PAGES: 8" in result.stdout
    assert "PAGE_COUNT_AUTHORITY: compile_pdf/pypdf" in result.stdout
    assert "REQUIRED_SECTIONS: 7/7" in result.stdout
    assert "DISTINCT_CITE_KEYS: 2" in result.stdout
    assert "CONTEXT_POLICY" not in result.stdout


def test_length_gate_rejects_workspace_escape_and_non_tex_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-paper.txt"
    outside.write_text(_manuscript(), encoding="utf-8")

    result = _run(_payload(str(outside)), tmp_path)

    assert result.returncode != 0
    assert "LENGTH_GATE: block" in result.stdout
    assert "escapes the active workspace" in result.stdout
    assert "must reference a .tex file" in result.stdout
    assert "escapes the active workspace" in result.stderr


def test_length_gate_rejects_missing_empty_and_non_tex_artifacts(tmp_path: Path) -> None:
    empty = tmp_path / "empty.tex"
    empty.write_text("", encoding="utf-8")
    not_tex = tmp_path / "paper.md"
    not_tex.write_text(_manuscript(), encoding="utf-8")

    missing_result = _run(_payload("paper/missing.tex"), tmp_path)
    empty_result = _run(_payload(str(empty)), tmp_path)
    non_tex_result = _run(_payload(str(not_tex)), tmp_path)

    assert missing_result.returncode != 0
    assert "cannot be resolved" in missing_result.stdout
    assert empty_result.returncode != 0
    assert "manuscript .tex file is empty" in empty_result.stdout
    assert non_tex_result.returncode != 0
    assert "MANUSCRIPT_PATH must reference a .tex file" in non_tex_result.stdout


def test_length_gate_blocks_missing_sections_small_body_and_citations(tmp_path: Path) -> None:
    paper = tmp_path / "short.tex"
    paper.write_text(
        r"\documentclass{article}\begin{document}\section{Introduction}Tiny.\end{document}",
        encoding="utf-8",
    )

    result = _run(_payload(str(paper), pages="10"), tmp_path)

    assert result.returncode != 0
    assert "required section missing: abstract" in result.stdout
    assert "required section missing: conclusion" in result.stdout
    assert "manuscript contains no LaTeX citation keys" in result.stdout
    assert "manuscript body is below readiness floor" in result.stdout


def test_length_gate_rejects_missing_or_out_of_range_page_target(tmp_path: Path) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(_manuscript(), encoding="utf-8")

    missing = _run(
        {
            "paper_contract": "PAPER_MODE: FULL_MANUSCRIPT",
            "manuscript_package": f"MANUSCRIPT_PATH: {paper}",
        },
        tmp_path,
    )
    out_of_range = _run(_payload(str(paper), pages="51"), tmp_path)

    assert missing.returncode != 0
    assert "TARGET_PAGES must be a machine-readable integer" in missing.stdout
    assert out_of_range.returncode != 0
    assert "TARGET_PAGES must be between 1 and 50" in out_of_range.stdout


def test_length_gate_rejects_modes_outside_the_public_contract(tmp_path: Path) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(_manuscript(), encoding="utf-8")

    result = _run(_payload(str(paper), mode="LEGACY_MODE"), tmp_path)

    assert result.returncode != 0
    assert "PAPER_MODE must be FULL_MANUSCRIPT or COMPACT_SKELETON" in result.stdout


def test_length_gate_keeps_inline_compact_package_compatible(tmp_path: Path) -> None:
    manuscript = _manuscript(repeats=30)
    payload = {
        "paper_contract": "PAPER_MODE: COMPACT_SKELETON\nTARGET_PAGES: 4",
        "manuscript_package": f"MANUSCRIPT_TEX:\n{manuscript}\nREFERENCES_BIB:\n",
    }

    result = _run(payload, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LENGTH_GATE: warn" in result.stdout
    assert "inline manuscript compatibility path used" in result.stdout
    assert "MANUSCRIPT_SOURCE: inline:MANUSCRIPT_TEX" in result.stdout
