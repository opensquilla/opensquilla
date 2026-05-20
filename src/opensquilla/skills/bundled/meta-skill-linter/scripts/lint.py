#!/usr/bin/env python3
"""Meta-skill linter: G1 (static structural) + G2 (scheduler dry-run)."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import tempfile
from pathlib import Path

# Path from scripts dir: scripts→linter→bundled→skills→opensquilla→src→repo
# That's 6 parents. Verify by checking that REPO/src/opensquilla exists.
REPO = Path(__file__).resolve().parents[6]
# lint.py is invoked as a subprocess (uv run python scripts/lint.py ...)
# rather than imported as a module. opensquilla is not on sys.path in the
# subprocess until we add it here; the in-process test harness avoids this
# by using subprocess.run + --skill-md-stdin.
sys.path.insert(0, str(REPO / "src"))

# Redirect all logging to stderr before importing opensquilla modules so that
# structlog output does not contaminate the JSON written to stdout.
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

import structlog  # noqa: E402

structlog.configure(
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
)

from opensquilla.skills.loader import SkillLoader  # noqa: E402
from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan  # noqa: E402


BUNDLED = REPO / "src" / "opensquilla" / "skills" / "bundled"

# G1.6 xml_escape rule: any `{{ inputs.user_message ` literal must be
# IMMEDIATELY followed by `| xml_escape` as the first filter.
# The positive lookahead (?=[\s|}]) adds a word boundary so that fields
# with a user_message prefix (e.g. inputs.user_message_body) are not
# false-positively matched.
_XML_ESCAPE_RE = re.compile(r"\{\{\s*inputs\.user_message(?=[\s|}])(?!\s*\|\s*xml_escape)")


def _load_main_catalog() -> set[str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = SkillLoader(
            bundled_dir=BUNDLED,
            snapshot_path=Path(tmpdir) / "snapshot.json",
        )
        loader.invalidate_cache()
        return {spec.name for spec in loader.load_all()}


def run_g1(skill_md: str, catalog: set[str]) -> dict:
    diagnostics: list[str] = []

    # G1.6 xml_escape rule: only applicable to kind=meta skills (the meta-skill
    # DSL is where untrusted user_message flows through Jinja into prompts).
    # Non-meta skills escape at different layers and may use other filters.
    _is_meta = bool(re.search(r"^kind:\s*meta\b", skill_md, re.MULTILINE))
    if _is_meta and _XML_ESCAPE_RE.search(skill_md):
        diagnostics.append(
            "G1.6: every `{{ inputs.user_message ` must be immediately followed by `| xml_escape`"
        )

    # Rule G1.1: parse_meta_plan succeeds
    spec = None
    plan = None
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "synth"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        loader = SkillLoader(
            bundled_dir=Path(tmpdir),
            snapshot_path=Path(tmpdir) / "snap.json",
        )
        loader.invalidate_cache()
        try:
            specs = loader.load_all()
        except Exception as exc:
            diagnostics.append(f"G1.1 (loader): {type(exc).__name__}: {exc}")
            return {"passed": False, "diagnostics": diagnostics, "spec": None, "plan": None}
        if not specs:
            diagnostics.append("G1.1 (loader): no spec parsed; check YAML frontmatter")
            return {"passed": False, "diagnostics": diagnostics, "spec": None, "plan": None}
        spec = specs[0]
        try:
            plan = parse_meta_plan(spec)
        except MetaPlanError as exc:
            diagnostics.append(f"G1.1 (parse_meta_plan): {exc}")
            return {"passed": False, "diagnostics": diagnostics, "spec": spec, "plan": None}

    if plan is None:
        diagnostics.append("G1.1: parse_meta_plan returned None (kind != meta?)")
        return {"passed": False, "diagnostics": diagnostics, "spec": spec, "plan": None}

    # Rule G1.2: every step.skill exists in main catalog
    for step in plan.steps:
        if step.kind in ("agent", "skill_exec") and step.skill not in catalog:
            diagnostics.append(
                f"G1.2: step {step.id!r} references unknown skill {step.skill!r}"
            )

    passed = not diagnostics
    return {"passed": passed, "diagnostics": diagnostics, "spec": spec, "plan": plan}


def run_g2(plan, spec) -> dict:  # noqa: ANN001
    """Scheduler dry-run with stub executors."""
    from opensquilla.skills.meta.scheduler import run_dag

    diagnostics: list[str] = []

    # dispatch_step_stream(step, effective_skill, inputs, outputs)
    # yield_skill_view_preface(step_id, effective_skill)
    async def _stub_dispatch_step_stream(step, _effective_skill, _inputs, _outputs):
        from opensquilla.skills.meta.events import _StepDone
        yield _StepDone(text=f"<stub:{step.id}>")

    async def _stub_skill_view(_step_id, _effective_skill):
        return
        yield  # pragma: no cover — make it an async generator

    from opensquilla.skills.meta.types import MetaMatch
    match = MetaMatch(plan=plan, inputs={"user_message": "<test>"})

    try:
        async def _run() -> None:
            async for _ in run_dag(
                match,
                dispatch_step_stream=_stub_dispatch_step_stream,
                yield_skill_view_preface=_stub_skill_view,
            ):
                pass

        import asyncio
        asyncio.run(_run())
    except Exception as exc:
        diagnostics.append(f"G2 (scheduler dry-run): {type(exc).__name__}: {exc}")
        return {"passed": False, "diagnostics": diagnostics, "steps_visited": 0}

    return {"passed": True, "diagnostics": [], "steps_visited": len(plan.steps)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates", default="G1,G2")
    parser.add_argument("--skill-md", type=Path, default=None)
    parser.add_argument("--skill-md-stdin", action="store_true")
    args = parser.parse_args(argv)

    if args.skill_md_stdin:
        skill_md = sys.stdin.read()
    elif args.skill_md:
        skill_md = args.skill_md.read_text(encoding="utf-8")
    else:
        print("Need --skill-md or --skill-md-stdin", file=sys.stderr)
        return 2

    catalog = _load_main_catalog()
    gates = set(args.gates.split(","))
    out: dict = {}

    if "G1" in gates:
        g1 = run_g1(skill_md, catalog)
        out["G1"] = {"passed": g1["passed"], "diagnostics": g1["diagnostics"]}
        if not g1["passed"]:
            json.dump(out, sys.stdout)
            return 0
        plan = g1["plan"]
        spec = g1["spec"]
    else:
        plan = spec = None

    if "G2" in gates and plan is not None:
        g2 = run_g2(plan, spec)
        out["G2"] = {"passed": g2["passed"], "diagnostics": g2["diagnostics"]}

    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
