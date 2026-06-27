"""Unit tests for opensquilla.contrib.swebench.prompt."""

from opensquilla.contrib.swebench.prompt import build_prompt, render_debug_prompt

INSTANCE = {
    "instance_id": "django__django-16429",
    "problem_statement": "Things are broken in a very specific way.",
    "base_commit": "abc123def456",
}


def test_build_prompt_with_custom_template(tmp_path):
    template = tmp_path / "tpl.txt"
    template.write_text("Issue: {problem_statement}\nBase: {base_commit}\n")
    prompt = build_prompt(INSTANCE, template_path=template)
    assert prompt == "Issue: Things are broken in a very specific way.\nBase: abc123def456\n"


def test_build_prompt_default_template_renders():
    prompt = build_prompt(INSTANCE)
    assert "Things are broken in a very specific way." in prompt
    assert "abc123def456" in prompt
    # Un-substituted placeholders would mean a malformed template.
    assert "{problem_statement}" not in prompt


def test_build_prompt_env_override(monkeypatch, tmp_path):
    template = tmp_path / "alt.txt"
    template.write_text("ALT {problem_statement}")
    monkeypatch.setenv("OPENSQUILLA_SWEBENCH_PROMPT_TEMPLATE", str(template))
    assert build_prompt(INSTANCE) == "ALT Things are broken in a very specific way."


def test_render_debug_prompt_wraps_with_markers(tmp_path):
    rendered = render_debug_prompt(INSTANCE)
    assert rendered.startswith("=== DEBUG PROMPT for django__django-16429 ===")
    assert rendered.endswith("=== END ===\n")
