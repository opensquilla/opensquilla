from __future__ import annotations

from pathlib import Path

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.trigger_accuracy import (
    TriggerCase,
    evaluate_trigger_cases,
)


def _write_meta_skill(root: Path, name: str, trigger: str, priority: int) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"""---
name: {name}
description: "Trigger accuracy fixture for {name}"
kind: meta
meta_priority: {priority}
triggers:
  - "{trigger}"
composition:
  steps:
    - id: classify
      kind: llm_classify
      output_choices: ["YES", "NO"]
      with:
        prompt: "{{{{ inputs.user_message | xml_escape }}}}"
---
""",
        encoding="utf-8",
    )


def test_trigger_accuracy_reports_hits_misses_and_false_positives(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_meta_skill(skills_dir, "meta-alpha", "alpha report", 80)
    _write_meta_skill(skills_dir, "meta-beta", "beta digest", 50)
    loader = SkillLoader(bundled_dir=skills_dir, snapshot_path=tmp_path / "snapshot.json")
    loader.invalidate_cache()

    report = evaluate_trigger_cases(
        loader,
        [
            TriggerCase(
                name="true-positive",
                user_message="Please build the alpha report today",
                expected_meta_skill="meta-alpha",
            ),
            TriggerCase(
                name="expected-none",
                user_message="Just chat normally",
                expected_meta_skill=None,
            ),
            TriggerCase(
                name="false-positive",
                user_message="Please build the beta digest",
                expected_meta_skill=None,
            ),
        ],
    )

    assert report["total"] == 3
    assert report["passed"] == 2
    assert report["failed"] == 1
    assert report["false_positives"] == 1
    assert report["cases"][0]["predicted_meta_skill"] == "meta-alpha"
    assert report["cases"][2]["passed"] is False
    assert report["cases"][2]["candidates"][0]["name"] == "meta-beta"
