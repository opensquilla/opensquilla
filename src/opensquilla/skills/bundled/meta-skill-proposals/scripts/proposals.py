#!/usr/bin/env python3
"""meta-skill-proposals: write/list/show/accept/reject proposals."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from pathlib import Path


def _proposals_dir(home: Path) -> Path:
    return home / "proposals"


def _skills_dir(home: Path) -> Path:
    return home / "skills"


def _atomic_write_proposal(home: Path, skill_md: str, gates: dict) -> str:
    proposals = _proposals_dir(home)
    proposals.mkdir(parents=True, exist_ok=True)
    proposal_id = uuid.uuid4().hex[:8]

    tmp_parent = home / ".tmp"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tmp_parent) / f"proposal-{proposal_id}"
    tmp_dir.mkdir()
    (tmp_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (tmp_dir / "gates.json").write_text(json.dumps(gates, indent=2), encoding="utf-8")

    final_dir = proposals / proposal_id
    tmp_dir.rename(final_dir)
    return proposal_id


def cmd_write_proposal(args) -> dict:
    skill_md = args.skill_md_inline if args.skill_md_inline else Path(args.skill_md).read_text()
    lint_result = json.loads(args.lint_result)
    smoke_result = json.loads(args.smoke_result)
    eligible = (
        lint_result.get("G1", {}).get("passed", False)
        and lint_result.get("G2", {}).get("passed", False)
        and smoke_result.get("G3", {}).get("passed", False)
        and smoke_result.get("G4", {}).get("passed", False)
    )
    gates = {
        "lint": lint_result,
        "smoke": smoke_result,
        "auto_enable_eligible": eligible,
    }
    proposal_id = _atomic_write_proposal(Path(args.home), skill_md, gates)
    return {"status": "ok", "proposal_id": proposal_id,
            "auto_enable_eligible": eligible}


def cmd_list(args) -> dict:
    proposals = _proposals_dir(Path(args.home))
    if not proposals.is_dir():
        return {"proposals": []}
    rows: list[dict] = []
    for sub in sorted(proposals.iterdir()):
        if not (sub / "SKILL.md").is_file():
            continue
        gates_path = sub / "gates.json"
        gates = json.loads(gates_path.read_text()) if gates_path.is_file() else {}
        rows.append({
            "proposal_id": sub.name,
            "auto_enable_eligible": gates.get("auto_enable_eligible", False),
        })
    return {"proposals": rows}


def cmd_accept(args) -> dict:
    home = Path(args.home)
    src = _proposals_dir(home) / args.proposal_id
    if not (src / "SKILL.md").is_file():
        return {"status": "error", "reason": f"proposal {args.proposal_id} not found"}

    gates = json.loads((src / "gates.json").read_text()) if (src / "gates.json").is_file() else {}
    if not gates.get("auto_enable_eligible") and not args.force:
        return {"status": "refused",
                "reason": "gates not all passed; use --force to override",
                "gates": gates}

    skill_md = (src / "SKILL.md").read_text(encoding="utf-8")
    # NOTE: matches unquoted YAML names only (e.g. `name: foo-bar`). Quoted
    # names like `name: "foo-bar"` are not handled; current creator-emitted
    # templates use the unquoted form (see creator/patterns/p1_sequential.md.j2).
    name_match = re.search(r"^name:\s*([\w\-]+)\s*$", skill_md, re.MULTILINE)
    if not name_match:
        return {"status": "error", "reason": "cannot parse skill name from SKILL.md"}
    name = name_match.group(1)

    dst = _skills_dir(home) / name
    if dst.exists():
        return {"status": "refused", "reason": f"skill {name} already exists at {dst}"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))  # true move: proposal disappears from proposals/
    return {"status": "ok", "skill_path": str(dst), "name": name}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action", required=True, choices=["write_proposal", "list", "accept"])
    p.add_argument("--home", required=True)
    p.add_argument("--skill-md", default=None)
    p.add_argument("--skill-md-inline", default=None)
    p.add_argument("--lint-result", default="{}")
    p.add_argument("--smoke-result", default="{}")
    p.add_argument("--proposal-id", default=None)
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    dispatch = {"write_proposal": cmd_write_proposal, "list": cmd_list, "accept": cmd_accept}
    result = dispatch[args.action](args)
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
