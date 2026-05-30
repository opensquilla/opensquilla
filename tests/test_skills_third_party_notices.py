from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
ORIGINALS = {
    "cron",
    "deep-research",
    "docx",
    "git-diff",
    "github",
    "history-explorer",
    "html-to-pdf",
    "http-fetch",
    "latex-compile",
    "memory",
    "meta-account-watch",
    "meta-daily-operator-brief",
    "meta-document-to-decision",
    "meta-family-day-coordinator",
    "meta-job-search-pipeline",
    "meta-kid-project-planner",
    "meta-paper-write",
    "meta-safe-skill-installer",
    "meta-skill-creator",
    "meta-web-research-to-report",
    "multi-search-engine",
    "nano-pdf",
    "paper-abstract-author",
    "paper-citation-planner",
    "paper-experiment-stub",
    "paper-outline-author",
    "paper-plot-stub",
    "paper-preference-planner",
    "paper-refbib-stub",
    "paper-revision-author",
    "paper-section-author",
    "paper-source-curator",
    "pdf-toolkit",
    "pptx",
    "skill-creator",
    "skill-creator-linter",
    "skill-creator-proposals",
    "skill-creator-smoke-test",
    "stack-trace-generic-probe",
    "stack-trace-go-probe",
    "stack-trace-js-probe",
    "stack-trace-python-probe",
    "stack-trace-rust-probe",
    "sub-agent",
    "summarize",
    "tmux",
    "weather",
    "xlsx",
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
            "bundled-derived",
            "openclaw-derived",
            "clawhub-mit0",
        }, skill.name
        assert provenance.maintained_by == "OpenSquilla", skill.name
        if provenance.origin == "bundled-derived":
            assert provenance.upstream_url == "https://github.com/bundled/bundled"
            assert provenance.license == "MIT", skill.name
        elif provenance.origin == "openclaw-derived":
            assert provenance.upstream_url == "https://github.com/openclaw/openclaw", skill.name
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
    derived = sorted(name for name, origin in skills.items() if origin == "bundled-derived")
    originals = sorted(name for name, origin in skills.items() if origin == "opensquilla-original")
    openclaw_derived = sorted(
        name for name, origin in skills.items() if origin == "openclaw-derived"
    )
    clawhub_derived = sorted(name for name, origin in skills.items() if origin == "clawhub-mit0")

    assert "## OpenClaw-derived bundled skill descriptors" in text
    assert "## OpenSquilla-original bundled skills" in text
    if clawhub_derived:
        assert "## ClawHub-derived bundled skill descriptors" in text
    for name in derived:
        assert f"- `{name}`" in text
    for name in originals:
        assert f"- `{name}`" in text
    for name in openclaw_derived:
        assert f"- `{name}`" in text
    for name in clawhub_derived:
        assert f"- `{name}`" in text

    listed = {
        line.strip()[3:-1]
        for line in text.splitlines()
        if line.strip().startswith("- `") and line.strip().endswith("`")
    }
    assert listed == set(skills)


def test_tokenjuice_backend_has_third_party_provenance() -> None:
    text = NOTICES.read_text(encoding="utf-8")
    package_dir = ROOT / "src" / "opensquilla" / "plugins" / "tokenjuice"
    provenance = package_dir / "PROVENANCE.md"
    license_file = package_dir / "LICENSE.tokenjuice"

    assert provenance.is_file()
    assert license_file.is_file()

    provenance_text = provenance.read_text(encoding="utf-8")
    license_text = license_file.read_text(encoding="utf-8")

    assert "## tokenjuice adapted reduction rules" in text
    assert "https://github.com/vincentkoc/tokenjuice" in text
    assert "License: MIT" in text
    assert "Copyright (c) 2026 Vincent Koc" in text
    assert "adaptation" in text
    assert "LICENSE.tokenjuice" in text

    assert "https://github.com/vincentkoc/tokenjuice" in provenance_text
    assert "bundled JSON reduction rules are derived" in provenance_text
    assert "MIT License" in license_text
    assert "Copyright (c) 2026 Vincent Koc" in license_text
