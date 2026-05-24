from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTHORING_DOC = ROOT / "src" / "opensquilla" / "skills" / "meta" / "META_SKILL_AUTHORING.md"


def test_meta_skill_authoring_doc_contains_user_facing_contract() -> None:
    text = AUTHORING_DOC.read_text(encoding="utf-8")

    required_snippets = [
        "metadata.opensquilla.risk",
        "metadata.opensquilla.capabilities",
        "kind: meta",
        "composition:",
        "llm_classify",
        "skill_exec",
        "xml_escape",
        "truncate",
        "scripts/live_meta_soft_activation_e2e.py",
        "Example: history-summary",
    ]
    for snippet in required_snippets:
        assert snippet in text
