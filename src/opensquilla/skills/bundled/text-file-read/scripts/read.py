#!/usr/bin/env python3
"""Read a UTF-8 text file and print its content to stdout.

Pairs with text-file-write to let a meta-skill round-trip an artefact
through disk between steps — useful when the user is allowed to hand-
edit the artefact during a review pause and the next step should
honour those edits rather than the in-context copy.

Usage:
    python read.py --input path/to/file.txt [--max-bytes 200000]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument(
        "--max-bytes", type=int, default=200_000,
        help="Refuse to read files larger than this many bytes.",
    )
    args = parser.parse_args()

    path = Path(args.input)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1

    size = path.stat().st_size
    if size > args.max_bytes:
        print(
            f"Error: file size {size} exceeds --max-bytes {args.max_bytes}: {path}",
            file=sys.stderr,
        )
        return 1

    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"Error: not valid UTF-8: {path} ({exc})", file=sys.stderr)
        return 1

    # Write through the binary buffer to bypass the Windows console
    # cp936 encoder — meta-skills capture stdout as bytes and decode
    # explicitly upstream.
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
