"""Generate prompts for OpenSquilla agent from SWE-bench instances."""

import logging
from pathlib import Path

from opensquilla.contrib.swebench.config import prompt_template_path

logger = logging.getLogger(__name__)


def build_prompt(
    instance: dict,
    template_path: Path | None = None,
) -> str:
    """Render a prompt for the given SWE-bench instance.

    Args:
        instance: SWE-bench instance dict with at least
            'problem_statement' and 'base_commit'.
        template_path: Path to prompt template file. Uses the packaged
            default (or OPENSQUILLA_SWEBENCH_PROMPT_TEMPLATE) if None.

    Returns:
        Rendered prompt string.
    """
    path = template_path or prompt_template_path()
    template = path.read_text(encoding="utf-8")

    prompt = template.format(
        problem_statement=instance["problem_statement"],
        base_commit=instance.get("base_commit", ""),
    )
    return prompt


def render_debug_prompt(instance: dict) -> str:
    """Render a prompt for debugging/review without running the agent."""
    prompt = build_prompt(instance)
    header = f"=== DEBUG PROMPT for {instance['instance_id']} ===\n"
    footer = "\n=== END ===\n"
    return header + prompt + footer
