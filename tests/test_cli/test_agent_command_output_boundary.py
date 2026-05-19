from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
import typer

from opensquilla.cli import agent_command_output
from opensquilla.cli.agent_outputs import AgentRunResult

ROOT = Path(__file__).resolve().parents[2]
AGENT_COMMAND_OUTPUT = ROOT / "src" / "opensquilla" / "cli" / "agent_command_output.py"


def _result(
    *,
    text: str = "done",
    artifacts: list[dict[str, Any]] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> AgentRunResult:
    return AgentRunResult(
        status="error" if errors else "ok",
        agent_id="main",
        session_key="agent:main:main",
        text=text,
        usage={"total_tokens": 7},
        errors=errors or [],
        workspace="/tmp/workspace",
        workspace_strict=True,
        thinking="medium",
        transcript_path="/tmp/transcript.jsonl",
        usage_path="/tmp/usage.json",
        artifacts=artifacts,
    )


def test_agent_command_output_exports_boundary_helpers() -> None:
    expected = {"agent_result_payload", "render_agent_result"}

    assert expected <= set(agent_command_output.__all__)
    for name in expected:
        assert hasattr(agent_command_output, name)
        assert getattr(agent_command_output, name).__module__ == (
            "opensquilla.cli.agent_command_output"
        )


def test_agent_result_payload_uses_public_artifact_normalization() -> None:
    artifact = {
        "id": "art-cli",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 4,
        "sha256": "d" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:main",
        "sessionKey": "agent:main:main",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-cli?sessionKey=agent%3Amain%3Amain",
        "store": "artifacts",
    }

    payload = agent_command_output.agent_result_payload(_result(artifacts=[artifact]))

    output_artifact = payload["artifacts"][0]
    assert "session_key" not in output_artifact
    assert "sessionKey" not in json.dumps(output_artifact)
    assert output_artifact["download_url"] == "/api/v1/artifacts/art-cli"


def test_render_agent_result_plain_output_includes_text_and_generated_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _result(
        text="Finished",
        artifacts=[
            {
                "id": "art-cli",
                "kind": "artifact_ref",
                "name": "report.txt",
                "mime": "text/plain",
                "size": 4,
                "sha256": "d" * 64,
                "session_id": "session-1",
                "source": "publish_artifact",
                "created_at": "2026-05-06T12:00:00Z",
                "download_url": "/api/v1/artifacts/art-cli",
                "store": "artifacts",
            }
        ],
    )

    agent_command_output.render_agent_result(
        result,
        json_output=False,
        no_provider_printer=lambda: None,
    )

    assert capsys.readouterr().out == (
        "Finished\nGenerated file: report.txt -> /api/v1/artifacts/art-cli\n"
    )


def test_render_agent_result_no_provider_uses_injected_printer_and_exits() -> None:
    calls: list[str] = []
    result = _result(
        text="",
        errors=[{"message": "No provider available", "code": "no_provider"}],
    )

    with pytest.raises(typer.Exit) as exc_info:
        agent_command_output.render_agent_result(
            result,
            json_output=False,
            no_provider_printer=lambda: calls.append("printed"),
        )

    assert calls == ["printed"]
    assert exc_info.value.exit_code == 1


def test_agent_command_output_does_not_import_agent_cmd() -> None:
    tree = ast.parse(AGENT_COMMAND_OUTPUT.read_text(encoding="utf-8"))

    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "opensquilla.cli.agent_cmd" not in imported_modules
    assert "opensquilla.cli.agent_cmd" not in imported_names
