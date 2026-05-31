"""RPC handlers for the config domain."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.paths import default_opensquilla_home

_d = get_dispatcher()


def _update_config_in_place(old: Any, new: Any) -> None:
    """Copy all fields from new config into the existing config object in-memory."""
    for field_name in type(new).model_fields:
        setattr(old, field_name, getattr(new, field_name))
    if hasattr(old, "inherit_runtime_secrets"):
        old.inherit_runtime_secrets(new)


def _persist_config(config: Any) -> None:
    """Write config to TOML, defaulting to the user config path when unset."""
    if not getattr(config, "config_path", None) and hasattr(config, "config_path"):
        config.config_path = str(default_opensquilla_home() / "config.toml")

    if not getattr(config, "config_path", None):
        return

    import tomli_w  # TOML writer (tomllib is read-only)

    path = Path(config.config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(config.to_toml_dict(), f)


def _inherit_runtime_secrets(source: Any, target: Any) -> None:
    if hasattr(target, "inherit_runtime_secrets") and source is not None:
        target.inherit_runtime_secrets(source)


def _clear_runtime_secret_paths(config: Any, paths: set[str]) -> None:
    if not hasattr(config, "clear_runtime_secret"):
        return
    for path in paths:
        config.clear_runtime_secret(path)


def _collect_paths(payload: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            current = f"{prefix}.{key}" if prefix else key
            paths.add(current)
            paths.update(_collect_paths(value, current))
    return paths


def _align_auto_router_profile_for_provider_patch(
    source_config: Any,
    cfg_dict: dict[str, Any],
    explicit_paths: set[str],
) -> None:
    if "llm.provider" not in explicit_paths:
        return
    if any(
        path == "squilla_router" or path.startswith("squilla_router.")
        for path in explicit_paths
    ):
        return

    llm = cfg_dict.get("llm")
    router = cfg_dict.get("squilla_router")
    if not isinstance(llm, dict) or not isinstance(router, dict):
        return

    old_provider = str(getattr(getattr(source_config, "llm", None), "provider", "") or "")
    old_provider = old_provider.strip().lower()
    new_provider = str(llm.get("provider") or "").strip().lower()
    if not old_provider or not new_provider or old_provider == new_provider:
        return

    profile = str(router.get("tier_profile") or "").strip().lower()
    if profile != old_provider:
        return

    from opensquilla.gateway.config import ROUTER_TIER_PROFILE_IDS, _router_tier_profile_defaults

    try:
        old_defaults = _router_tier_profile_defaults(old_provider)
    except ValueError:
        return
    if router.get("tiers") != old_defaults:
        return

    if new_provider in ROUTER_TIER_PROFILE_IDS and new_provider != "openrouter":
        router["tier_profile"] = new_provider
        router["tiers"] = _router_tier_profile_defaults(new_provider)
        return

    router.pop("tier_profile", None)
    router.pop("tiers", None)


_REDACTED_PUBLIC_VALUE = "[redacted]"


def _is_sensitive_redacted_path(path: str) -> bool:
    if not path:
        return False
    from opensquilla.gateway.config import is_sensitive_config_key

    return is_sensitive_config_key(path.rsplit(".", 1)[-1])


def _has_existing_redacted_source(source: Any) -> bool:
    return source is not None and source != ""


def _restore_redacted_values(payload: Any, source: Any, prefix: str = "") -> tuple[Any, set[str]]:
    if payload == _REDACTED_PUBLIC_VALUE and _is_sensitive_redacted_path(prefix):
        if not _has_existing_redacted_source(source):
            raise ValueError(f"Cannot preserve redacted secret at {prefix}: no existing secret")
        return source, {prefix} if prefix else set()
    if isinstance(payload, dict):
        source_dict = source if isinstance(source, dict) else {}
        restored: dict[str, Any] = {}
        redacted_paths: set[str] = set()
        for key, value in payload.items():
            current = f"{prefix}.{key}" if prefix else key
            child, child_paths = _restore_redacted_values(
                value,
                source_dict.get(key),
                current,
            )
            restored[key] = child
            redacted_paths.update(child_paths)
        return restored, redacted_paths
    if isinstance(payload, list):
        source_list = source if isinstance(source, list) else []
        restored_list: list[Any] = []
        list_redacted_paths: set[str] = set()
        for index, value in enumerate(payload):
            current = f"{prefix}.{index}" if prefix else str(index)
            source_value = source_list[index] if index < len(source_list) else None
            child, child_paths = _restore_redacted_values(value, source_value, current)
            restored_list.append(child)
            list_redacted_paths.update(child_paths)
        return restored_list, list_redacted_paths
    return payload, set()


def _memory_restart_required_for_paths(paths: set[str]) -> bool:
    for path in paths:
        if path == "memory":
            return True
        if path == "memory.retrieval_mode":
            return True
        if path.startswith("memory.embedding"):
            return True
    return False


def _memory_restart_fingerprint(config: Any) -> dict[str, Any]:
    if config is None or not hasattr(config, "model_dump"):
        return {}
    data = config.model_dump(mode="python")
    memory = data.get("memory") if isinstance(data, dict) else None
    if not isinstance(memory, dict):
        return {}
    return {
        "retrieval_mode": memory.get("retrieval_mode"),
        "embedding": memory.get("embedding"),
    }


def _channels_restart_fingerprint(config: Any) -> Any:
    """Fingerprint config.channels so any change forces restartRequired=True.

    ChannelManager and webhook routes are constructed once at boot, so any
    field change in config.channels — even a single token — requires a
    gateway restart to take live effect.
    """
    if config is None or not hasattr(config, "model_dump"):
        return None
    data = config.model_dump(mode="python")
    channels = data.get("channels") if isinstance(data, dict) else None
    if not isinstance(channels, dict):
        return None
    entries = channels.get("channels") or []
    if not isinstance(entries, list):
        return None
    return sorted(
        [entry for entry in entries if isinstance(entry, dict)],
        key=lambda e: (e.get("name") or "", e.get("type") or ""),
    )


def _sandbox_posture_restart_fingerprint(config: Any) -> dict[str, Any]:
    if config is None or not hasattr(config, "model_dump"):
        return {}
    data = config.model_dump(mode="python")
    if not isinstance(data, dict):
        return {}
    return {
        "permissions": data.get("permissions"),
        "sandbox": data.get("sandbox"),
    }


def _restart_required(
    *,
    old_memory_fingerprint: dict[str, Any],
    old_channels_fingerprint: Any,
    old_sandbox_posture_fingerprint: dict[str, Any],
    new_config: Any,
) -> bool:
    return (
        old_memory_fingerprint != _memory_restart_fingerprint(new_config)
        or old_channels_fingerprint != _channels_restart_fingerprint(new_config)
        or old_sandbox_posture_fingerprint
        != _sandbox_posture_restart_fingerprint(new_config)
    )


def _validate_memory_embedding_semantics(config: Any) -> None:
    memory_cfg = getattr(config, "memory", None)
    if memory_cfg is None:
        return
    from opensquilla.memory.embedding_resolver import resolve_memory_embedding

    resolve_memory_embedding(memory_cfg, local_available=lambda *_: False)


def _sync_provider_selector(ctx: RpcContext, config: Any) -> None:
    llm_cfg = getattr(config, "llm", None)
    if llm_cfg is None:
        return

    from opensquilla.gateway.llm_runtime import resolve_llm_runtime_config
    from opensquilla.provider.selector import ProviderConfig

    runtime = resolve_llm_runtime_config(config)
    selector = getattr(ctx, "provider_selector", None)
    if selector is None or not hasattr(selector, "sync_primary"):
        return

    selector.sync_primary(
        ProviderConfig(
            provider=runtime.provider,
            model=runtime.model,
            api_key=runtime.api_key,
            base_url=runtime.base_url,
            proxy=runtime.proxy,
            provider_routing=runtime.provider_routing,
        )
    )


def _sync_image_generation(config: Any) -> None:
    from opensquilla.tools.builtin.media import configure_image_generation

    configure_image_generation(
        getattr(config, "image_generation", None),
        llm_config=getattr(config, "llm", None),
        squilla_router_config=getattr(config, "squilla_router", None),
    )


# Read-only paths that cannot be modified via config.set/patch/apply
_READONLY_PATHS = frozenset({"auth.token", "auth.password"})
_SAFE_WRITE_PATCH_PATHS = frozenset(
    {
        "skills.filter_enabled",
        "skills.filter_lexical_top_n",
        "skills.filter_semantic_top_n",
        "skills.filter_rrf_k",
        "prompt_cache.mode",
        "squilla_router.enabled",
        "squilla_router.rollout_phase",
        "squilla_router.strategy",
        "squilla_router.default_tier",
        "squilla_router.confidence_threshold",
    }
)


def _resolve_path(obj: dict, path: str) -> Any:
    """Walk a dot-separated path into a nested dict."""
    parts = path.split(".")
    val: Any = obj
    for part in parts:
        if isinstance(val, dict):
            if part not in val:
                raise KeyError(f"Path not found: {path}")
            val = val[part]
        else:
            raise KeyError(f"Path not found: {path}")
    return val


def _set_path(obj: dict, path: str, value: Any) -> None:
    """Set a value at a dot-separated path in a nested dict."""
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge *patch* into *base*. Keys set to None delete the target key."""
    result = dict(base)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@_d.method("config.set", scope="operator.admin")
