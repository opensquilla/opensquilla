"""RPC handlers for onboarding (catalog, status, provider/channel mutations).

Mutations are applied against the gateway's *active* in-memory config when the
RPC context provides one (``ctx.config``). The same context exposes the
running ``provider_selector``; provider mutations are mirrored into it so a
``configure`` from the WebUI takes effect on the next chat without a restart.

Channel mutations always require a restart because ``ChannelManager`` is built
once at boot.

The onboarding mutation/store modules import ``opensquilla.gateway.config`` at
module top level, which transitively re-enters ``opensquilla.gateway`` during
boot. To avoid the circular import, we import those bindings lazily inside the
handler bodies.
"""

from __future__ import annotations

from typing import Any

from opensquilla.gateway.rpc import RpcContext, get_dispatcher

_d = get_dispatcher()


def _active_config(ctx: RpcContext) -> Any:
    """Return the gateway's running config when available, else load from disk."""
    if ctx.config is not None:
        return ctx.config
    from opensquilla.onboarding.config_store import load_config

    return load_config()


def _config_path_for(ctx: RpcContext, source: Any) -> str | None:
    """Resolve the persistence path that matches ``source``.

    Prefers the path stored on the running ``GatewayConfig`` so RPCs save back
    to wherever the gateway booted from (e.g. ``./opensquilla.toml``) rather
    than the env-default user config.
    """
    path = getattr(source, "config_path", None)
    if path:
        return str(path)
    return None


def _apply_inplace(ctx: RpcContext, new_cfg: Any) -> None:
    """Mirror new config fields into ``ctx.config`` so the running gateway sees them."""
    if ctx.config is None or ctx.config is new_cfg:
        return
    for field_name in type(new_cfg).model_fields:
        setattr(ctx.config, field_name, getattr(new_cfg, field_name))
    if hasattr(ctx.config, "inherit_runtime_secrets"):
        ctx.config.inherit_runtime_secrets(new_cfg)


def _sync_provider_selector(ctx: RpcContext, config: Any) -> None:
    from opensquilla.gateway.provider_runtime_sync import sync_provider_selector

    sync_provider_selector(ctx, getattr(ctx, "config", None) or config)


def _sync_image_generation(config: Any) -> None:
    from opensquilla.gateway.provider_runtime_sync import sync_image_generation

    sync_image_generation(config)


def _persist(ctx: RpcContext, new_cfg: Any, *, restart_required: bool) -> str:
    from opensquilla.onboarding.config_store import persist_config

    if (
        ctx.config is not None
        and ctx.config is not new_cfg
        and hasattr(new_cfg, "inherit_runtime_secrets")
    ):
        new_cfg.inherit_runtime_secrets(ctx.config)
    path = _config_path_for(ctx, new_cfg) or _config_path_for(ctx, ctx.config)
    persist = persist_config(new_cfg, path=path, restart_required=restart_required)
    # Preserve the resolved path on the running config so subsequent saves
    # round-trip to the same file.
    if hasattr(new_cfg, "config_path") and not getattr(new_cfg, "config_path", None):
        new_cfg.config_path = str(persist.path)
    if (
        ctx.config is not None
        and hasattr(ctx.config, "config_path")
        and not getattr(ctx.config, "config_path", None)
    ):
        ctx.config.config_path = str(persist.path)
    return str(persist.path)


@_d.method("onboarding.status", scope="operator.read")
async def _onboarding_status(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.rpc_payload import onboarding_status_rpc_payload

    cfg = _active_config(ctx)
    return onboarding_status_rpc_payload(cfg, config_path=_config_path_for(ctx, cfg))


@_d.method("onboarding.catalog", scope="operator.read")
async def _onboarding_catalog(params: Any, ctx: RpcContext) -> dict[str, Any]:
    from opensquilla.onboarding.rpc_payload import onboarding_catalog_rpc_payload

    return onboarding_catalog_rpc_payload()


def _require(params: Any, key: str) -> Any:
    if not isinstance(params, dict) or key not in params:
        raise ValueError(f"params.{key} is required")
    return params[key]
