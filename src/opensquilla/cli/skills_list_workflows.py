"""CLI workflows for skill list commands."""

from __future__ import annotations

from opensquilla.cli.skills_catalog_presenters import emit_skill_rows
from opensquilla.cli.skills_rows import load_skill_rows


def list_skills_for_cli(*, json_output: bool) -> None:
    """Load skill rows and emit the CLI list view."""

    rows = load_skill_rows()
    emit_skill_rows(rows, json_output=json_output)
