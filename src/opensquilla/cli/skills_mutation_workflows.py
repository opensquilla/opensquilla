"""CLI workflows for skill install and uninstall mutations."""

from __future__ import annotations

from opensquilla.cli.skills_gateway_mutations import try_gateway_skill_mutation
from opensquilla.cli.skills_local_mutations import (
    run_local_skill_install,
    run_local_skill_uninstall,
)
from opensquilla.cli.skills_mutation_presenters import (
    emit_failed_skill_mutation,
    emit_local_skill_install_result,
    emit_local_skill_install_start,
    emit_local_skill_uninstall_result,
    emit_missing_skill_mutation_result,
    emit_skill_mutation_payload,
)


async def install_skill_for_cli(
    identifier: str,
    *,
    source: str,
    force: bool,
    json_output: bool,
) -> None:
    """Install a skill through the gateway, falling back locally when unavailable."""

    payload = await try_gateway_skill_mutation(
        "skills.install",
        {"identifier": identifier, "source": source, "force": force},
        json_output=json_output,
    )
    if payload is not None:
        emit_skill_mutation_payload(
            payload,
            json_output=json_output,
            success_label="Installed",
            fallback_name=identifier,
        )
        return

    emit_local_skill_install_start(identifier, source, json_output=json_output)
    outcome = await run_local_skill_install(
        identifier,
        source=source,
        force=force,
    )
    if outcome.unavailable_message:
        emit_failed_skill_mutation(
            outcome.unavailable_message,
            json_output=json_output,
            success_label="Installed",
            fallback_name=identifier,
        )
        return

    result = outcome.result
    if result is None:
        emit_missing_skill_mutation_result(
            "install",
            json_output=json_output,
            success_label="Installed",
            fallback_name=identifier,
        )
        return

    emit_local_skill_install_result(result, json_output=json_output)


async def uninstall_skill_for_cli(name: str, *, json_output: bool) -> None:
    """Uninstall a skill through the gateway, falling back locally when unavailable."""

    payload = await try_gateway_skill_mutation(
        "skills.uninstall",
        {"name": name},
        json_output=json_output,
    )
    if payload is not None:
        emit_skill_mutation_payload(
            payload,
            json_output=json_output,
            success_label="Uninstalled",
            fallback_name=name,
        )
        return

    outcome = await run_local_skill_uninstall(name)
    if outcome.unavailable_message:
        emit_failed_skill_mutation(
            outcome.unavailable_message,
            json_output=json_output,
            success_label="Uninstalled",
            fallback_name=name,
        )
        return

    result = outcome.result
    if result is None:
        emit_missing_skill_mutation_result(
            "uninstall",
            json_output=json_output,
            success_label="Uninstalled",
            fallback_name=name,
        )
        return

    emit_local_skill_uninstall_result(result, json_output=json_output)
