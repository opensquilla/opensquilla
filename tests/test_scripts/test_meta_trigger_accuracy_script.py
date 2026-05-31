from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    path = Path("scripts/meta_trigger_accuracy.py")
    spec = importlib.util.spec_from_file_location("meta_trigger_accuracy", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_meta_trigger_accuracy_script_loads_fixture_cases(tmp_path: Path) -> None:
    module = _load_script_module()
    fixtures = tmp_path / "cases.json"
    fixtures.write_text(
        json.dumps([
            {
                "name": "hit",
                "user_message": "run the alpha report",
                "expected_meta_skill": "meta-alpha",
            },
            {
                "name": "none",
                "user_message": "normal question",
                "expected_meta_skill": None,
            },
        ]),
        encoding="utf-8",
    )

    cases = module.load_cases(fixtures)

    assert [c.name for c in cases] == ["hit", "none"]
    assert cases[0].expected_meta_skill == "meta-alpha"
    assert cases[1].expected_meta_skill is None
