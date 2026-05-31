from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    path = Path("scripts/meta_skill_validation_matrix.py")
    spec = importlib.util.spec_from_file_location("meta_skill_validation_matrix", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_meta_skill_validation_matrix_materials_are_present() -> None:
    module = _load_script_module()
    result = module.check_materials(module.load_cases())

    assert result["ok"] is True
    assert len(result["cases"]) >= 10
    assert all(not row["missing"] for row in result["cases"])


def test_meta_skill_validation_matrix_writes_judge_bundle_template(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    out = tmp_path / "bundle.json"

    result = module.write_empty_bundle("B2_pdf_intelligence", out)

    assert result == {"ok": True, "bundle": str(out)}
    bundle = json.loads(out.read_text(encoding="utf-8"))
    assert bundle["case_id"] == "B2_pdf_intelligence"
    assert bundle["skill_name"] == "meta-pdf-intelligence"
    assert "router-evaluation-summary.pdf" in "\n".join(bundle["materials"])
    assert bundle["selected_meta_skill"] == ""
    assert bundle["step_trace"] == []


def test_meta_skill_validation_matrix_writes_live_smoke_bundles(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    result = {
        "soft_activation": {
            "model_decision": {"selected_meta_skill": "meta-live-soft-activation"},
            "observed_tool_results": ["meta-step:classify", "meta_invoke"],
            "meta_invoke_result": "meta-skill completed",
            "final_text": "LIVE_OK",
            "cases": [{"errors": []}],
        },
        "creator": {
            "llm_slots": {
                "name": "decision-history-summary",
                "triggers": ["show decision history"],
            },
            "lint": {"G1": {"passed": True}},
            "smoke": {"G3": {"passed": True}},
            "persist": {
                "proposal_id": "abc123",
                "auto_enable": {"skill_path": str(tmp_path / "skill")},
            },
        },
    }

    written = module.write_live_smoke_bundles(result, tmp_path)

    assert [row["case_id"] for row in written] == [
        "A1_live_soft_activation",
        "C4_live_meta_skill_creator_history_summary",
    ]
    soft = json.loads((tmp_path / "A1_live_soft_activation.bundle.json").read_text())
    assert soft["selected_meta_skill"] == "meta-live-soft-activation"
    assert soft["step_trace"] == [{"step_id": "classify", "status": "ok"}]
    creator = json.loads(
        (tmp_path / "C4_live_meta_skill_creator_history_summary.bundle.json").read_text()
    )
    assert creator["selected_meta_skill"] == "meta-skill-creator"
    assert creator["artifacts"][0]["type"] == "proposal"
