"""RPC handlers for the config domain."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

from opensquilla.gateway.config_secrets import (
    REDACTED_PUBLIC_VALUE as _REDACTED_PUBLIC_VALUE,
)
from opensquilla.gateway.config_secrets import (
    collect_paths as _collect_paths,
)
from opensquilla.gateway.config_secrets import (
    inherit_runtime_secrets as _inherit_runtime_secrets,
)
from opensquilla.gateway.config_secrets import (
    inherit_then_clear_explicit,
)
from opensquilla.gateway.config_secrets import (
    is_sensitive_redacted_path as _is_sensitive_redacted_path,
)
from opensquilla.gateway.config_secrets import (
    restore_redacted_values as _restore_redacted_values,
)
from opensquilla.gateway.rpc import RpcContext, get_dispatcher
from opensquilla.paths import default_opensquilla_home

_d = get_dispatcher()


def _update_config_in_place(old: Any, new: Any) -> None:
    """Copy all fields from new config into the existing config object in-memory."""
    for field_name in type(new).model_fields:
        setattr(old, field_name, getattr(new, field_name))
    _inherit_runtime_secrets(new, old)


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


def _strip_public_derived_config_fields(payload: dict[str, Any]) -> dict[str, Any]:
    privacy = payload.get("privacy")
    if isinstance(privacy, dict) and "network_observability_disabled_effective" in privacy:
        payload = dict(payload)
        privacy = dict(privacy)
        privacy.pop("network_observability_disabled_effective", None)
        payload["privacy"] = privacy
    return payload


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
    return bool(
        _restart_sections(
            old_memory_fingerprint=old_memory_fingerprint,
            old_channels_fingerprint=old_channels_fingerprint,
            old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
            new_config=new_config,
        )
    )


def _restart_sections(
    *,
    old_memory_fingerprint: dict[str, Any],
    old_channels_fingerprint: Any,
    old_sandbox_posture_fingerprint: dict[str, Any],
    new_config: Any,
) -> list[str]:
    """Top-level sections whose restart fingerprint changed old→new.

    Mirrors :func:`_restart_required` but names the gated sections so
    responses can report *why* a restart is required and so the
    ``liveApplied`` diff can exclude exactly those sections. The sandbox
    posture fingerprint spans two top-level sections (``permissions`` and
    ``sandbox``); they are compared per key so the response names only the
    one that actually changed.
    """
    sections: list[str] = []
    if old_memory_fingerprint != _memory_restart_fingerprint(new_config):
        sections.append("memory")
    if old_channels_fingerprint != _channels_restart_fingerprint(new_config):
        sections.append("channels")
    new_sandbox_posture = _sandbox_posture_restart_fingerprint(new_config)
    for key in ("permissions", "sandbox"):
        if old_sandbox_posture_fingerprint.get(key) != new_sandbox_posture.get(key):
            sections.append(key)
    return sections


def _live_applied_sections(
    old_dump: dict[str, Any],
    new_dump: dict[str, Any],
    restart_gated: list[str],
) -> list[str]:
    """Top-level config sections that differ old→new and are not restart-gated.

    These are the sections a write/reload actually hot-applied in-process via
    :func:`_update_config_in_place`. Sections listed in ``restart_gated``
    changed too but only take live effect after a gateway restart, so they are
    excluded here. ``config_path`` is machine-local load metadata, not a
    config section, and is never reported.

    Honesty caveat: restart fingerprints cover only memory/channels/sandbox
    posture. Boot-only fields outside those fingerprints (auth, host, port,
    file logging, search provider wiring) are reported here when they differ
    even though parts of them are read once at boot — see the
    ``config.reload`` handler docstring for the known blind spots.
    """
    excluded = set(restart_gated) | {"config_path"}
    keys = set(old_dump) | set(new_dump)
    return sorted(
        key
        for key in keys
        if key not in excluded and old_dump.get(key) != new_dump.get(key)
    )


def _config_dump(config: Any) -> dict[str, Any]:
    if config is None or not hasattr(config, "model_dump"):
        return {}
    data = config.model_dump(mode="python")
    return data if isinstance(data, dict) else {}


def _change_meta(
    *,
    old_memory_fingerprint: dict[str, Any],
    old_channels_fingerprint: Any,
    old_sandbox_posture_fingerprint: dict[str, Any],
    old_dump: dict[str, Any],
    new_config: Any,
) -> dict[str, Any]:
    """Build the shared ``restartRequired`` / ``restartSections`` /
    ``liveApplied`` response fields from old fingerprints + old dump vs the
    candidate config. ``restartRequired`` is ``bool(restartSections)`` and
    agrees with :func:`_restart_required` (same fingerprints, same
    comparisons — only named per section)."""
    restart_sections = _restart_sections(
        old_memory_fingerprint=old_memory_fingerprint,
        old_channels_fingerprint=old_channels_fingerprint,
        old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
        new_config=new_config,
    )
    live_applied = _live_applied_sections(
        old_dump, _config_dump(new_config), restart_sections
    )
    return {
        "restartRequired": bool(restart_sections),
        "restartSections": restart_sections,
        "liveApplied": live_applied,
    }


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
    from opensquilla.tools.builtin.media import configure_audio, configure_image_generation

    configure_image_generation(
        getattr(config, "image_generation", None),
        llm_config=getattr(config, "llm", None),
        squilla_router_config=getattr(config, "squilla_router", None),
    )
    configure_audio(getattr(config, "audio", None))


def _sync_model_catalog_overrides(config: Any) -> None:
    """Re-apply ``[models.*]`` overrides onto the shared catalog.

    ``ModelCatalog`` is a boot-constructed singleton (see
    ``gateway.boot.build_services``); without this, a live ``[models.*]``
    edit made via ``config.set``/``patch``/``apply`` or ``opensquilla gateway
    reload`` would hot-apply into the config object but silently keep
    resolving prices/capabilities from the stale override snapshot until a
    full restart.
    """
    from opensquilla.gateway.boot import apply_model_catalog_overrides
    from opensquilla.provider.model_catalog import shared_catalog

    apply_model_catalog_overrides(shared_catalog(), config)


# Read-only paths that cannot be modified via config.set/patch/apply.
# config_version is the migration stamp owned by migrate_config_payload;
# client writes to it could re-run or skip one-time migrations.
_READONLY_PATHS = frozenset({"auth.token", "auth.password", "config_version"})
_SAFE_WRITE_PATCH_PATHS = frozenset(
    {
        "skills.filter_enabled",
        "skills.filter_lexical_top_n",
        "skills.filter_semantic_top_n",
        "skills.filter_rrf_k",
        "skills.disabled",
        "skills.coding_mode",
        "llm_ensemble.enabled",
        "naming.enabled",
        "privacy.disable_network_observability",
        "prompt_cache.mode",
        "squilla_router.enabled",
        "squilla_router.rollout_phase",
        "squilla_router.strategy",
        "squilla_router.visual_mode",
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
    old_dump = copy.deepcopy(cfg_dict) if isinstance(cfg_dict, dict) else {}
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
    explicit_paths = {path} | _collect_paths(value, path)
    inherit_then_clear_explicit(ctx.config, new_config, explicit_paths - redacted_paths)
    _sync_provider_selector(ctx, new_config)
    _update_config_in_place(ctx.config, new_config)
    _sync_image_generation(new_config)
    _sync_model_catalog_overrides(new_config)
    _persist_config(ctx.config)
    return _change_meta(
        old_memory_fingerprint=old_memory_fingerprint,
        old_channels_fingerprint=old_channels_fingerprint,
        old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
        old_dump=old_dump,
        new_config=new_config,
    )


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
    inherit_then_clear_explicit(ctx.config, new_config, explicit_paths - redacted_paths)

    _sync_provider_selector(ctx, new_config)
    # Update in-memory config so subsequent requests see changes immediately
    _update_config_in_place(ctx.config, new_config)
    _sync_image_generation(new_config)
    _sync_model_catalog_overrides(new_config)

    _persist_config(ctx.config)
    change_meta = _change_meta(
        old_memory_fingerprint=old_memory_fingerprint,
        old_channels_fingerprint=old_channels_fingerprint,
        old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
        old_dump=source_cfg_dict,
        new_config=new_config,
    )
    return {
        "patched": list(dot_patches.keys()) + (["(merge)"] if patch_data else []),
        **change_meta,
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
    config_payload = _strip_public_derived_config_fields(config_payload)

    # Validate and persist the full replacement config
    new_config = GatewayConfig(**config_payload)
    _validate_memory_embedding_semantics(new_config)
    inherit_then_clear_explicit(
        ctx.config, new_config, _collect_paths(config_payload) - redacted_paths
    )
    _sync_provider_selector(ctx, new_config)
    if ctx.config is not None:
        _update_config_in_place(ctx.config, new_config)
    _sync_image_generation(new_config)
    _sync_model_catalog_overrides(new_config)
    _persist_config(ctx.config if ctx.config is not None else new_config)
    return _change_meta(
        old_memory_fingerprint=old_memory_fingerprint,
        old_channels_fingerprint=old_channels_fingerprint,
        old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
        old_dump=old_payload if isinstance(old_payload, dict) else {},
        new_config=new_config,
    )


def _get_config_attr(config: Any, path: str) -> Any:
    """Walk a dot-separated attribute path on a config model."""
    obj: Any = config
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _set_config_attr(config: Any, path: str, value: Any) -> None:
    """Set a dot-separated attribute path on a config model."""
    parts = path.split(".")
    obj: Any = config
    for part in parts[:-1]:
        obj = getattr(obj, part, None)
        if obj is None:
            return
    setattr(obj, parts[-1], value)


@_d.method("config.reload", scope="operator.admin")
async def _handle_config_reload(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Re-read the on-disk config file and hot-apply it (validate, then apply).

    Hand-edited TOML is otherwise only read at boot; this handler gives
    ``opensquilla gateway reload`` the same hot-apply path the RPC writers
    have. Semantics are validate-then-apply-or-rollback: the candidate is
    built and validated from disk first, and on any failure the live
    ``ctx.config`` object is left untouched (same object identity, same
    values) and an ``{"ok": false, "error": ...}`` payload is returned.

    Sequence (order is load-bearing for secret handling):

    1. Build the candidate with ``onboarding.config_store.load_config`` —
       it migrates, validates, stamps ``config_path``, and re-marks
       ``llm.api_key`` as a runtime secret only when the TOML omits it.
       Runtime-secret markers are deliberately NOT inherited from the old
       config: a stale marker would make the next persist silently drop an
       operator's newly hand-written on-disk ``llm.api_key``
       (``to_toml_dict`` deletes marked paths).
    2. Restore boot-generated, non-reconstructible secrets by value AND
       marker: any path in the old config's runtime-secret set that is empty
       in the candidate and read-only for writers (today exactly
       ``auth.token``) is copied over and re-marked so a later persist can
       never write it to disk.
    3. ``_sync_provider_selector`` runs on the CANDIDATE before the in-place
       swap: it re-resolves provider env keys onto the candidate and re-marks
       ``llm.api_key`` when the key came from the environment. Running it
       after the swap would leave an empty api_key with an empty marker set,
       and a later persist could leak an env key to disk.
    4. ``_update_config_in_place`` swaps values + markers into ``ctx.config``,
       then ``_sync_image_generation`` refreshes media tooling.

    Reload is read-only against disk: it never persists the config file.

    Honesty notes (mirrored in ``opensquilla.toml.example``): the restart
    fingerprints cover only memory (retrieval mode + embedding), channels,
    and sandbox posture (permissions + sandbox). Boot-only sections outside
    those fingerprints — auth, host/port binding, file logging, and the
    search provider wiring — are blind spots: they hot-apply into
    ``ctx.config`` (and so may appear in ``liveApplied``) but components
    constructed at boot keep their old values until a real restart. Neither
    this handler nor ``config.set``/``config.patch`` live-syncs the search
    provider.
    """
    if ctx.config is None:
        raise ValueError("No config available")

    from opensquilla.onboarding.config_store import load_config, resolve_config_path

    target, _source = resolve_config_path(getattr(ctx.config, "config_path", None) or None)
    try:
        candidate = load_config(target)
        _validate_memory_embedding_semantics(candidate)
    except Exception as exc:  # noqa: BLE001 — rollback contract: config untouched
        return {"ok": False, "path": str(target), "error": str(exc)}

    old_memory_fingerprint = _memory_restart_fingerprint(ctx.config)
    old_channels_fingerprint = _channels_restart_fingerprint(ctx.config)
    old_sandbox_posture_fingerprint = _sandbox_posture_restart_fingerprint(ctx.config)
    old_dump = _config_dump(ctx.config)

    # Step 2: carry forward boot-generated secrets the disk cannot restore.
    old_secret_paths = set(getattr(ctx.config, "_runtime_secret_paths", set()))
    for path in sorted(old_secret_paths & _READONLY_PATHS):
        if _get_config_attr(candidate, path):
            continue
        old_value = _get_config_attr(ctx.config, path)
        if not old_value:
            continue
        _set_config_attr(candidate, path, old_value)
        candidate.mark_runtime_secret(path)

    # Step 3: selector sync on the candidate BEFORE the in-place swap.
    _sync_provider_selector(ctx, candidate)

    change_meta = _change_meta(
        old_memory_fingerprint=old_memory_fingerprint,
        old_channels_fingerprint=old_channels_fingerprint,
        old_sandbox_posture_fingerprint=old_sandbox_posture_fingerprint,
        old_dump=old_dump,
        new_config=candidate,
    )

    # Step 4: swap values + runtime-secret markers into the live config.
    _update_config_in_place(ctx.config, candidate)
    _sync_image_generation(candidate)
    _sync_model_catalog_overrides(candidate)

    return {"ok": True, "path": str(target), **change_meta}


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


