"""Compile a LaTeX paper with xelatex + bibtex; print the log tail."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tex_path")
    args = parser.parse_args()

    tex_path = Path(args.tex_path)
    if not tex_path.is_file():
        print(f"error: {tex_path} does not exist", file=sys.stderr)
        sys.exit(2)
    if shutil.which("xelatex") is None:
        print("error: xelatex not in PATH", file=sys.stderr)
        sys.exit(3)

    cwd = tex_path.parent
    stem = tex_path.stem
    passes = [
        ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
        ["bibtex", stem],
        ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
        ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
    ]
    full_log: list[str] = []
    for cmd in passes:
        rc, log = _run(cmd, cwd)
        full_log.append(f"--- {' '.join(cmd)} (rc={rc}) ---\n{log}")
        # xelatex returns 0 even on minor issues; only fail-hard on the
        # final pass.
        if rc != 0 and cmd[0] == "xelatex" and cmd is passes[-1]:
            print("\n".join(full_log[-3:]), file=sys.stderr)
            sys.exit(rc)

    pdf = cwd / f"{stem}.pdf"
    if not pdf.is_file():
        print("error: compile produced no PDF", file=sys.stderr)
        print("\n".join(full_log[-3:]), file=sys.stderr)
        sys.exit(4)

    # On success: emit a clean user-facing deliverable as stdout. The
    # full xelatex log tail is verbose and confusing in the chat surface
    # (overfull-hbox warnings, font info, page break trackers) — route it
    # to stderr where it survives in the gateway log for debugging
    # without becoming the meta-skill's final_text payload.
    log_tail = "\n".join("\n".join(full_log).splitlines()[-40:])
    print(log_tail, file=sys.stderr)
    try:
        size_kb = pdf.stat().st_size / 1024
        print(f"Paper compiled successfully: {pdf} ({size_kb:.1f} KB)")
    except OSError:
        print(f"Paper compiled successfully: {pdf}")


if __name__ == "__main__":
    main()
