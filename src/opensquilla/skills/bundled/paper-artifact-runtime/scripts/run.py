"""Cross-platform artifact operations for ``meta-paper-write``."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_SAFE_META_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SECTION_NAMES = (
    "abstract",
    "introduction",
    "related_work",
    "method",
    "experiments",
    "discussion",
    "conclusion",
)


class PaperArtifactError(RuntimeError):
    """Raised when an artifact operation fails its deterministic contract."""


def _text(payload: Mapping[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise PaperArtifactError(f"PAPER_ARTIFACT_RUNTIME_FAILED: {key} must be text")
    return value


def _validated_run_id(payload: Mapping[str, Any], prefix: str) -> str:
    run_id = _text(payload, "meta_run_id").strip()
    if _SAFE_META_RUN_ID_RE.fullmatch(run_id) is None:
        raise PaperArtifactError(f"{prefix}: invalid runtime-owned meta_run_id")
    return run_id


def _paper_run_dir(
    payload: Mapping[str, Any],
    *,
    prefix: str,
    create: bool,
) -> Path:
    run_id = _validated_run_id(payload, prefix)
    workspace = Path.cwd().resolve()
    paper_root = workspace / "paper"
    if paper_root.is_symlink():
        raise PaperArtifactError(f"{prefix}: paper root must not be a symlink")
    if create:
        paper_root.mkdir(exist_ok=True)
    if paper_root.exists() and (
        not paper_root.is_dir() or paper_root.resolve() != paper_root
    ):
        raise PaperArtifactError(f"{prefix}: paper root escaped the workspace")

    paper_dir = paper_root / run_id
    if paper_dir.is_symlink():
        raise PaperArtifactError(f"{prefix}: paper run directory must not be a symlink")
    if create:
        paper_dir.mkdir(exist_ok=True)
    if paper_dir.exists() and (
        not paper_dir.is_dir() or paper_dir.resolve() != paper_dir
    ):
        raise PaperArtifactError(f"{prefix}: paper run directory escaped the workspace")
    return paper_dir


def _clean_latex_fence(text: str, *, multiline: bool = False) -> str:
    flags = re.MULTILINE if multiline else 0
    text = re.sub(r"^```(?:latex|tex)?\s*\n", "", text, flags=flags)
    return re.sub(r"\n```\s*$", "", text).strip()


def _scrub_placeholder_table_cells(tex: str) -> str:
    """Scrub numeric-looking data cells from placeholder tables."""

    numeric = re.compile(
        r"^\s*(?:\\textbf\{)?[-+]?\d[\d,]*(?:\.\d+)?\s*"
        r"(?:%|ms|s|x|MB|GB|points?)?(?:\})?\s*$",
        re.IGNORECASE,
    )
    output: list[str] = []
    in_tabular = False
    after_midrule = False
    for line in tex.splitlines():
        if r"\begin{tabular}" in line:
            in_tabular = True
            after_midrule = False
            output.append(line)
            continue
        if in_tabular and r"\end{tabular}" in line:
            in_tabular = False
            after_midrule = False
            output.append(line)
            continue
        if in_tabular and r"\midrule" in line:
            after_midrule = True
            output.append(line)
            continue
        if in_tabular and after_midrule and "&" in line and r"\bottomrule" not in line:
            suffix = r" \\" if line.rstrip().endswith(r"\\") else ""
            row = line.rstrip()
            if suffix:
                row = row[:-2].rstrip()
            cells = [cell.strip() for cell in row.split("&")]
            if len(cells) > 1:
                cells = [
                    cells[0],
                    *("---" if numeric.match(cell) else cell for cell in cells[1:]),
                ]
                indent_match = re.match(r"^\s*", line)
                indent = indent_match.group(0) if indent_match else ""
                line = indent + " & ".join(cells) + suffix
        output.append(line)
    return "\n".join(output)


def persist_sections(payload: Mapping[str, Any]) -> str:
    """Persist generated section fragments and return a compact manifest."""

    paper_dir = _paper_run_dir(payload, prefix="PERSIST_SECTIONS_FAILED", create=True)
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, Mapping):
        raise PaperArtifactError("PERSIST_SECTIONS_FAILED: sections must be an object")
    sections = {name: _text(raw_sections, name) for name in _SECTION_NAMES}

    out_dir = paper_dir / "sections"
    if out_dir.is_symlink():
        raise PaperArtifactError(
            "PERSIST_SECTIONS_FAILED: sections directory must not be a symlink"
        )
    out_dir.mkdir(exist_ok=True)
    if not out_dir.is_dir() or out_dir.resolve() != out_dir:
        raise PaperArtifactError(
            "PERSIST_SECTIONS_FAILED: sections directory escaped the paper run"
        )

    lines = ["SECTION_ARTIFACTS:"]
    total = 0
    for name, text in sections.items():
        body = _clean_latex_fence(text, multiline=True)
        path = out_dir / f"{name}.tex"
        if path.is_symlink():
            raise PaperArtifactError(
                f"PERSIST_SECTIONS_FAILED: section path is a symlink: {name}"
            )
        path.write_text(body, encoding="utf-8")
        chars = len(body)
        total += chars
        first_line = next(
            (line.strip() for line in body.splitlines() if line.strip()),
            "",
        )
        lines.append(
            f"- {name}: path={path.as_posix()} chars={chars} "
            f"first_line={first_line[:120]!r}"
        )
    lines.extend(
        (
            f"TOTAL_SECTION_CHARS: {total}",
            "CONTEXT_POLICY: downstream steps must read section files from disk "
            "and pass only paths/summaries to LLM prompts",
        )
    )
    return "\n".join(lines)


def _latex_escape(text: str) -> str:
    text = text.replace("\\", r"\textbackslash{}")
    for character in "&%$#_{}":
        text = text.replace(character, "\\" + character)
    return text.replace("~", r"\textasciitilde{}").replace(
        "^", r"\textasciicircum{}"
    )


def assemble_manuscript_tex(payload: Mapping[str, Any]) -> str:
    """Assemble persisted section fragments into the run-owned manuscript."""

    paper_dir = _paper_run_dir(payload, prefix="ASSEMBLE_FAILED", create=True)
    section_dir = paper_dir / "sections"
    if (
        section_dir.is_symlink()
        or not section_dir.is_dir()
        or section_dir.resolve() != section_dir
    ):
        raise PaperArtifactError("ASSEMBLE_FAILED: sections directory escaped the paper run")
    sections = {name: section_dir / f"{name}.tex" for name in _SECTION_NAMES}
    if any(path.is_symlink() for path in sections.values()):
        raise PaperArtifactError("ASSEMBLE_FAILED: section files must not be symlinks")
    section_text = {
        name: path.read_text(encoding="utf-8") if path.is_file() else ""
        for name, path in sections.items()
    }

    bib = _text(payload, "bib_text").strip()
    writing_plan = _text(payload, "writing_plan")
    topic_fallback = _text(payload, "topic", "Untitled Manuscript")
    title_match = re.search(
        r"^\s*TITLE\s*:\s*(.+?)\s*$",
        writing_plan,
        re.MULTILINE,
    )
    raw_title = (
        title_match.group(1).strip() if title_match else topic_fallback
    ) or topic_fallback
    title_tex = _latex_escape(raw_title)
    any_cjk = re.search(r"[一-鿿]", raw_title) is not None or any(
        re.search(r"[一-鿿]", value) for value in section_text.values()
    )
    preamble = [
        r"\documentclass{article}",
        r"\usepackage{fontspec}" if any_cjk else r"% no CJK",
        r"\setmainfont[FontIndex=2]{NotoSansCJK-Regular.ttc}"
        if any_cjk
        else r"% no CJK font",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{amsmath,amssymb}",
        r"\usepackage{algorithm}",
        r"\usepackage{algorithmic}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\usepackage{geometry}",
        r"\geometry{margin=2.5cm}",
        r"\title{" + title_tex + r"}",
        r"\author{OpenSquilla meta-paper-write}",
        r"\date{\today}",
        r"\begin{document}",
        r"\maketitle",
    ]
    body_parts = [section_text[name] for name in _SECTION_NAMES]
    tail = [
        r"\bibliographystyle{plain}",
        r"\bibliography{references}",
        r"\end{document}",
    ]
    tex = (
        "\n".join(preamble)
        + "\n\n"
        + "\n\n".join(part for part in body_parts if part)
        + "\n\n"
        + "\n".join(tail)
    )
    tex = _scrub_placeholder_table_cells(tex)
    tex_path = paper_dir / "paper.tex"
    bib_path = paper_dir / "references.bib"
    if tex_path.is_symlink() or bib_path.is_symlink():
        raise PaperArtifactError("ASSEMBLE_FAILED: output files must not be symlinks")
    tex_path.write_text(tex, encoding="utf-8")
    bib_path.write_text(bib if bib else "% no verified references", encoding="utf-8")
    present = ", ".join(name for name, value in section_text.items() if value)
    return "\n".join(
        (
            f"MANUSCRIPT_PATH: {tex_path.resolve()}",
            f"REFERENCES_PATH: {bib_path.resolve()}",
            f"MANUSCRIPT_CHARS: {len(tex)}",
            f"REFERENCES_CHARS: {len(bib)}",
            "COMPILE_NOTES:",
            "- assembled section-by-section via paper-section-author",
            f"- sections present: {present}",
            f"- total section chars: {sum(len(value) for value in section_text.values())}",
            "- context policy: full manuscript persisted on disk; downstream prompts "
            "should use path/summary only",
        )
    )


def citation_map(payload: Mapping[str, Any]) -> str:
    """Build the deterministic citation provenance table from run artifacts."""

    run_dir = _paper_run_dir(payload, prefix="CITATION_MAP_FAILED", create=False)
    expected_tex = run_dir / "paper.tex"
    expected_bib = run_dir / "references.bib"
    if expected_tex.is_symlink() or expected_bib.is_symlink():
        raise PaperArtifactError("CITATION_MAP_FAILED: artifact files must not be symlinks")

    manifest = _text(payload, "manifest")
    manuscript_match = re.search(r"MANUSCRIPT_PATH:\s*(.+)", manifest)
    references_match = re.search(r"REFERENCES_PATH:\s*(.+)", manifest)
    tex_path = (
        Path(manuscript_match.group(1).strip()).resolve()
        if manuscript_match
        else expected_tex
    )
    bib_path = (
        Path(references_match.group(1).strip()).resolve()
        if references_match
        else expected_bib
    )
    if tex_path != expected_tex or bib_path != expected_bib:
        raise PaperArtifactError(
            "CITATION_MAP_FAILED: manifest path does not match this meta run"
        )

    tex = (
        tex_path.read_text(encoding="utf-8", errors="ignore")
        if tex_path.is_file()
        else ""
    )
    bib = (
        bib_path.read_text(encoding="utf-8", errors="ignore")
        if bib_path.is_file()
        else _text(payload, "refbib")
    )
    cite_counts: dict[str, int] = {}
    for group in re.findall(r"\\cite\{([^}]+)\}", tex):
        for key in (value.strip() for value in group.split(",")):
            if key:
                cite_counts[key] = cite_counts.get(key, 0) + 1

    entries: dict[str, dict[str, str]] = {}
    for match in re.finditer(
        r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n@\w+\s*\{|\Z)",
        bib,
        re.DOTALL,
    ):
        key = match.group(1).strip()
        body = match.group(2)
        title = re.search(r"title\s*=\s*[\{\"]([^}\"]+)", body, re.IGNORECASE)
        url = re.search(
            r"(?:url|howpublished)\s*=\s*[\{\"]([^}\"]+)",
            body,
            re.IGNORECASE,
        )
        doi = re.search(r"doi\s*=\s*[\{\"]([^}\"]+)", body, re.IGNORECASE)
        eprint = re.search(r"eprint\s*=\s*[\{\"]([^}\"]+)", body, re.IGNORECASE)
        locator = (url.group(1) if url else "")
        if not locator and doi:
            locator = f"doi:{doi.group(1)}"
        if not locator and eprint:
            locator = f"arXiv:{eprint.group(1)}"
        entries[key] = {
            "title": title.group(1).strip() if title else "",
            "locator": locator,
        }

    strong_domains = (
        "arxiv.org",
        "aclanthology.org",
        "dl.acm.org",
        "openreview.net",
        "ieee.org",
        "nature.com",
        "science.org",
        "biorxiv.org",
        "pnas.org",
    )
    weak_markers = (
        "medium.com",
        "wikipedia.org",
        "github.com",
        "stackoverflow.com",
        "twitter.com",
        "x.com",
    )

    def quality(locator: str, *, invalid: bool = False) -> str:
        lowered = locator.lower()
        if invalid:
            return "INVALID"
        if (
            any(domain in lowered for domain in strong_domains)
            or "doi:" in lowered
            or "arxiv:" in lowered
        ):
            return "STRONG"
        if any(marker in lowered for marker in weak_markers):
            return "WEAK"
        return "OK" if locator else "WEAK"

    lines = [
        "CITATION_MAP:",
        "",
        "| Cite Key | Cited Times | Title | URL / DOI / arXiv | Source Quality |",
        "|---|---:|---|---|---|",
    ]
    invalid = weak = strong = ok = unused = 0
    for key in sorted(set(cite_counts) | set(entries)):
        count = cite_counts.get(key, 0)
        entry = entries.get(key)
        invalid_row = entry is None
        source_quality = quality(
            entry["locator"] if entry else "",
            invalid=invalid_row,
        )
        if invalid_row:
            invalid += 1
        elif count == 0:
            unused += 1
            source_quality = "UNUSED"
        elif source_quality == "STRONG":
            strong += 1
        elif source_quality == "OK":
            ok += 1
        elif source_quality == "WEAK":
            weak += 1
        title = entry["title"] if entry else "(MISSING IN BIB)"
        locator = entry["locator"] if entry else "-"
        lines.append(f"| {key} | {count} | {title} | {locator} | {source_quality} |")
    lines.extend(
        (
            "",
            f"SUMMARY: total_cite_keys={len(cite_counts)}, strong={strong}, "
            f"ok={ok}, weak={weak}, invalid={invalid}, unused={unused}",
            f"ARTIFACTS: manuscript={tex_path} references={bib_path}",
        )
    )
    return "\n".join(lines)


def _extract_compile_inputs(
    payload: Mapping[str, Any],
    paper: Path,
) -> tuple[str, str, int]:
    package = _text(payload, "manuscript_package")
    paper_contract = _text(payload, "paper_contract")
    target_match = re.search(
        r"^\s*TARGET_PAGES\s*:\s*(\d+)\s*$",
        paper_contract,
        re.MULTILINE,
    )
    if not target_match:
        raise PaperArtifactError("COMPILE_FAILED: TARGET_PAGES missing from paper contract")
    target_pages = int(target_match.group(1))
    if not 1 <= target_pages <= 50:
        raise PaperArtifactError(
            f"COMPILE_FAILED: TARGET_PAGES must be between 1 and 50; got {target_pages}"
        )

    manuscript_match = re.search(
        r"MANUSCRIPT_TEX:\s*(.+?)(?:REFERENCES_BIB:|COMPILE_NOTES:|\Z)",
        package,
        re.DOTALL,
    )
    tex_body = manuscript_match.group(1).strip() if manuscript_match else ""
    bibliography_match = re.search(
        r"REFERENCES_BIB:\s*(.+?)(?:COMPILE_NOTES:|\Z)",
        package,
        re.DOTALL,
    )
    bibliography = bibliography_match.group(1).strip() if bibliography_match else ""

    if not tex_body:
        fenced = re.search(
            r"```(?:latex|tex)?\s*(\\documentclass[\s\S]+?\\end\{document\})",
            package,
        )
        if fenced:
            tex_body = fenced.group(1).strip()
    if not tex_body:
        raw = re.search(r"(\\documentclass[\s\S]+?\\end\{document\})", package)
        if raw:
            tex_body = raw.group(1).strip()

    expected_tex = paper / "paper.tex"
    expected_bib = paper / "references.bib"
    if not tex_body:
        path_match = re.search(r"MANUSCRIPT_PATH:\s*(.+)", package)
        bib_path_match = re.search(r"REFERENCES_PATH:\s*(.+)", package)
        if path_match:
            manuscript_path = Path(path_match.group(1).strip()).resolve()
            if manuscript_path != expected_tex:
                raise PaperArtifactError(
                    "COMPILE_FAILED: manuscript path does not match this meta run"
                )
            if manuscript_path.is_file():
                tex_body = manuscript_path.read_text(encoding="utf-8")
        if bib_path_match:
            bibliography_path = Path(bib_path_match.group(1).strip()).resolve()
            if bibliography_path != expected_bib:
                raise PaperArtifactError(
                    "COMPILE_FAILED: references path does not match this meta run"
                )
            if bibliography_path.is_file():
                bibliography = bibliography_path.read_text(encoding="utf-8")

    tex_body = _clean_latex_fence(tex_body)
    if not tex_body:
        raise PaperArtifactError(
            "COMPILE_FAILED: MANUSCRIPT_TEX block missing; refusing to create degraded PDF\n"
            f"PACKAGE_PREVIEW:\n{package[:2000]}"
        )
    return tex_body, bibliography, target_pages


def _prepare_tex(tex_body: str) -> str:
    if r"\documentclass" not in tex_body:
        tex_body = (
            r"\documentclass{article}"
            "\n"
            r"\usepackage{fontspec}"
            "\n"
            r"\setmainfont[FontIndex=2]{NotoSansCJK-Regular.ttc}"
            "\n"
            r"\usepackage{graphicx}\usepackage{booktabs}\usepackage{amsmath}"
            "\n"
            r"\usepackage{algorithm}\usepackage{algorithmic}"
            "\n"
            r"\usepackage[hidelinks]{hyperref}"
            "\n"
            r"\begin{document}"
            "\n"
            + tex_body
            + "\n"
            + r"\bibliographystyle{plain}"
            + "\n"
            + r"\bibliography{references}"
            + "\n"
            + r"\end{document}"
            + "\n"
        )

    tex_body = tex_body.replace(r"\usepackage{xeCJK}", r"\usepackage{fontspec}")
    tex_body = re.sub(
        r"\\setCJKmainfont\{[^}]+\}",
        r"\\setmainfont[FontIndex=2]{NotoSansCJK-Regular.ttc}",
        tex_body,
    )
    if re.search(r"[一-鿿]", tex_body) and "fontspec" not in tex_body:
        tex_body = tex_body.replace(
            r"\documentclass{article}",
            r"\documentclass{article}" + "\n" + r"\usepackage{fontspec}",
            1,
        )
    if re.search(r"[一-鿿]", tex_body) and "setmainfont" not in tex_body:
        tex_body = tex_body.replace(
            r"\usepackage{fontspec}",
            r"\usepackage{fontspec}"
            + "\n"
            + r"\setmainfont[FontIndex=2]{NotoSansCJK-Regular.ttc}",
            1,
        )
    tex_body = tex_body.replace(
        r"\usepackage{hyperref}",
        r"\usepackage[hidelinks]{hyperref}",
        1,
    )

    algorithm_packages: list[str] = []
    if r"\begin{algorithm}" in tex_body and r"\usepackage{algorithm}" not in tex_body:
        algorithm_packages.append(r"\usepackage{algorithm}")
    if (
        r"\begin{algorithmic}" in tex_body
        and r"\usepackage{algorithmic}" not in tex_body
        and r"\usepackage{algpseudocode}" not in tex_body
    ):
        legacy_commands = re.search(
            r"\\(?:STATE|FOR|FORALL|ENDFOR|IF|ELSE|ENDIF|WHILE|ENDWHILE|"
            r"REQUIRE|ENSURE)\b",
            tex_body,
        )
        algorithm_packages.append(
            r"\usepackage{algorithmic}"
            if legacy_commands
            else r"\usepackage{algpseudocode}"
        )
    if algorithm_packages:
        insertion = "\n".join(algorithm_packages) + "\n"
        begin_document = tex_body.find(r"\begin{document}")
        if begin_document < 0:
            raise PaperArtifactError(
                "COMPILE_FAILED: algorithm environment found but preamble is missing"
            )
        tex_body = tex_body[:begin_document] + insertion + tex_body[begin_document:]
    return _scrub_placeholder_table_cells(tex_body)


def _compile_commands(paper: Path) -> tuple[list[str], str]:
    logs: list[str] = []
    final_xelatex_output = ""
    compile_env = dict(os.environ)
    compile_env.update(
        {
            "openin_any": "p",
            "openout_any": "p",
            "TEXINPUTS": f".{os.pathsep}",
            "BIBINPUTS": f".{os.pathsep}",
            "BSTINPUTS": f".{os.pathsep}",
        }
    )
    commands = (
        [
            "xelatex",
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "paper.tex",
        ],
        ["bibtex", "paper"],
        [
            "xelatex",
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "paper.tex",
        ],
        [
            "xelatex",
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "paper.tex",
        ],
    )
    deadline = time.monotonic() + 110.0
    for command in commands:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PaperArtifactError(
                "COMPILE_FAILED: TeX command sequence exceeded the 110-second compile budget"
            )
        try:
            result = subprocess.run(  # noqa: S603 - fixed internal argv, no shell.
                command,
                cwd=paper,
                capture_output=True,
                text=True,
                env=compile_env,
                check=False,
                timeout=remaining,
            )
        except subprocess.TimeoutExpired as exc:
            raise PaperArtifactError(
                f"COMPILE_FAILED: {' '.join(command)} timed out within the "
                "110-second compile budget"
            ) from exc
        command_log = (
            f"--- {' '.join(command)} (rc={result.returncode}) ---\n"
            f"{result.stdout}\n{result.stderr}"
        )
        logs.append(command_log)
        if command[0] == "xelatex":
            final_xelatex_output = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0:
            raise PaperArtifactError(
                f"COMPILE_FAILED: {' '.join(command)} exited with "
                f"status {result.returncode}\n{'\n'.join(logs[-2:])}"
            )
    return logs, final_xelatex_output


def _validate_final_latex_quality(paper: Path, final_xelatex_output: str) -> None:
    paper_log = paper / "paper.log"
    if paper_log.is_symlink():
        raise PaperArtifactError("COMPILE_FAILED: paper output files must not be symlinks")
    final_quality_log = final_xelatex_output
    if paper_log.is_file():
        final_quality_log += "\n" + paper_log.read_text(
            encoding="utf-8",
            errors="replace",
        )
    missing_glyphs = sorted(
        set(re.findall(r"^Missing character:.*$", final_quality_log, re.MULTILINE))
    )
    overfull_points = [
        float(value)
        for value in re.findall(
            r"Overfull \\hbox \((\d+(?:\.\d+)?)pt too wide\)",
            final_quality_log,
        )
    ]
    severe_overfull = [value for value in overfull_points if value >= 20.0]
    unresolved = sorted(
        {
            line.strip()
            for line in final_quality_log.splitlines()
            if re.search(
                r"LaTeX Warning: (?:Citation|Reference) .+ undefined|"
                r"There were undefined references",
                line,
            )
        }
    )
    if not (missing_glyphs or severe_overfull or unresolved):
        return
    messages = ["COMPILE_FAILED: LATEX_OUTPUT_QUALITY_GATE"]
    if missing_glyphs:
        messages.extend(
            (f"LATEX_MISSING_GLYPHS: {len(missing_glyphs)}", *missing_glyphs[:20])
        )
    if severe_overfull:
        messages.append(
            "LATEX_LAYOUT_OVERFLOW: "
            f"max={max(severe_overfull):.2f}pt threshold=20.00pt"
        )
    if unresolved:
        messages.extend(
            (f"LATEX_UNRESOLVED_REFERENCES: {len(unresolved)}", *unresolved[:20])
        )
    raise PaperArtifactError("\n".join(messages))


def compile_pdf(payload: Mapping[str, Any]) -> str:
    """Compile and validate a real PDF using the managed TeX toolchain."""

    from pypdf import PdfReader

    paper = _paper_run_dir(payload, prefix="COMPILE_FAILED", create=True)
    expected_tex = paper / "paper.tex"
    expected_bib = paper / "references.bib"
    if expected_tex.is_symlink() or expected_bib.is_symlink():
        raise PaperArtifactError("COMPILE_FAILED: paper input/output files must not be symlinks")
    tex_body, bibliography, target_pages = _extract_compile_inputs(payload, paper)
    tex_body = _prepare_tex(tex_body)
    stale_paths = tuple(
        paper / f"paper{suffix}"
        for suffix in (".pdf", ".aux", ".bbl", ".blg", ".log", ".out", ".toc")
    )
    if any(path.is_symlink() for path in stale_paths):
        raise PaperArtifactError("COMPILE_FAILED: paper output files must not be symlinks")
    expected_tex.write_text(tex_body, encoding="utf-8")
    expected_bib.write_text(bibliography, encoding="utf-8")

    for path in stale_paths:
        path.unlink(missing_ok=True)
    logs, final_xelatex_output = _compile_commands(paper)
    _validate_final_latex_quality(paper, final_xelatex_output)

    pdf_path = paper / "paper.pdf"
    if pdf_path.is_symlink():
        raise PaperArtifactError("COMPILE_FAILED: paper output files must not be symlinks")
    pdf = pdf_path.resolve()
    if not pdf.is_file():
        log_text = (
            (paper / "paper.log").read_text(encoding="utf-8", errors="ignore")
            if (paper / "paper.log").is_file()
            else ""
        )
        log_tail = "\n".join(log_text.splitlines()[-80:])
        raise PaperArtifactError(
            f"COMPILE_FAILED:\n{'\n'.join(logs[-3:])}\n\n"
            f"=== paper.log tail ===\n{log_tail}"
        )
    try:
        pages = len(PdfReader(str(pdf)).pages)
    except Exception as exc:
        raise PaperArtifactError(
            f"COMPILE_FAILED: could not read generated PDF page count: {exc}"
        ) from exc
    if pages < target_pages:
        raise PaperArtifactError(
            "COMPILE_FAILED: PDF_PAGE_TARGET_NOT_MET: "
            f"requested at least {target_pages} pages; compiled PDF has {pages}"
        )
    return "\n".join(
        (
            f"PDF_PATH: {pdf}",
            f"PDF_PAGES: {pages}",
            f"PDF_TARGET_PAGES: {target_pages}",
            f"PDF_BYTES: {pdf.stat().st_size}",
            f"TEX_BYTES: {expected_tex.stat().st_size}",
            f"BIB_BYTES: {expected_bib.stat().st_size}",
        )
    )


_OPERATIONS: dict[str, Callable[[Mapping[str, Any]], str]] = {
    "persist_sections": persist_sections,
    "assemble_manuscript_tex": assemble_manuscript_tex,
    "citation_map": citation_map,
    "compile_pdf": compile_pdf,
}


def execute(payload: Mapping[str, Any]) -> str:
    """Execute the selected operation and return its text output contract."""

    operation = _text(payload, "operation").strip()
    handler = _OPERATIONS.get(operation)
    if handler is None:
        raise PaperArtifactError(
            "PAPER_ARTIFACT_RUNTIME_FAILED: operation must be one of "
            + ", ".join(sorted(_OPERATIONS))
        )
    return handler(payload)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, Mapping):
            raise PaperArtifactError("PAPER_ARTIFACT_RUNTIME_FAILED: payload must be an object")
        output = execute(payload)
    except (json.JSONDecodeError, PaperArtifactError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
