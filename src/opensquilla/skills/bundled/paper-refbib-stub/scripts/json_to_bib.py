"""Convert multi-search-engine JSON (on stdin) into a BibTeX file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_BIB_UNSAFE = re.compile(r"[{}\\$&%#_~^]")


def _escape(text: str) -> str:
    return _BIB_UNSAFE.sub(lambda m: "\\" + m.group(0), text)


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
        entry = (
            f"@misc{{ref{idx},\n"
            f"  title = {{{title}}},\n"
            f"  howpublished = {{\\url{{{url}}}}},\n"
            f"  note = {{{snippet}}},\n"
            f"  year = {{2026}}\n"
            f"}}\n"
        )
        entries.append(entry)

    bib_text = "\n".join(entries)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(bib_text, encoding="utf-8")
    sys.stdout.write(bib_text)


if __name__ == "__main__":
    main()
