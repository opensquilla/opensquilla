"""Tool compression slash-command workflows for interactive chat."""

from __future__ import annotations

from opensquilla.cli.ui import console

_COMPRESSION_ENABLED_PATH = "agent_token_saving.tool_result_compression_enabled"
_COMPRESSION_MODE_PATH = "agent_token_saving.tool_result_compression_mode"
_COMPRESSION_SUMMARY_MODEL_PATH = "agent_token_saving.tool_result_compression_summary_model"
_VALID_MODES = {"off", "truncate", "summarize", "status"}
_MODE_ALIASES = {"on": "truncate", "trim": "truncate", "summary": "summarize"}


async def handle_tool_compress_command(
    cmd: str,
    *,
    config: object | None = None,
    client: object | None = None,
) -> None:
    """Handle the chat /tool-compress command."""

    parts = cmd.split()
    arg = parts[1].lower() if len(parts) > 1 else "status"
    mode_arg = _MODE_ALIASES.get(arg, arg)
    if len(parts) > 2 or mode_arg not in _VALID_MODES:
        console.print("[red]Usage: /tool-compress [off|truncate|summarize|status][/red]")
        return

    if client is not None:
        from opensquilla.cli.gateway_client import GatewayClient

        assert isinstance(client, GatewayClient)
        if mode_arg == "status":
            mode = await client.get_config(_COMPRESSION_MODE_PATH)
            enabled = bool(await client.get_config(_COMPRESSION_ENABLED_PATH))
            model = await client.get_config(_COMPRESSION_SUMMARY_MODEL_PATH)
            mode = mode if mode in {"off", "truncate", "summarize"} else None
            resolved_mode = str(mode or ("truncate" if enabled else "off"))
        else:
            resolved_mode = mode_arg
            await client.patch_config_safe(
                {
                    _COMPRESSION_MODE_PATH: resolved_mode,
                    _COMPRESSION_ENABLED_PATH: resolved_mode != "off",
                }
            )
            model = (
                await client.get_config(_COMPRESSION_SUMMARY_MODEL_PATH)
                if resolved_mode == "summarize"
                else None
            )
    else:
        cfg = getattr(config, "agent_token_saving", None)
        if cfg is None:
            console.print("[yellow]Tool result compression config is unavailable.[/yellow]")
            return
        if mode_arg == "status":
            mode = getattr(cfg, "tool_result_compression_mode", None)
            enabled = bool(getattr(cfg, "tool_result_compression_enabled", True))
            model = getattr(cfg, "tool_result_compression_summary_model", None)
            if mode in {"off", "truncate", "summarize"}:
                resolved_mode = str(mode)
            else:
                resolved_mode = "truncate" if enabled else "off"
        else:
            resolved_mode = mode_arg
            setattr(cfg, "tool_result_compression_mode", resolved_mode)
            setattr(cfg, "tool_result_compression_enabled", resolved_mode != "off")
            model = getattr(cfg, "tool_result_compression_summary_model", None)

    model_suffix = f" [dim]model={model}[/dim]" if resolved_mode == "summarize" and model else ""
    console.print(f"[cyan]tool result compression:[/cyan] {resolved_mode.upper()}{model_suffix}")
