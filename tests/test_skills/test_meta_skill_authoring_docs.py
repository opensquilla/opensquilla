from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOT_GUIDE = ROOT / "META_SKILL_GUIDE.md"
AUTHORING_DOC = ROOT / "src" / "opensquilla" / "skills" / "meta" / "META_SKILL_AUTHORING.md"
README = ROOT / "README.md"


def test_meta_skill_authoring_doc_contains_user_facing_contract() -> None:
    text = ROOT_GUIDE.read_text(encoding="utf-8")

    required_snippets = [
        "Meta-Skill User Guide and Templates",
        "Where to Put a Meta-Skill",
        "Basic Usage Flow",
        "metadata.opensquilla.risk",
        "metadata.opensquilla.capabilities",
        "kind: meta",
        "composition:",
        "llm_classify",
        "tool_call",
        "skill_exec",
        "final_text_mode",
        "xml_escape",
        "truncate",
        "Template: Minimal Read-Only Classifier",
        "Template: Parallel Review and Merge",
        "Template: Deterministic Tool Call",
        "Template: CLI-Backed Artifact Generation",
        "scripts/live_meta_soft_activation_e2e.py",
        "disable-model-invocation",
    ]
    for snippet in required_snippets:
        assert snippet in text


def test_meta_skill_authoring_doc_is_available_from_readme_and_package() -> None:
    root_text = ROOT_GUIDE.read_text(encoding="utf-8")
    package_text = AUTHORING_DOC.read_text(encoding="utf-8")
    readme_text = README.read_text(encoding="utf-8")

    assert package_text == root_text
    assert "META_SKILL_GUIDE.md" in readme_text
    assert "Meta-skills" in readme_text
