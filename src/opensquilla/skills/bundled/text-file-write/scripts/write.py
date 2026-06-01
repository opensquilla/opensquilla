#!/usr/bin/env python3
"""Write stdin to a UTF-8 file.

Used by meta-skills that need to persist an LLM-produced text blob to
the workspace (e.g. saving a generated script or contract) without
inventing a full skill_exec wrapper per use case.

Usage:
    cat my-text | python write.py --output path/to/file.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument(
        "--mode", default="w", choices=["w", "a"],
        help="w = overwrite (default), a = append.",
    )
    args = parser.parse_args()

    text = sys.stdin.read()
    if not text:
        print("Error: stdin was empty.", file=sys.stderr)
        return 1

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open(args.mode, encoding="utf-8") as f:
        f.write(text)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
