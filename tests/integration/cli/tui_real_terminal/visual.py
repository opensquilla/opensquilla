from __future__ import annotations

from typing import Any


def build_visual_verdict(
    *,
    scenario_id: str,
    checkpoint: str,
    backend_id: str,
    terminal_size: dict[str, int],
    screenshot_path: str | None,
    frame_path: str,
    expected_visible_regions: tuple[str, ...],
) -> dict[str, Any]:
    status = "inspect" if screenshot_path is None else "pass"
    severity = "inspect-only" if screenshot_path is None else "acceptable-variation"
    symptom = "screenshot unavailable" if screenshot_path is None else "no blocking symptom"
    return {
        "status": status,
        "severity": severity,
        "affected_region": "terminal",
        "symptom": symptom,
        "suspected_cause": "text-only driver mode" if screenshot_path is None else "none",
        "recommended_next_action": (
            "review transcript and frames" if screenshot_path is None else "keep evidence"
        ),
        "input": {
            "scenario_id": scenario_id,
            "checkpoint": checkpoint,
            "backend_id": backend_id,
            "terminal_size": terminal_size,
            "screenshot_path": screenshot_path,
            "frame_path": frame_path,
            "expected_visible_regions": list(expected_visible_regions),
            "failure_modes": [
                "overlap between HUD, prompt, tool cards, and stream text",
                "clipping at terminal edge, panel border, or prompt region",
                "broken wrapping for long text, code fences, URLs, and CJK text",
                "unreadable hierarchy or color contrast",
                "stale loading, approval, or HUD state",
                "bad recovery after resize, Ctrl-C, approval, or EOF",
            ],
        },
    }


def blocking(verdict: dict[str, Any]) -> bool:
    return verdict.get("status") == "fail" and verdict.get("severity") == "blocking"
