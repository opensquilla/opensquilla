"""Input prompt and attachment builders for interactive chat commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opensquilla.cli import attachments as _cli_attachments
from opensquilla.cli.ui import console


def _image_prompt_from_command(command: str) -> str:
    return _cli_attachments.image_prompt_from_command(command)


def _image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
    prompt, attachments = _cli_attachments.image_prompt_and_attachments(command)
    if attachments:
        name = attachments[0].get("name") or "image"
        data = attachments[0].get("data") or ""
        console.print(f"[dim]Sending image: {name} ({len(data) // 1024}KB base64)[/dim]")
    return prompt, attachments


def _gateway_client_is_local(client: object) -> bool:
    local_attr = getattr(client, "is_local_gateway", None)
    if callable(local_attr):
        try:
            return bool(local_attr())
        except TypeError:
            return False
    if local_attr is not None:
        return bool(local_attr)

    try:
        from opensquilla.cli.gateway_client import gateway_base_is_local
    except Exception:  # pragma: no cover - defensive import fallback
        return False
    return gateway_base_is_local(getattr(client, "_http_base", None))


def _parse_path_command(command: str) -> tuple[Path, str]:
    return _cli_attachments.parse_path_command(command)


def _path_strategy_hint(path: Path) -> str:
    return _cli_attachments.path_strategy_hint(path)


def _path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
    return _cli_attachments.path_prompt_and_attachments(command)


def _file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return _cli_attachments.file_prompt_and_attachments(
        command, upload_callable=upload_callable
    )


async def _async_file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return await _cli_attachments.async_file_prompt_and_attachments(
        command, upload_callable=upload_callable
    )
