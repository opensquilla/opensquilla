from __future__ import annotations

import mimetypes
import re
import time
from hashlib import sha256
from pathlib import Path

from opensquilla.knowledge.chunking import (
    chunker_candidates,
    count_markdown_headings,
    detect_language_bucket,
)
from opensquilla.knowledge.models import DocumentProfile, ProcessingPlan, SourceFileRecord
from opensquilla.knowledge.parsers import (
    content_sha256,
    parse_document,
    parser_candidates_for_suffix,
)

ANALYZER_VERSION = "knowledge-analyzer-p0-v1"
DEFAULT_INDEX_PROFILES = ["sqlite_fts5_default"]


def make_collection_id(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return clean[:64] or "default"


def make_stable_id(prefix: str, *parts: str, length: int = 24) -> str:
    digest = sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def analyze_source_file(
    path: Path,
    *,
    root: Path,
    collection_id: str,
    snapshot_id: str,
) -> tuple[SourceFileRecord, DocumentProfile]:
    now = int(time.time() * 1000)
    sha = content_sha256(path)
    relative = _relative_to(path, root)
    suffix = path.suffix.lower()
    source_file = SourceFileRecord(
        source_file_id=make_stable_id("sf", collection_id, str(relative), sha),
        collection_id=collection_id,
        snapshot_id=snapshot_id,
        source_path=str(relative),
        absolute_path=str(path),
        file_name=path.name,
        extension=suffix,
        size_bytes=path.stat().st_size,
        content_sha256=sha,
        status="analyzed",
        discovered_at=now,
        metadata={"root": str(root)},
    )
    parser_candidates = parser_candidates_for_suffix(suffix)
    text_sample = _read_text_sample(path, suffix)
    language = detect_language_bucket(text_sample or path.name)
    heading_count = count_markdown_headings(text_sample)
    chunk_candidates = chunker_candidates(text_sample, suffix=suffix)
    profile = DocumentProfile(
        profile_id=make_stable_id("prof", source_file.source_file_id, sha),
        source_file_id=source_file.source_file_id,
        collection_id=collection_id,
        mime_type=_guess_mime_type(path),
        encoding="utf-8" if suffix in {".md", ".markdown", ".txt", ".html", ".htm"} else None,
        language_bucket=language,
        text_quality=_estimate_text_quality(text_sample, suffix=suffix),
        structure_kind=_structure_kind(suffix, text_sample),
        estimated_chars=len(text_sample),
        page_count=None,
        has_frontmatter=text_sample.lstrip().startswith("---"),
        heading_count=heading_count,
        parser_candidates=parser_candidates,
        chunker_candidates=chunk_candidates,
        metadata={
            "suffix": suffix,
            "sampleChars": len(text_sample),
            "sampleOnly": suffix == ".pdf",
        },
    )
    return source_file, profile


def build_processing_plan(
    source_file: SourceFileRecord,
    profile: DocumentProfile,
    *,
    index_profiles: list[str] | None = None,
) -> ProcessingPlan:
    parser = profile.parser_candidates[0] if profile.parser_candidates else "unsupported"
    chunker = _select_chunker(profile)
    profiles = index_profiles or DEFAULT_INDEX_PROFILES
    steps = [
        {
            "step": "preprocess",
            "strategy": parser,
            "input": source_file.source_path,
            "output": "normalized_text_artifact",
            "reversible": True,
        },
        {
            "step": "chunk",
            "strategy": chunker,
            "input": "normalized_text_artifact",
            "output": "chunks",
            "reversible": True,
            "params": {"targetChars": 1200, "overlapChars": 120},
        },
        {
            "step": "index",
            "strategy": ",".join(profiles),
            "input": "chunks",
            "output": "index_catalog",
            "reversible": False,
        },
    ]
    return ProcessingPlan(
        plan_id=make_stable_id("plan", source_file.source_file_id, parser, chunker),
        source_file_id=source_file.source_file_id,
        collection_id=source_file.collection_id,
        analyzer_version=ANALYZER_VERSION,
        preprocessor_strategy=parser,
        chunking_strategy=chunker,
        index_profiles=profiles,
        steps=steps,
        status="planned" if parser != "unsupported" else "unsupported",
        created_at=int(time.time() * 1000),
        metadata={"profileId": profile.profile_id},
    )


def parse_with_plan(path: Path, plan: ProcessingPlan):
    if plan.preprocessor_strategy == "unsupported":
        raise ValueError(f"Unsupported knowledge file type: {path.suffix or '<none>'}")
    return parse_document(path, strategy=plan.preprocessor_strategy)


def _select_chunker(profile: DocumentProfile) -> str:
    if profile.structure_kind == "markdown_headed":
        return "markdown_heading_v1"
    if profile.structure_kind == "plain_text":
        return "paragraph_window_v1"
    if profile.structure_kind in {"html", "pdf"}:
        return "paragraph_window_v1"
    return profile.chunker_candidates[0] if profile.chunker_candidates else "paragraph_window_v1"


def _relative_to(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return Path(path.name)


def _guess_mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _read_text_sample(path: Path, suffix: str) -> str:
    if suffix == ".pdf":
        return path.stem
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return raw[:20000]


def _estimate_text_quality(sample: str, *, suffix: str) -> str:
    if suffix == ".pdf":
        return "unknown_until_parse"
    stripped = sample.strip()
    if not stripped:
        return "empty"
    replacement_rate = stripped.count("\ufffd") / max(len(stripped), 1)
    if replacement_rate > 0.02:
        return "encoding_lossy"
    if len(stripped) < 80:
        return "short"
    return "normal"


def _structure_kind(suffix: str, sample: str) -> str:
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".pdf":
        return "pdf"
    if count_markdown_headings(sample) > 0:
        return "markdown_headed"
    return "plain_text"
