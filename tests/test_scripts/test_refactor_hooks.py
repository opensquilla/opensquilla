"""Contract tests for the architecture-refactor control assets."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_refactor_control_docs_capture_superpower_checkpoints() -> None:
    overall = _read("docs/refactor/overall-plan.md")
    template = _read("docs/refactor/stage-template.md")

    assert "superpowers:writing-plans" in overall
    assert "superpowers:test-driven-development" in overall
    assert "superpowers:verification-before-completion" in overall
    assert "Current-state audit" in template
    assert "TDD red/green" in template
    assert "Integration gate" in template
    assert "Co-authored-by: Codex <noreply@openai.com>" in template


def test_refactor_gate_script_preserves_project_quality_commands() -> None:
    script = _read("scripts/refactor_gate.sh")

    assert "uv run --extra dev ruff check src tests" in script
    assert "uv run --extra dev mypy src/opensquilla --show-error-codes" in script
    assert "uv run --extra dev pytest" in script
    assert "uv build --wheel" in script
    assert "opensquilla gateway start" in script
    assert "opensquilla gateway status" in script
    assert "opensquilla gateway stop" in script


def test_refactor_preflight_script_surfaces_context_recovery_inputs() -> None:
    script = _read("scripts/refactor_preflight.sh")

    assert "git status --short --branch" in script
    assert "git rev-parse --short HEAD" in script
    assert "git log --oneline -8" in script
    assert "find . -name AGENTS.md -print" in script
    assert "superpowers:writing-plans" in script


def test_refactor_hook_scripts_help_without_side_effects() -> None:
    for script in (
        "scripts/refactor_preflight.sh",
        "scripts/refactor_gate.sh",
        "scripts/refactor_stage_init.sh",
        "scripts/refactor_stage_close.sh",
    ):
        result = subprocess.run(
            ["bash", str(ROOT / script), "--help"],
            check=False,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        assert result.returncode == 0
        assert "Usage:" in result.stdout


def test_refactor_control_assets_do_not_embed_local_user_paths() -> None:
    for path in (
        "docs/refactor/overall-plan.md",
        "docs/refactor/stage-template.md",
        "scripts/refactor_stage_init.sh",
    ):
        text = _read(path)

        assert "/Users/" not in text
        assert "/home/" not in text
