from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

DASHSCOPE_DUPLICATE_MARKER = "duplicate tool interaction omitted"
PROVIDER_COMPACTION_MARKER = "Historical tool call omitted for provider context budget"
BARE_THINK_CLOSE_MARKER = "</think>"


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _row_text(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def _numeric_timestamp(row: dict[str, Any]) -> float | None:
    for key in ("ts", "timestamp", "time", "created_at"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _instance_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def _latency_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(mean(ordered), 3),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


def _prediction_summary(predictions_path: Path | None) -> dict[str, Any]:
    rows = _iter_jsonl(predictions_path) if predictions_path is not None else []
    submitted = 0
    empty = 0
    instance_ids: set[str] = set()
    for row in rows:
        submitted += 1
        instance_id = row.get("instance_id")
        if isinstance(instance_id, str):
            instance_ids.add(instance_id)
        model_patch = row.get("model_patch")
        if not isinstance(model_patch, str) or not model_patch.strip():
            empty += 1
    return {
        "submitted": submitted,
        "unique_instance_ids": len(instance_ids),
        "empty_model_patch": empty,
    }


def analyze_artifact_root(
    artifact_root: str | Path,
    *,
    predictions_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(artifact_root)
    prediction_path = Path(predictions_path) if predictions_path is not None else None
    instances = _instance_dirs(root)
    signals = {
        "dashscope_duplicate_omission": 0,
        "provider_compaction_omission": 0,
        "bare_think_close": 0,
    }
    patches = {"empty_git_patch": 0, "present_git_patch": 0}
    llm = {
        "requests": 0,
        "responses": 0,
        "response_chunks": 0,
        "errors": 0,
        "status_429": 0,
        "status_5xx": 0,
        "timeout_errors": 0,
    }
    request_ts_by_id: dict[str, float] = {}
    first_chunk_ts_by_id: dict[str, float] = {}

    for instance_dir in instances:
        transcript_text = ""
        transcript_path = instance_dir / "transcript.jsonl"
        if transcript_path.exists():
            transcript_text = transcript_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        signals["dashscope_duplicate_omission"] += transcript_text.count(
            DASHSCOPE_DUPLICATE_MARKER
        )
        signals["provider_compaction_omission"] += transcript_text.count(
            PROVIDER_COMPACTION_MARKER
        )
        signals["bare_think_close"] += transcript_text.count(BARE_THINK_CLOSE_MARKER)

        patch_path = instance_dir / "git.patch"
        if patch_path.exists():
            patches["present_git_patch"] += 1
            if not patch_path.read_text(encoding="utf-8", errors="replace").strip():
                patches["empty_git_patch"] += 1

        for row in _iter_jsonl(instance_dir / "llm_calls.jsonl"):
            event = str(row.get("event") or "")
            if event == "llm.request":
                llm["requests"] += 1
                request_id = row.get("request_id")
                ts = _numeric_timestamp(row)
                if isinstance(request_id, str) and ts is not None:
                    request_ts_by_id.setdefault(request_id, ts)
            elif event == "llm.response":
                llm["responses"] += 1
            elif event == "llm.response_chunk":
                llm["response_chunks"] += 1
                request_id = row.get("request_id")
                ts = _numeric_timestamp(row)
                if isinstance(request_id, str) and ts is not None:
                    first_chunk_ts_by_id.setdefault(request_id, ts)
            elif event == "llm.error":
                llm["errors"] += 1

            status_code = row.get("status_code")
            if status_code == 429:
                llm["status_429"] += 1
            if isinstance(status_code, int) and 500 <= status_code <= 599:
                llm["status_5xx"] += 1
            text = _row_text(row).lower()
            if event == "llm.error" and "timeout" in text:
                llm["timeout_errors"] += 1

    latencies = [
        first_ts - request_ts
        for request_id, request_ts in request_ts_by_id.items()
        if (first_ts := first_chunk_ts_by_id.get(request_id)) is not None
        and first_ts >= request_ts
    ]
    llm["first_chunk_latency_seconds"] = _latency_summary(latencies)

    return {
        "artifact_root": str(root),
        "instances": len(instances),
        "predictions": _prediction_summary(prediction_path),
        "patches": patches,
        "signals": signals,
        "llm": llm,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Qwen/DashScope provider-visible run artifact risks.",
    )
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--predictions", type=Path, default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    summary = analyze_artifact_root(
        args.artifact_root,
        predictions_path=args.predictions,
    )
    indent = 2 if args.pretty else None
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

