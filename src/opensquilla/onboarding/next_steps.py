"""Secret-safe next-step text for onboarding output."""

from __future__ import annotations

import os
import platform
import shlex
from pathlib import Path
from typing import Any

from opensquilla.onboarding.image_generation_specs import (
    get_image_generation_provider_setup_spec,
)
from opensquilla.onboarding.search_specs import get_search_provider_setup_spec
from opensquilla.onboarding.setup_paths import web_setup_url
from opensquilla.onboarding.status import get_onboarding_status

_KEY_URLS = {
    "openrouter": "https://openrouter.ai/keys",
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "deepseek": "https://platform.deepseek.com/api_keys",
}
_CAPABILITY_SECTIONS = (
    "search",
    "channels",
    "image_generation",
    "audio",
    "memory_embedding",
)
_CAPABILITY_STATUS_DISPLAY = {
    "ok": "Ready",
    "optional": "Later",
    "missing": "Missing",
    "degraded": "Needs action",
    "unknown": "Check",
}
_HEADLESS_SECTION_ALIASES = {
    "llm": "provider",
    "providers": "provider",
    "channel": "channels",
    "image_generation": "image-generation",
    "audio": "audio",
    "memory_embedding": "memory-embedding",
}
_HEADLESS_SETUP_COMMANDS = {
    "provider": (
        "Provider recipes",
        "opensquilla onboard catalog providers",
    ),
    "router": (
        "Headless router",
        "opensquilla onboard configure router --router recommended --default-tier c1",
    ),
    "channels": (
        "Channel recipes",
        "opensquilla onboard catalog channels",
    ),
    "search": (
        "Headless search",
        "opensquilla onboard configure search --search-provider duckduckgo",
    ),
    "image-generation": (
        "Image recipes",
        "opensquilla onboard catalog image",
    ),
    "audio": (
        "Audio recipes",
        "opensquilla onboard catalog audio",
    ),
    "memory-embedding": (
        "Headless memory embedding",
        "opensquilla onboard configure memory --memory-provider auto",
    ),
}


def _normalize_headless_section(section: str) -> str:
    normalized = section.strip().lower().replace("_", "-")
    return _HEADLESS_SECTION_ALIASES.get(normalized, normalized)


def headless_setup_commands(section: str) -> list[tuple[str, str]]:
    normalized = _normalize_headless_section(section)
    commands: list[tuple[str, str]] = []
    entry = _HEADLESS_SETUP_COMMANDS.get(normalized)
    if entry:
        commands.append(entry)
    return commands


def headless_setup_command(section: str) -> tuple[str, str] | None:
    commands = headless_setup_commands(section)
    return commands[-1] if commands else None


def setup_catalog_command(config_arg: str = "") -> tuple[str, str]:
    return "Explore options", f"opensquilla onboard catalog{config_arg}"


def set_env_hint(env_key: str) -> str:
    if platform.system().lower().startswith("win"):
        return f'PowerShell: $env:{env_key} = "<your-key>"'
    return f'export {env_key}="<your-key>"'


def _set_env_hint(env_key: str) -> str:
    return set_env_hint(env_key)


def env_recovery_commands(status: Any) -> list[dict[str, str]]:
    candidates = [
        ("llm", "Set provider key", status.llm_source, status.llm_env_key),
        ("search", "Set search key", status.search_source, status.search_env_key),
        (
            "image_generation",
            "Set image key",
            status.image_generation_source,
            status.image_generation_env_key,
        ),
        ("audio", "Set audio key", status.audio_source, status.audio_env_key),
        (
            "memory_embedding",
            "Set memory key",
            status.memory_embedding_source,
            status.memory_embedding_env_key,
        ),
    ]
    seen_env_keys: set[str] = set()

    def priority(
        item: tuple[int, tuple[str, str, str, str]],
    ) -> tuple[int, int]:
        index, (section, _label, _source, _env_key) = item
        detail = status.section_details.get(section, {})
        return (0 if detail.get("blocking") else 1, index)

    commands: list[dict[str, str]] = []
    for _index, (section, label, source, env_key) in sorted(
        enumerate(candidates),
        key=priority,
    ):
        if source != "missing_env" or not env_key or env_key in seen_env_keys:
            continue
        seen_env_keys.add(env_key)
        commands.append(
            {
                "section": section,
                "label": label,
                "command": set_env_hint(env_key),
            }
        )
    return commands


def _missing_env_warning(surface: str, env_key: str) -> str:
    return (
        f"{surface}: ${env_key} is not set in this shell. "
        "The config saved the environment-variable reference, but this feature "
        "will not work until the gateway is started with that variable set."
    )


def _config_cli_arg(config_path: str | Path | None) -> str:
    if not config_path:
        return ""
    return f" --config {shlex.quote(str(config_path))}"


def _image_generation_provider_id(config: Any) -> str:
    primary = str(getattr(config.image_generation, "primary", "") or "")
    provider_id, sep, _model = primary.partition("/")
    if sep and provider_id:
        return provider_id
    return "openai"


