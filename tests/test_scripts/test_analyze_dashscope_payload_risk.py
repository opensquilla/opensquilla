from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "experiments" / (
        "analyze_dashscope_payload_risk.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_dashscope_payload_risk", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_analyze_dashscope_payload_risk_counts_provider_visible_signals(
    tmp_path: Path,
) -> None:
    mod = _load_script()
    artifact_root = tmp_path / "artifacts"

    inst_a = artifact_root / "repo__issue-1"
    inst_a.mkdir(parents=True)
    _write_jsonl(
        inst_a / "transcript.jsonl",
        [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "Historical tool call omitted for provider context budget.\n"
                        "</think>\n"
                        "[Earlier duplicate tool interaction omitted for DashScope replay "
                        "compatibility: tool=read_file]"
                    ),
                }
            }
        ],
    )
    _write_jsonl(
        inst_a / "llm_calls.jsonl",
        [
            {"event": "llm.request", "request_id": "req-a", "ts": 10.0},
            {"event": "llm.response_chunk", "request_id": "req-a", "ts": 12.5},
            {
                "event": "llm.error",
                "request_id": "req-timeout",
                "error_type": "timeout",
                "message": "Request timed out",
            },
            {
                "event": "llm.error",
                "request_id": "req-429",
                "status_code": 429,
                "message": "rate limit",
            },
        ],
    )
    (inst_a / "git.patch").write_text("", encoding="utf-8")

    inst_b = artifact_root / "repo__issue-2"
    inst_b.mkdir(parents=True)
    _write_jsonl(inst_b / "transcript.jsonl", [{"message": {"content": "clean"}}])
    _write_jsonl(
        inst_b / "llm_calls.jsonl",
        [
            {"event": "llm.request", "request_id": "req-b", "ts": 20.0},
            {"event": "llm.response_chunk", "request_id": "req-b", "ts": 21.0},
        ],
    )
    (inst_b / "git.patch").write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")

    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {"instance_id": "repo__issue-1", "model_patch": ""},
            {"instance_id": "repo__issue-2", "model_patch": "diff --git a/a.py b/a.py\n"},
        ],
    )

    summary = mod.analyze_artifact_root(artifact_root, predictions_path=predictions)

    assert summary["instances"] == 2
    assert summary["predictions"]["submitted"] == 2
    assert summary["predictions"]["empty_model_patch"] == 1
    assert summary["patches"]["empty_git_patch"] == 1
    assert summary["signals"]["dashscope_duplicate_omission"] == 1
    assert summary["signals"]["provider_compaction_omission"] == 1
    assert summary["signals"]["bare_think_close"] == 1
    assert summary["llm"]["requests"] == 2
    assert summary["llm"]["errors"] == 2
    assert summary["llm"]["status_429"] == 1
    assert summary["llm"]["timeout_errors"] == 1
    assert summary["llm"]["first_chunk_latency_seconds"]["count"] == 2
    assert summary["llm"]["first_chunk_latency_seconds"]["mean"] == 1.75

