"""3 个高频 meta-skill 的 step 都声明 label。"""

from pathlib import Path

import pytest
import yaml

HIGH_FREQ = [
    "meta-document-to-decision",
    "meta-web-research-to-report",
    "meta-daily-operator-brief",
]


def _extract_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path}: missing YAML frontmatter"
    end = text.index("\n---", 3)
    return yaml.safe_load(text[3:end])


@pytest.mark.parametrize("name", HIGH_FREQ)
def test_each_step_has_label(name):
    path = Path(f"src/opensquilla/skills/bundled/{name}/SKILL.md")
    fm = _extract_frontmatter(path)
    steps = fm["composition"]["steps"]
    missing = [s["id"] for s in steps if not s.get("label")]
    assert not missing, f"{name}: steps missing label: {missing}"