def _capabilities_summary(status: Any) -> str:
    parts: list[str] = []
    for name in _CAPABILITY_SECTIONS:
        detail = status.section_details.get(name, {})
        label = str(detail.get("label") or name.replace("_", " ").title())
        if detail.get("blocking") or detail.get("actionRequired"):
            display = "Needs action"
        else:
            state = status.sections.get(name)
            value = str(getattr(state, "value", detail.get("status") or "optional"))
            display = _CAPABILITY_STATUS_DISPLAY.get(value, value.replace("_", " ").title())
        parts.append(f"{label}={display}")
    return " | ".join(parts)


def env_reference_warnings(config: Any) -> list[str]:
    """Return operator-facing warnings for saved env references not visible now."""
    warnings: list[str] = []
    status = get_onboarding_status(config)

    llm = config.llm
    llm_env_key = str(getattr(llm, "api_key_env", "") or "")
    if status.llm_source == "missing_env" and llm_env_key:
        warnings.append(_missing_env_warning("LLM provider", llm_env_key))

    search_provider = str(getattr(config, "search_provider", "") or "")
    search_env_key = str(getattr(config, "search_api_key_env", "") or "")
    if search_provider and search_env_key and not getattr(config, "search_api_key", ""):
        try:
            search_spec = get_search_provider_setup_spec(search_provider)
        except KeyError:
            search_spec = None
        if (
            search_spec is not None
            and search_spec.requires_api_key
            and not os.environ.get(search_env_key)
        ):
            warnings.append(_missing_env_warning("Search provider", search_env_key))

    if status.image_generation_enabled and not status.image_generation_configured:
        provider_id = _image_generation_provider_id(config)
        try:
            image_spec = get_image_generation_provider_setup_spec(provider_id)
        except KeyError:
            image_spec = None
        providers = getattr(getattr(config, "image_generation", None), "providers", None)
        provider_cfg = getattr(providers, provider_id, None) if providers is not None else None
        image_env_key = str(getattr(provider_cfg, "api_key_env", "") or "").strip()
        if not image_env_key and image_spec is not None:
            image_env_key = str(getattr(image_spec, "env_key", "") or "").strip()
        if image_env_key and not os.environ.get(image_env_key):
            warnings.append(_missing_env_warning("Image generation provider", image_env_key))

    audio = getattr(config, "audio", None)
    if getattr(audio, "enabled", False) and not status.audio_configured:
        providers = getattr(audio, "providers", None)
        provider_cfg = getattr(providers, "elevenlabs", None) if providers is not None else None
        audio_env_key = str(getattr(provider_cfg, "api_key_env", "") or "").strip()
        if audio_env_key and not os.environ.get(audio_env_key):
            warnings.append(_missing_env_warning("Audio provider", audio_env_key))

    embedding = getattr(getattr(config, "memory", None), "embedding", None)
    embedding_provider = str(getattr(embedding, "requested_provider", "") or "")
    if embedding_provider in {"openai", "openai-compatible"}:
        remote = getattr(embedding, "remote", None)
        memory_env_key = str(getattr(remote, "api_key_env", "") or "").strip()
        memory_key = str(getattr(remote, "api_key", "") or "") or str(
            getattr(embedding, "api_key", "") or ""
        )
        if memory_env_key and not memory_key and not os.environ.get(memory_env_key):
            warnings.append(_missing_env_warning("Memory embedding", memory_env_key))

    return warnings


def format_next_steps(config: Any, *, config_path: str | Path | None = None) -> str:
    status = get_onboarding_status(config)
    llm = config.llm
    router = config.squilla_router
    path = str(config_path or status.config_path or getattr(config, "config_path", ""))
    provider = str(getattr(llm, "provider", "") or "")
    model = str(getattr(llm, "model", "") or "")
    env_key = str(getattr(llm, "api_key_env", "") or "")
    router_default = str(getattr(router, "default_tier", "") or "c1")
    router_line = (
        "  Router: disabled"
        if not router.enabled
        else f"  Router: SquillaRouter, default={router_default}"
    )
    config_arg = _config_cli_arg(config_path)
    key_source = status.llm_source
    if key_source == "env" and env_key:
        key_line = f"Key: ${env_key}"
    elif key_source == "missing_env" and env_key:
        key_line = f"Key: ${env_key} is not set in this shell"
    elif key_source == "explicit":
        key_line = "Key: stored in config"
    else:
        key_line = "Key: not required" if status.llm_configured else "Key: not configured"

    lines = [
        "Configuration summary:",
        f"  Config: {path}",
        f"  LLM: {provider} / {model}",
        f"  {key_line}",
        router_line,
        f"  Capabilities: {_capabilities_summary(status)}",
        "",
        "Commands:",
        f"  Run gateway now: opensquilla gateway run{config_arg}",
        f"  Start gateway in background: opensquilla gateway start --json{config_arg}",
        f"  Restart running gateway: opensquilla gateway restart --json{config_arg}",
    ]
    if key_source == "missing_env" and env_key:
        lines.append(f"  Set key before starting gateway: {set_env_hint(env_key)}")
    lines.extend(["", "Reference:"])
    setup_url = web_setup_url(config)
    if setup_url:
        lines.append(f"  Web UI: {setup_url}")
    key_url = _KEY_URLS.get(provider)
    if key_url:
        lines.append(f"  Provider keys: {key_url}")
    return "\n".join(lines)
