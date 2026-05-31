"""Convert multi-search-engine JSON (on stdin) into a BibTeX file.

Each search result becomes one ``@misc{}`` entry with the URL preserved
as ``howpublished``. When the URL pattern reveals a stronger identifier
the entry gains an extra structured field so downstream gates can audit
citation provenance:

* arxiv (abs / pdf URLs)               → ``eprint = {YYMM.NNNNN}``
* DOI URLs                              → ``doi = {10.xxxx/xxxxx}``
* OpenReview / ACL Anthology / ACM DL  → kept as ``howpublished`` only
  (no canonical IDs) but tagged via ``note = {source: <domain>}``

``note`` always records the source domain so the strict citation_map +
citation_integrity_gate steps in meta-paper-write can classify each
entry as STRONG / OK / WEAK without re-parsing the URL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

_BIB_UNSAFE = re.compile(r"[{}\\$&%#_~^]")

# arxiv abs/pdf — both with and without version suffix
_ARXIV_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?",
    re.IGNORECASE,
)
# arxiv legacy taxonomy (cs.LG/0312001)
_ARXIV_LEGACY_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(?P<id>[a-z\-]+/\d{7})", re.IGNORECASE,
)
_DOI_RE = re.compile(r"(?:doi\.org/|/doi/(?:abs/|full/|pdf/)?)"
                     r"(?P<doi>10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)


def _escape(text: str) -> str:
    return _BIB_UNSAFE.sub(lambda m: "\\" + m.group(0), text)


def _source_domain(url: str) -> str:
    """Return a normalised host string used by the citation gates."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _detect_identifiers(url: str) -> dict[str, str]:
    """Pull eprint / doi out of common paper URL shapes."""
    found: dict[str, str] = {}
    m = _ARXIV_RE.search(url)
    if m:
        found["eprint"] = m.group("id")
        found["archivePrefix"] = "arXiv"
        return found
    m = _ARXIV_LEGACY_RE.search(url)
    if m:
        found["eprint"] = m.group("id")
        found["archivePrefix"] = "arXiv"
        return found
    m = _DOI_RE.search(url)
    if m:
        # BibTeX doesn't escape DOIs the same way — keep the raw string.
        found["doi"] = m.group("doi")
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: stdin is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        print("error: payload.results missing or not a list", file=sys.stderr)
        sys.exit(2)

    entries: list[str] = []
    for idx, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        title = _escape(str(item.get("title", f"Untitled {idx}")))
        url = str(item.get("url", ""))
        snippet = _escape(str(item.get("snippet", "")))[:300]
        identifiers = _detect_identifiers(url)
        domain = _source_domain(url)

        # note field carries machine-readable provenance markers so the
        # downstream citation_map / citation_integrity_gate prompts can
        # classify each entry without re-fetching the URL.
        note_bits: list[str] = []
        if domain:
            note_bits.append(f"source: {domain}")
        if snippet:
            note_bits.append(snippet)
        note_field = "; ".join(note_bits)

        lines: list[str] = [
            f"@misc{{ref{idx},",
            f"  title = {{{title}}},",
            f"  howpublished = {{\\url{{{url}}}}},",
        ]
        if "doi" in identifiers:
            lines.append(f"  doi = {{{identifiers['doi']}}},")
        if "eprint" in identifiers:
            lines.append(f"  eprint = {{{identifiers['eprint']}}},")
            lines.append(
                f"  archivePrefix = {{{identifiers['archivePrefix']}}},"
            )
        if note_field:
            lines.append(f"  note = {{{note_field}}},")
        lines.append("  year = {2026}")
        lines.append("}")
        entries.append("\n".join(lines) + "\n")

    bib_text = "\n".join(entries)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(bib_text, encoding="utf-8")
    sys.stdout.write(bib_text)


if __name__ == "__main__":
    main()
