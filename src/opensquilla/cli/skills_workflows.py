"""Facade for CLI skill command workflows."""

from __future__ import annotations

from opensquilla.cli.skills_gateway_workflows import (
    update_gateway_skills_for_cli,
    view_gateway_skill_for_cli,
)
from opensquilla.cli.skills_list_workflows import list_skills_for_cli
from opensquilla.cli.skills_mutation_workflows import (
    install_skill_for_cli_command,
    uninstall_skill_for_cli_command,
)
from opensquilla.cli.skills_publish_workflows import publish_skill_for_cli_command
from opensquilla.cli.skills_search_workflows import search_skills_for_cli_command
from opensquilla.cli.skills_tap_workflows import (
    add_skill_tap_for_cli,
    list_skill_taps_for_cli,
    remove_skill_tap_for_cli,
)

__all__ = [
    "add_skill_tap_for_cli",
    "install_skill_for_cli_command",
    "list_skill_taps_for_cli",
    "list_skills_for_cli",
    "publish_skill_for_cli_command",
    "remove_skill_tap_for_cli",
    "search_skills_for_cli_command",
    "uninstall_skill_for_cli_command",
    "update_gateway_skills_for_cli",
    "view_gateway_skill_for_cli",
]
