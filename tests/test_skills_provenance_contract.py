from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "opensquilla" / "skills" / "bundled"
DEFAULTS = {"skill-creator", "pptx", "memory", "cron", "github"}


def test_default_bundled_skills_have_release_provenance(tmp_path: Path) -> None:
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snapshot.json")
    skills = {skill.name: skill for skill in loader.load_all()}

    for name in DEFAULTS:
        provenance = skills[name].provenance
        assert provenance.origin in {
            "opensquilla-original",
            "openclaw-derived",
            "clawhub-mit0",
        }
        assert provenance.maintained_by == "OpenSquilla"
        if provenance.origin == "openclaw-derived":
            assert provenance.upstream_url.startswith("https://")
            assert provenance.license == "MIT"
        elif provenance.origin == "clawhub-mit0":
            assert provenance.upstream_url.startswith("https://clawhub.ai/")
            assert provenance.license == "MIT-0"
        else:
            assert provenance.license == "Apache-2.0"


def test_provenance_survives_snapshot_roundtrip(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=snapshot)
    first = {skill.name: skill.provenance for skill in loader.load_all()}
    loader.save_snapshot()

    reloaded = SkillLoader(bundled_dir=BUNDLED, snapshot_path=snapshot)
    second = {skill.name: skill.provenance for skill in reloaded.load_all()}

    for name in DEFAULTS:
        assert second[name] == first[name]


def test_entrypoint_manifest_survives_snapshot_roundtrip(tmp_path: Path) -> None:
    """skill_exec depends on the entrypoint manifest surviving the snapshot
    cache — a gateway cold-start that loads from snapshot must see the same
    entrypoint dict as a fresh frontmatter parse."""

    snapshot = tmp_path / "snapshot.json"
    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=snapshot)
    fresh = {skill.name: skill.entrypoint for skill in loader.load_all()}
    loader.save_snapshot()

    reloaded = SkillLoader(bundled_dir=BUNDLED, snapshot_path=snapshot)
    from_snapshot = {skill.name: skill.entrypoint for skill in reloaded.load_all()}

    # multi-search-engine is the canonical skill_exec target — its entrypoint
    # must round-trip intact.
    assert fresh["multi-search-engine"] is not None
    assert fresh["multi-search-engine"] == from_snapshot["multi-search-engine"]
    assert "command" in fresh["multi-search-engine"]
    # Skills without an entrypoint manifest should still round-trip as None.
    for name, ep in fresh.items():
        assert from_snapshot[name] == ep, f"entrypoint mismatch for {name}"
