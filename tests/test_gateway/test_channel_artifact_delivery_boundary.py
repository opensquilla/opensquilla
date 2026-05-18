from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.gateway.channel_artifacts import (
    artifact_fallback_lines,
    strip_artifact_markers_from_channel_text,
)

ROOT = Path(__file__).resolve().parents[2]
CHANNEL_DISPATCH = ROOT / "src/opensquilla/gateway/channel_dispatch.py"
CHANNEL_ARTIFACTS = ROOT / "src/opensquilla/gateway/channel_artifacts.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_channel_artifact_boundary_preserves_safe_fallback_text() -> None:
    assert artifact_fallback_lines(
        [
            {
                "name": "report.txt",
                "download_url": "/api/v1/artifacts/art-1?sessionKey=secret",
            }
        ]
    ) == ["Generated file: report.txt -> available in WebUI"]
    assert artifact_fallback_lines(
        [
            {
                "name": "signed.txt",
                "signed_download_url": "https://gateway.example/artifacts/art-2?sig=short",
            }
        ]
    ) == ["Generated file: signed.txt -> https://gateway.example/artifacts/art-2?sig=short"]


def test_channel_artifact_boundary_strips_generated_markers() -> None:
    text = "ready\n[generated artifact omitted: chart.png (image/png)]\n\nthanks"

    assert strip_artifact_markers_from_channel_text(text) == "ready\nthanks"


def test_channel_dispatch_imports_artifact_boundary() -> None:
    imports = _imports_from(CHANNEL_DISPATCH)

    assert ("opensquilla.gateway.channel_artifacts", "artifact_event_payload") in imports
    assert ("opensquilla.gateway.channel_artifacts", "artifact_fallback_lines") in imports
    assert (
        "opensquilla.gateway.channel_artifacts",
        "deliver_artifacts_as_channel_files",
    ) in imports
    assert (
        "opensquilla.gateway.channel_artifacts",
        "strip_artifact_markers_from_channel_text",
    ) in imports


def test_channel_dispatch_no_longer_owns_artifact_delivery_helpers() -> None:
    dispatch_functions = _top_level_functions(CHANNEL_DISPATCH)
    artifact_functions = _top_level_functions(CHANNEL_ARTIFACTS)

    assert "artifact_event_payload" in artifact_functions
    assert "artifact_fallback_lines" in artifact_functions
    assert "deliver_artifacts_as_channel_files" in artifact_functions
    assert "strip_artifact_markers_from_channel_text" in artifact_functions
    assert "split_assistant_artifact_content" in artifact_functions

    assert "_artifact_event_payload" not in dispatch_functions
    assert "_artifact_delivery_key" not in dispatch_functions
    assert "_artifact_fallback_lines" not in dispatch_functions
    assert "_strip_artifact_markers_from_channel_text" not in dispatch_functions
    assert "_strip_delivered_artifact_image_references" not in dispatch_functions
    assert "_deliver_artifacts_as_channel_files" not in dispatch_functions
    assert "_split_assistant_artifact_content" not in dispatch_functions