@_d.method("config.effective", scope="operator.read")
async def _handle_config_effective(params: dict | None, ctx: RpcContext) -> dict[str, Any]:
    """Effective LLM routing values with per-field provenance.

    Wire shape (public contract, frozen by
    tests/test_contracts/test_config_effective_wire.py)::

        {"fields": {"llm.model": {"value": ..., "source": "config"}, ...}}

    Redaction: the resolver's field allowlist excludes secret-named fields
    by construction, and this handler is belt-and-braces on top of that.
    A flat ``{path, value, source}`` record defeats key-name redaction —
    ``redact_public_config`` masks by dict KEY, and here the dict key is
    literally ``"value"`` — so the secret-name check runs per dotted PATH
    segment instead: a field whose path contains a secret-named segment is
    dropped entirely. Raw values are additionally run through
    ``redact_public_config`` BEFORE provenance-wrapping so that any
    container-shaped value has secret-named members masked.
    """
    if ctx.config is None:
        raise ValueError("No config available")

    from opensquilla.gateway.config import is_sensitive_config_key, redact_public_config
    from opensquilla.provider.model_catalog import shared_catalog
    from opensquilla.provider.resolution import resolve_effective_llm

    resolved = resolve_effective_llm(ctx.config, shared_catalog())
    fields: dict[str, dict[str, Any]] = {}
    for path, field in resolved.items():
        if any(is_sensitive_config_key(segment) for segment in path.split(".")):
            continue
        fields[path] = {
            "value": redact_public_config(field.value),
            "source": field.source,
        }
    return {"fields": fields}
