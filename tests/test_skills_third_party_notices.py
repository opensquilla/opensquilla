from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
ORIGINALS = {
    "history-explorer",
    "latex-compile",
    "memory",
    "meta-compliance-audit-bundle",
    "meta-github-pr-watch-digest",
    "meta-issue-to-pr-autopilot",
    "meta-knowledge-base-bootstrap",
    "meta-long-running-build-watchdog",
    "meta-migration-assistant",
    "meta-multi-format-export-pack",
    "meta-paper-write",
    "meta-pdf-intelligence",
    "meta-pdf-reformat-pipeline",
    "meta-research-to-deck",
    "meta-scheduled-morning-digest",
    "meta-security-review-bundle",
    "meta-skill-linter",
    "meta-skill-smoke-test",
    "meta-self-improving-skill-factory",
    "meta-spreadsheet-insight",
    "meta-travel-planner",
    "meta-web-research-to-report",
    "meta-web-to-pdf-briefing",
    "paper-experiment-stub",
    "paper-outline-author",
    "paper-plot-stub",
    "paper-refbib-stub",
    "paper-section-author",
}


def test_all_bundled_skills_have_complete_provenance(tmp_path: Path) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    skills = sorted(loader.load_all(), key=lambda skill: skill.name)
    skill_dirs = [
        path for path in BUNDLED.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()
    ]

    assert len(skills) == len(skill_dirs)
    for skill in skills:
        provenance = skill.provenance
        assert provenance.origin in {
            "opensquilla-original",
            "openclaw-derived",
            "clawhub-mit0",
        }, skill.name
        assert provenance.maintained_by == "OpenSquilla", skill.name
        if provenance.origin == "openclaw-derived":
            assert provenance.upstream_url == "https://github.com/openclaw/openclaw"
            assert provenance.license == "MIT", skill.name
        elif provenance.origin == "clawhub-mit0":
            assert provenance.upstream_url.startswith("https://clawhub.ai/"), skill.name
            assert provenance.license == "MIT-0", skill.name
        else:
            assert skill.name in ORIGINALS
            assert provenance.license == "Apache-2.0", skill.name


def test_third_party_notices_match_bundled_provenance(tmp_path: Path) -> None:
    text = NOTICES.read_text(encoding="utf-8")
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    skills = {skill.name: skill.provenance.origin for skill in loader.load_all()}
    derived = sorted(name for name, origin in skills.items() if origin == "openclaw-derived")
    originals = sorted(name for name, origin in skills.items() if origin == "opensquilla-original")

    clawhub_derived = sorted(name for name, origin in skills.items() if origin == "clawhub-mit0")

    assert "## OpenClaw-derived bundled skill descriptors" in text
    assert "## OpenSquilla-original bundled skills" in text
    if clawhub_derived:
        assert "## ClawHub-derived bundled skill descriptors" in text
    for name in derived:
        assert f"- `{name}`" in text
    for name in originals:
        assert f"- `{name}`" in text
    for name in clawhub_derived:
        assert f"- `{name}`" in text

    listed = {
        line.strip()[3:-1]
        for line in text.splitlines()
        if line.strip().startswith("- `") and line.strip().endswith("`")
    }
    assert listed == set(skills)