async def _handle_config_set(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict) or "path" not in params or "value" not in params:
        raise ValueError("params.path and params.value are required")

    path: str = params["path"]
    if path in _READONLY_PATHS:
        raise ValueError(f"Path is read-only: {path}")

    if ctx.config is None:
        raise ValueError("No config available")

    old_memory_fingerprint = _memory_restart_fingerprint(ctx.config)
    old_channels_fingerprint = _channels_restart_fingerprint(ctx.config)
    old_sandbox_posture_fingerprint = _sandbox_posture_restart_fingerprint(ctx.config)
    cfg_dict = ctx.config.model_dump() if hasattr(ctx.config, "model_dump") else {}
    # Validate path exists
    source_value = _resolve_path(cfg_dict, path)
    value = params["value"]
    if value == _REDACTED_PUBLIC_VALUE and _is_sensitive_redacted_path(path):
        raise ValueError(
            f"Cannot set redacted secret marker directly at {path}; "
            "submit the containing public config object to preserve it"
        )
    restored_value, redacted_paths = _restore_redacted_values(value, source_value, path)
    _set_path(cfg_dict, path, restored_value)

    # Re-validate full config
    from opensquilla.gateway.config import GatewayConfig

    new_config = GatewayConfig(**cfg_dict)
    if _memory_restart_required_for_paths({path}):
        _validate_memory_embedding_semantics(new_config)
    _inherit_runtime_secrets(ctx.config, new_config)
    explicit_paths = {path} | _collect_paths(value, path)
    _clear_runtime_secret_paths(new_config, explicit_paths - redacted_paths)
    _sync_provider_selector(ctx, new_config)
    _update_config_in_place(ctx.config, new_config)
    _sync_image_generation(new_config)
    _persist_config(ctx.config)
    return {
        "restartRequired": _restart_required(
            old_memory_fingerprint=old_memory_fingerprint,
            old_channels_fingerprint=old_channels_fingerprint,
            old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
            new_config=new_config,
        )
    }


