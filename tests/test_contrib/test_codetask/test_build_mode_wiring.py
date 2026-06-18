"""Build-mode wiring: template selection, prompt render, result fields, CLI param."""

from __future__ import annotations

import inspect
from pathlib import Path

from opensquilla.contrib.codetask import config, runner
from opensquilla.contrib.codetask.types import TaskResult


def test_template_selection():
    assert config.prompt_template_path("build").name == "app_build.txt"
    assert config.prompt_template_path("red-green").name == "default.txt"
    assert config.prompt_template_path().name == "default.txt"  # default arg


def test_env_override_wins_in_both_modes(monkeypatch, tmp_path):
    custom = tmp_path / "custom.txt"
    custom.write_text("x")
    monkeypatch.setenv("OPENSQUILLA_CODETASK_PROMPT_TEMPLATE", str(custom))
    assert config.prompt_template_path("build") == custom
    assert config.prompt_template_path("red-green") == custom


def test_app_build_template_renders_with_build_checklist():
    out = runner._render_prompt("DO THE THING", "ENV HINT", Path("/tmp/s"), "build")
    assert "DO THE THING" in out
    assert "ENV HINT" in out
    assert "npm ci" in out
    assert "electron-builder" in out
    assert "package-lock.json" in out
    # build mode must NOT ask the agent for the red->green verification.json
    assert "verification.json" not in out


def test_default_template_is_red_green():
    out = runner._render_prompt("DO THE THING", "", Path("/tmp/s"), "red-green")
    assert "acceptance" in out.lower()
    assert "verification" in out.lower()


def test_solve_has_verification_mode_param_defaulting_red_green():
    sig = inspect.signature(runner.solve)
    assert "verification_mode" in sig.parameters
    assert sig.parameters["verification_mode"].default == "red-green"


def test_taskresult_new_field_defaults():
    fields = TaskResult.__dataclass_fields__
    assert fields["verification_kind"].default == "red_green"
    assert fields["build"].default is None


def test_template_selection_edit_mode():
    assert config.prompt_template_path("build", True).name == "app_edit.txt"
    assert config.prompt_template_path("build", False).name == "app_build.txt"


def test_repo_has_app_detection(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "src").mkdir()
    assert runner._repo_has_app(tmp_path) is True
    empty = tmp_path / "empty"
    empty.mkdir()
    assert runner._repo_has_app(empty) is False
