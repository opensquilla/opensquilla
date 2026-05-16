"""Local skill mutation fallbacks for CLI skill commands."""

from __future__ import annotations

from typing import Any


async def run_local_skill_install(
    identifier: str,
    *,
    source: str,
    force: bool,
) -> Any:
    """Run the local install workflow used when the gateway is unavailable."""

    from opensquilla.skills.hub.operations import (
        run_skill_install_operation,
        skill_install_request,
    )

    return await run_skill_install_operation(
        None,
        skill_install_request(
            {"identifier": identifier, "source": source, "force": force}
        ),
        require_loader=False,
    )


async def run_local_skill_uninstall(name: str) -> Any:
    """Run the local uninstall workflow used when the gateway is unavailable."""

    from opensquilla.skills.hub.operations import (
        run_skill_uninstall_operation,
        skill_uninstall_request,
    )

    return await run_skill_uninstall_operation(
        None,
        skill_uninstall_request({"name": name}),
    )