@_d.method("config.patch", scope="operator.admin")
async def _handle_config_patch(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params.patch or params.patches is required")

    # Accept both "patch" (dict merge) and "patches" (dot-path key-value pairs)
    patch_data = params.get("patch") or {}
    dot_patches = params.get("patches") or {}

    if not patch_data and not dot_patches:
        raise ValueError("params.patch or params.patches is required")

    if ctx.config is None:
        raise ValueError("No config available")

    old_memory_fingerprint = _memory_restart_fingerprint(ctx.config)
    old_channels_fingerprint = _channels_restart_fingerprint(ctx.config)
    old_sandbox_posture_fingerprint = _sandbox_posture_restart_fingerprint(ctx.config)
    cfg_dict = ctx.config.model_dump() if hasattr(ctx.config, "model_dump") else {}
    source_cfg_dict = copy.deepcopy(cfg_dict) if isinstance(cfg_dict, dict) else {}
    redacted_paths: set[str] = set()

    # Apply dot-path patches (e.g. {"skills.filter_enabled": true})
    for path, value in dot_patches.items():
        if path in _READONLY_PATHS:
            continue
        if value == _REDACTED_PUBLIC_VALUE and _is_sensitive_redacted_path(path):
            raise ValueError(
                f"Cannot patch redacted secret marker directly at {path}; "
                "submit the containing public config object to preserve it"
            )
        try:
            source_value = _resolve_path(source_cfg_dict, path)
        except KeyError:
            source_value = None
        restored_value, restored_paths = _restore_redacted_values(value, source_value, path)
        redacted_paths.update(restored_paths)
        _set_path(cfg_dict, path, restored_value)

    # Apply dict merge patch
    if patch_data:
        patch_data, merge_restored_paths = _restore_redacted_values(patch_data, source_cfg_dict)
        redacted_paths.update(merge_restored_paths)
        cfg_dict = _deep_merge(cfg_dict, patch_data)

    explicit_paths = set(dot_patches.keys()) | _collect_paths(patch_data)
    for path, value in dot_patches.items():
        explicit_paths.update(_collect_paths(value, path))
    _align_auto_router_profile_for_provider_patch(ctx.config, cfg_dict, explicit_paths)

    from opensquilla.gateway.config import GatewayConfig

    new_config = GatewayConfig(**cfg_dict)
    if _memory_restart_required_for_paths(explicit_paths):
        _validate_memory_embedding_semantics(new_config)
    _inherit_runtime_secrets(ctx.config, new_config)
    _clear_runtime_secret_paths(new_config, explicit_paths - redacted_paths)

    _sync_provider_selector(ctx, new_config)
    # Update in-memory config so subsequent requests see changes immediately
    _update_config_in_place(ctx.config, new_config)
    _sync_image_generation(new_config)

    _persist_config(ctx.config)
    return {
        "patched": list(dot_patches.keys()) + (["(merge)"] if patch_data else []),
        "restartRequired": _restart_required(
            old_memory_fingerprint=old_memory_fingerprint,
            old_channels_fingerprint=old_channels_fingerprint,
            old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
            new_config=new_config,
        ),
    }


@_d.method("config.patch.safe", scope="operator.write")
async def _handle_config_patch_safe(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params.patches is required")

    patch_data = params.get("patch") or {}
    dot_patches = params.get("patches") or {}
    if patch_data:
        raise ValueError("params.patch is not supported for safe config patch")
    if not dot_patches:
        raise ValueError("params.patches is required")

    unsafe_paths = sorted(set(dot_patches) - _SAFE_WRITE_PATCH_PATHS)
    if unsafe_paths:
        raise ValueError(f"Path is not safe for operator.write: {unsafe_paths[0]}")

    return cast(dict[str, Any], await _handle_config_patch(params, ctx))


@_d.method("config.apply", scope="operator.admin")
async def _handle_config_apply(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ValueError("params.config is required")

    from opensquilla.gateway.config import GatewayConfig

    config_payload = params.get("config")
    if config_payload is None and "config_yaml" in params:
        import yaml  # type: ignore[import-untyped]

        config_payload = yaml.safe_load(params["config_yaml"]) or {}

    if not isinstance(config_payload, dict):
        raise ValueError("params.config is required")

    config_payload = dict(config_payload)
    if ctx.config is not None and not config_payload.get("config_path"):
        config_payload["config_path"] = getattr(ctx.config, "config_path", None)

    old_memory_fingerprint = _memory_restart_fingerprint(ctx.config)
    old_channels_fingerprint = _channels_restart_fingerprint(ctx.config)
    old_sandbox_posture_fingerprint = _sandbox_posture_restart_fingerprint(ctx.config)
    old_payload = (
        ctx.config.model_dump(mode="python")
        if ctx.config is not None and hasattr(ctx.config, "model_dump")
        else {}
    )
    config_payload, redacted_paths = _restore_redacted_values(config_payload, old_payload)

    # Validate and persist the full replacement config
    new_config = GatewayConfig(**config_payload)
    _validate_memory_embedding_semantics(new_config)
    _inherit_runtime_secrets(ctx.config, new_config)
    _clear_runtime_secret_paths(new_config, _collect_paths(config_payload) - redacted_paths)
    _sync_provider_selector(ctx, new_config)
    if ctx.config is not None:
        _update_config_in_place(ctx.config, new_config)
    _sync_image_generation(new_config)
    _persist_config(ctx.config if ctx.config is not None else new_config)
    return {
        "restartRequired": _restart_required(
            old_memory_fingerprint=old_memory_fingerprint,
            old_channels_fingerprint=old_channels_fingerprint,
            old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
            new_config=new_config,
        )
    }


@_d.method("config.schema", scope="operator.admin")
async def _handle_config_schema(params: dict | None, ctx: RpcContext) -> dict:
    from opensquilla.gateway.config import GatewayConfig

    schema = GatewayConfig.model_json_schema()

    if isinstance(params, dict) and params.get("section"):
        section = params["section"]
        # Navigate into $defs or properties
        props = schema.get("properties", {})
        if section in props:
            return {"schema": props[section]}
        defs = schema.get("$defs", {})
        if section in defs:
            return {"schema": defs[section]}
        raise KeyError(f"Schema section not found: {section}")

    return {"schema": schema}


@_d.method("config.schema.lookup", scope="operator.read")
async def _handle_config_schema_lookup(params: dict | None, ctx: RpcContext) -> dict:
    if not isinstance(params, dict) or "path" not in params:
        raise ValueError("params.path is required")

    from opensquilla.gateway.config import GatewayConfig

    schema = GatewayConfig.model_json_schema()
    path = params["path"]
    parts = path.split(".")

    # Walk through the schema tree resolving $ref along the way
    node: dict = schema
    for part in parts:
        props = node.get("properties", {})
        if part in props:
            node = props[part]
            # Resolve $ref if present
            ref = node.get("$ref")
            if ref and ref.startswith("#/$defs/"):
                def_name = ref.split("/")[-1]
                node = schema.get("$defs", {}).get(def_name, node)
        else:
            raise KeyError(f"Schema path not found: {path}")

    return {
        "path": path,
        "type": node.get("type", "object"),
        "description": node.get("description"),
        "default": node.get("default"),
        "enum": node.get("enum"),
    }
