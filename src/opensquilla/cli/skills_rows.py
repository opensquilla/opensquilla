"""Local skill row loading for CLI skill views."""

from __future__ import annotations

import os
from typing import Any

from opensquilla.gateway.config import GatewayConfig
from opensquilla.skills import runtime as skill_runtime
from opensquilla.skills.runtime_facade import loaded_skill_rows


def load_skill_rows() -> list[dict[str, Any]]:
    """Load local skill rows for the CLI list view."""

    config = GatewayConfig.load(os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH"))
    skill_setup = skill_runtime.create_configured_skill_loader(
        config.skills,
        workspace_dir=config.workspace_dir,
    )
    return loaded_skill_rows(skill_setup.loader)
