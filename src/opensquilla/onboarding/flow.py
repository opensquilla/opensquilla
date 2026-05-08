"""Coordinate interactive and non-interactive onboarding flows."""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from typing import Any

from opensquilla.cli.ui import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_SOFT,
    banner_panel,
    console,
    markup_escape,
    questionary_style,
    warning_panel,
)
from opensquilla.onboarding.channel_specs import (
    ChannelSetupField,
    ChannelSetupSpec,
    get_channel_setup_spec,
    list_channel_setup_specs,
)
from opensquilla.onboarding.config_store import (
    PersistResult,
    default_config_path,
    load_config,
    persist_config,
)
from opensquilla.onboarding.image_generation_specs import (
    ImageGenerationProviderSetupSpec,
    get_image_generation_provider_setup_spec,
    list_image_generation_provider_setup_specs,
)
from opensquilla.onboarding.mutations import (
    upsert_channel,
    upsert_image_generation_provider,
    upsert_llm_provider,
    upsert_router,
    upsert_search_provider,
)
from opensquilla.onboarding.provider_specs import (
    get_provider_setup_spec,
    list_provider_setup_specs,
)
from opensquilla.onboarding.search_specs import (
    get_search_provider_setup_spec,
    list_search_provider_setup_specs,
)
from opensquilla.onboarding.status import get_onboarding_status

_QSTYLE = None


def _qs():
    global _QSTYLE
    if _QSTYLE is None:
        built = questionary_style()
        if built is None:
            return None
        _QSTYLE = built
    return _QSTYLE


def _styled(q):
    """Wrap the questionary module so every prompt inherits the brand style.

    When ``questionary_style()`` returns ``None`` (e.g. test stub or missing
    optional dep) the wrapper passes calls through unchanged.
    """
    from types import SimpleNamespace

    style = _qs()
    if style is None:
        return q

    def _wrap(name):
        fn = getattr(q, name)
        return lambda *a, **kw: fn(*a, **{"style": style, **kw})

    return SimpleNamespace(
        select=_wrap("select"),
        text=_wrap("text"),
        confirm=_wrap("confirm"),
        password=_wrap("password"),
    )


@dataclass(frozen=True)
class OnboardOptions:
    skip_channels: bool = False
    skip_search: bool = False
    skip_image_generation: bool = False
    if_needed: bool = False
    provider_id: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    router_mode: str = "recommended"
    minimal: bool = False


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_noninteractive_provider_configure(
    provider_id: str, values: dict[str, Any]
) -> PersistResult:
    from opensquilla.onboarding.setup_engine import SetupEngine

    engine = SetupEngine()
    engine.apply(
        "provider",
        {
            "providerId": provider_id,
            "model": values.get("model", ""),
            "apiKey": values.get("api_key", ""),
            "apiKeyEnv": values.get("api_key_env", ""),
            "baseUrl": values.get("base_url", ""),
            "proxy": values.get("proxy", ""),
        },
    )
    router_mode = values.get("router", "")
    if router_mode:
        engine.apply("router", {"mode": router_mode})
    return engine.persist()


def run_noninteractive_channel_add(
    type_name: str, values: dict[str, Any]
) -> PersistResult:
    cfg = load_config()
    payload = {"type": type_name, **values}
    result = upsert_channel(cfg, entry_payload=payload)
    return persist_config(result.config, restart_required=True)


def run_noninteractive_search_configure(
    provider_id: str, values: dict[str, Any]
) -> PersistResult:
    cfg = load_config()
    result = upsert_search_provider(
        cfg,
        provider_id=provider_id,
        api_key=values.get("api_key", ""),
        api_key_env=values.get("api_key_env", ""),
        max_results=int(values.get("max_results", 5)),
        proxy=values.get("proxy", ""),
        use_env_proxy=bool(values.get("use_env_proxy", False)),
        fallback_policy=values.get("fallback_policy", "off"),
        diagnostics=bool(values.get("diagnostics", False)),
    )
    return persist_config(result.config, restart_required=False)


def _print_noninteractive_hint() -> PersistResult:
    print(
        "Onboarding requires a TTY. Run a non-interactive equivalent, e.g.:\n"
        "  opensquilla onboard --provider openrouter "
        "--api-key-env OPENROUTER_API_KEY --router recommended --minimal\n"
        "  opensquilla search configure brave --api-key $BRAVE_SEARCH_API_KEY\n"
        "  opensquilla channels add slack --name work --token $SLACK_TOKEN"
    )
    return PersistResult(
        path=default_config_path(),
        backup_path=None,
        restart_required=False,
        warnings=["tty_required"],
    )


def _ask_provider_choice(questionary, options: OnboardOptions):
    if options.provider_id:
        spec = get_provider_setup_spec(options.provider_id)
        return spec, spec.provider_id
    supported = [s for s in list_provider_setup_specs() if s.runtime_supported]
    pid = questionary.select(
        "LLM provider",
        choices=[f"{s.provider_id} ({s.label})" for s in supported],
    ).ask()
    pid_clean = pid.split(" ")[0]
    return get_provider_setup_spec(pid_clean), pid_clean


def _ask_provider_fields(
    questionary, spec, options: OnboardOptions
) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    if options.model:
        answers["model"] = options.model
    elif getattr(spec, "router_supported", False):
        answers["model"] = ""
    else:
        answers["model"] = questionary.text("Model id").ask() or ""
    if spec.requires_api_key:
        env_key = options.api_key_env or spec.env_key
        if options.api_key:
            answers["api_key"] = options.api_key
            answers["api_key_env"] = ""
        elif options.api_key_env:
            answers["api_key"] = ""
            answers["api_key_env"] = options.api_key_env
        elif env_key and os.environ.get(env_key):
            use_env = questionary.confirm(
                (
                    f"Use {env_key} from this shell instead of storing the API key "
                    "in config? Detected now."
                ),
                default=True,
            ).ask()
            answers["api_key"] = ""
            answers["api_key_env"] = env_key if use_env else ""
            if not use_env:
                answers["api_key"] = questionary.password("API key").ask() or ""
        else:
            use_env_ref = questionary.confirm(
                (
                    f"Use {env_key or 'an environment variable'} instead of storing "
                    "the API key in config? Not set now; set it before starting "
                    "the gateway."
                ),
                default=True,
            ).ask()
            if use_env_ref:
                answers["api_key"] = ""
                answers["api_key_env"] = (
                    questionary.text(
                        "API key environment variable",
                        default=env_key or "",
                    ).ask()
                    or ""
                )
            else:
                answers["api_key"] = questionary.password("API key").ask() or ""
                answers["api_key_env"] = ""
    else:
        answers["api_key"] = options.api_key or ""
        answers["api_key_env"] = ""
    if spec.requires_base_url:
        answers["base_url"] = options.base_url or (
            questionary.text("Base URL", default=spec.default_base_url).ask() or ""
        )
    else:
        answers["base_url"] = options.base_url or spec.default_base_url
    return answers


def _ask_search_choice(questionary):
    supported = [s for s in list_search_provider_setup_specs() if s.runtime_supported]
    provider_id = questionary.select(
        "Search provider",
        choices=[f"{s.provider_id} ({s.label})" for s in supported],
    ).ask()
    provider_id_clean = provider_id.split(" ")[0]
    return get_search_provider_setup_spec(provider_id_clean), provider_id_clean


def _ask_search_fields(questionary, spec) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    if spec.requires_api_key:
        env_key = spec.env_key or ""
        env_choice = f"Use environment variable {env_key}"
        paste_choice = "Paste API key now"
        key_source = questionary.select(
            "Search API key source",
            choices=([env_choice] if env_key else []) + [paste_choice],
            default=env_choice if env_key else paste_choice,
        ).ask()
        if key_source == env_choice and env_key:
            answers["api_key"] = ""
            answers["api_key_env"] = env_key
        else:
            answers["api_key"] = questionary.password("Search API key").ask() or ""
            answers["api_key_env"] = ""
    else:
        answers["api_key"] = ""
        answers["api_key_env"] = ""
    max_results = questionary.text("Max search results", default="5").ask() or "5"
    answers["max_results"] = int(max_results)
    answers["proxy"] = questionary.text("Search HTTP proxy", default="").ask() or ""
    answers["use_env_proxy"] = questionary.confirm(
        "Use environment proxy for search?", default=False
    ).ask()
    fallback_choice = questionary.select(
        "Search fallback policy",
        choices=list(_SEARCH_FALLBACK_LABELS.values()),
        default=_SEARCH_FALLBACK_LABELS["off"],
    ).ask()
    answers["fallback_policy"] = _search_fallback_choice_to_value(fallback_choice)
    answers["diagnostics"] = questionary.confirm(
        _SEARCH_DIAGNOSTICS_PROMPT, default=False
    ).ask()
    return answers


def run_interactive_search_configure() -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint()

    import questionary as _qmod
    questionary = _styled(_qmod)

    console.print(banner_panel("Search Setup", "Wire a web search provider"))
    spec, provider_id = _ask_search_choice(questionary)
    answers = _ask_search_fields(questionary, spec)
    cfg = load_config()
    result = upsert_search_provider(
        cfg,
        provider_id=provider_id,
        api_key=answers.get("api_key", ""),
        api_key_env=answers.get("api_key_env", ""),
        max_results=answers["max_results"],
        proxy=answers.get("proxy", ""),
        use_env_proxy=answers.get("use_env_proxy", False),
        fallback_policy=answers.get("fallback_policy", "off"),
        diagnostics=answers.get("diagnostics", False),
    )
    return persist_config(result.config, restart_required=False)


def _image_generation_choice_label(spec: ImageGenerationProviderSetupSpec) -> str:
    return f"{spec.provider_id} ({spec.label})"


def _image_generation_choice_to_provider_id(choice: str) -> str:
    return choice.split(" ")[0]


def _preferred_image_generation_provider_id(config) -> str | None:
    provider_id = str(getattr(config.llm, "provider", "") or "")
    supported = {
        spec.provider_id
        for spec in list_image_generation_provider_setup_specs()
        if spec.runtime_supported
    }
    return provider_id if provider_id in supported else None


def _ask_image_generation_choice(questionary, config):
    supported = [
        spec
        for spec in list_image_generation_provider_setup_specs()
        if spec.runtime_supported
    ]
    preferred = _preferred_image_generation_provider_id(config)
    default_spec = next(
        (spec for spec in supported if spec.provider_id == preferred),
        supported[0],
    )
    selected = questionary.select(
        "Image generation provider",
        choices=[_image_generation_choice_label(spec) for spec in supported],
        default=_image_generation_choice_label(default_spec),
    ).ask()
    provider_id = _image_generation_choice_to_provider_id(selected)
    return get_image_generation_provider_setup_spec(provider_id), provider_id


def _ask_image_generation_fields(
    questionary,
    spec: ImageGenerationProviderSetupSpec,
    config,
) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    answers["primary"] = (
        questionary.text("Primary image model", default=spec.default_model).ask()
        or spec.default_model
    )

    key_choices: list[str] = []
    env_choice = f"Use environment variable {spec.env_key}" if spec.env_key else ""
    if env_choice and os.environ.get(spec.env_key):
        key_choices.append(env_choice)
    llm_choice = "Reuse matching LLM provider key"
    if config.llm.provider == spec.provider_id and config.llm.api_key:
        key_choices.append(llm_choice)
    paste_choice = "Paste API key now"
    key_choices.append(paste_choice)

    key_source = questionary.select(
        "Image API key source",
        choices=key_choices,
        default=key_choices[0],
    ).ask()
    if key_source == paste_choice:
        answers["api_key"] = questionary.password("Image API key").ask() or ""
    else:
        answers["api_key"] = ""

    answers["base_url"] = (
        questionary.text("Image base URL", default=spec.default_base_url).ask()
        or spec.default_base_url
    )
    answers["enabled"] = questionary.confirm(
        "Image generation enabled?", default=True
    ).ask()
    return answers


def _print_image_generation_intro(spec: ImageGenerationProviderSetupSpec) -> None:
    console.print(
        f"[bold {ACCENT}]▌[/] [bold]Image generation[/]"
        f" [dim]· {markup_escape(spec.label)}[/dim]"
    )
    console.print(
        f"  [dim]Enables the [{ACCENT_SOFT}]image_generate[/] tool for new turns "
        "when the gateway can see the selected provider key.[/dim]"
    )


def _print_image_generation_saved(provider_id: str) -> None:
    console.print(
        f"[bold {ACCENT}]◆[/] [bold]Image generation configured.[/]"
    )
    console.print(
        f"  [dim]Provider:[/dim] [{ACCENT_SOFT}]{markup_escape(provider_id)}[/]"
        " [dim]· start a new turn after the gateway can see the key[/dim]"
    )


def run_interactive_image_generation_configure() -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint()

    import questionary as _qmod
    questionary = _styled(_qmod)

    cfg = load_config()
    spec, provider_id = _ask_image_generation_choice(questionary, cfg)
    _print_image_generation_intro(spec)
    answers = _ask_image_generation_fields(questionary, spec, cfg)
    result = upsert_image_generation_provider(
        cfg,
        provider_id=provider_id,
        primary=answers.get("primary", ""),
        api_key=answers.get("api_key", ""),
        base_url=answers.get("base_url", ""),
        enabled=bool(answers.get("enabled", True)),
    )
    persisted = persist_config(result.config, restart_required=False)
    _print_image_generation_saved(provider_id)
    return persisted


_TEXT_ROUTER_TIERS = ("t0", "t1", "t2", "t3")
_EXPOSED_ROUTER_TIERS = ("t0", "t1", "t2", "t3", "image_model")
_TEXT_TIER_LABELS = {
    "t0": "Fast/simple (t0)",
    "t1": "Balanced default (t1)",
    "t2": "Stronger reasoning (t2)",
    "t3": "Max quality (t3)",
}
_IMAGE_TIER_LABEL = "Image model"
_DONE_LABEL = "Done"


_ROUTER_MODE_LABEL = "SquillaRouter"
_ROUTER_DISABLED_LABEL = "Disabled"
_SEARCH_FALLBACK_LABELS = {
    "off": "off - no fallback; surface the original provider error",
    "network": "network - retry with DuckDuckGo on timeout/network errors",
}
_SEARCH_DIAGNOSTICS_PROMPT = (
    "Enable search diagnostics? Include provider attempt/error details "
    "for troubleshooting?"
)


def _search_fallback_choice_to_value(choice: str | None) -> str:
    for value, label in _SEARCH_FALLBACK_LABELS.items():
        if choice == label or choice == value:
            return value
    return "off"


def _router_mode_choices(provider_id: str) -> list[str]:
    return [_ROUTER_MODE_LABEL, _ROUTER_DISABLED_LABEL]


def _router_mode_default(provider_id: str, requested: str) -> str:
    if requested == "disabled":
        return _ROUTER_DISABLED_LABEL
    return _ROUTER_MODE_LABEL


def _router_mode_to_internal(selected: str | None) -> str:
    if selected == _ROUTER_DISABLED_LABEL:
        return "disabled"
    return "recommended"


def _text_tier_label(tier: str | None) -> str:
    return _TEXT_TIER_LABELS.get(str(tier or "t1"), _TEXT_TIER_LABELS["t1"])


def _text_tier_to_internal(selected: str | None) -> str:
    if selected in _TEXT_ROUTER_TIERS:
        return str(selected)
    for tier, label in _TEXT_TIER_LABELS.items():
        if selected == label:
            return tier
    return "t1"


def _tier_choice_label(tier: str) -> str:
    if tier == "image_model":
        return _IMAGE_TIER_LABEL
    return _text_tier_label(tier)


def _tier_choice_to_internal(selected: str | None) -> str | None:
    if not selected or selected == _DONE_LABEL:
        return None
    if selected == _IMAGE_TIER_LABEL:
        return "image_model"
    if selected in _EXPOSED_ROUTER_TIERS:
        return str(selected)
    for tier_name in _EXPOSED_ROUTER_TIERS:
        if selected == _tier_choice_label(tier_name):
            return tier_name
    return None


def _print_router_defaults(config) -> None:
    router = config.squilla_router
    if not getattr(router, "enabled", True):
        console.print(
            f"[{ACCENT_DIM}]router[/] [dim]disabled — requests bypass tier routing[/dim]"
        )
        return
    default_tier = str(getattr(router, "default_tier", "t1") or "t1")
    default = router.tiers.get(default_tier, {})
    console.print(
        f"[bold {ACCENT}]◆ router[/] "
        f"[dim]default[/] [{ACCENT_SOFT}]{default_tier}[/] "
        f"[dim]→[/] {markup_escape(default.get('provider', ''))}"
        f"[dim]/[/]{markup_escape(default.get('model', ''))}"
    )
    for tier_name in _EXPOSED_ROUTER_TIERS:
        tier = router.tiers.get(tier_name)
        if not isinstance(tier, dict):
            continue
        marker = (
            f"[{ACCENT}]●[/]" if tier_name == default_tier else f"[{ACCENT_DIM}]○[/]"
        )
        console.print(
            f"  {marker} [{ACCENT_SOFT}]{tier_name:<11}[/]"
            f" [dim]{markup_escape(tier.get('provider', ''))}/"
            f"{markup_escape(tier.get('model', ''))}[/dim]"
        )


def _router_tier_overrides(questionary, config) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    choices = [_DONE_LABEL] + [
        _tier_choice_label(tier_name)
        for tier_name in _EXPOSED_ROUTER_TIERS
        if isinstance(config.squilla_router.tiers.get(tier_name), dict)
    ]
    while True:
        selected = questionary.select(
            "Tier to edit",
            choices=choices,
            default=_DONE_LABEL,
        ).ask()
        tier_name = _tier_choice_to_internal(selected)
        if not tier_name:
            break
        tier = config.squilla_router.tiers.get(tier_name)
        if not isinstance(tier, dict):
            continue
        provider = questionary.text(
            f"{tier_name} provider",
            default=str(tier.get("provider") or ""),
        ).ask() or str(tier.get("provider") or "")
        model = questionary.text(
            f"{tier_name} model",
            default=str(tier.get("model") or ""),
        ).ask() or str(tier.get("model") or "")
        overrides[tier_name] = {"provider": provider, "model": model}
        if tier_name == "image_model":
            overrides[tier_name]["supportsImage"] = True
    return overrides


def _ask_router_fields(
    questionary,
    config,
    *,
    provider_id: str,
    requested_mode: str,
) -> dict[str, Any]:
    choices = _router_mode_choices(provider_id)
    selected_mode = questionary.select(
        "Router mode",
        choices=choices,
        default=_router_mode_default(provider_id, requested_mode),
    ).ask()
    mode = _router_mode_to_internal(selected_mode)
    if mode == "disabled":
        preview = upsert_router(config, mode=mode).config
        _print_router_defaults(preview)
        return {"mode": mode}

    preview = upsert_router(config, mode=mode).config
    _print_router_defaults(preview)
    default_tier_choice = questionary.select(
        "Default text model",
        choices=[_TEXT_TIER_LABELS[tier] for tier in _TEXT_ROUTER_TIERS],
        default=_text_tier_label(str(preview.squilla_router.default_tier or "t1")),
    ).ask()
    default_tier = _text_tier_to_internal(default_tier_choice)
    preview = upsert_router(config, mode=mode, default_tier=default_tier).config
    _print_router_defaults(preview)

    payload: dict[str, Any] = {"mode": mode, "defaultTier": default_tier}
    if questionary.confirm("Edit router tier models now?", default=False).ask():
        payload["tiers"] = _router_tier_overrides(questionary, preview)
    return payload


def _channel_control_fields(spec: ChannelSetupSpec) -> set[str]:
    controls: set[str] = set()
    for field in spec.fields:
        controls.update((field.show_when or {}).keys())
    return controls


def _channel_field_visible(field: ChannelSetupField, answers: dict[str, Any]) -> bool:
    return all(
        str(answers.get(key, "")) == str(expected)
        for key, expected in (field.show_when or {}).items()
    )


def _should_prompt_channel_field(
    field: ChannelSetupField,
    *,
    controls: set[str],
    answers: dict[str, Any],
) -> bool:
    if not _channel_field_visible(field, answers):
        return False
    if field.name == "name":
        return True
    if field.required:
        return True
    if field.name in controls:
        return True
    if field.show_when and field.default in (None, ""):
        return True
    return False


def _channel_prompt_default(
    field: ChannelSetupField,
    *,
    current: Any,
    type_name: str,
) -> Any:
    if current not in (None, ""):
        return current
    if field.name == "name":
        return type_name
    return field.default


def _ask_channel_field(questionary, field: ChannelSetupField, default: Any) -> Any:
    if field.help:
        console.print(
            f"  [dim]{markup_escape(field.label)}: {markup_escape(field.help)}[/dim]"
        )
    elif field.placeholder:
        console.print(
            f"  [dim]{markup_escape(field.label)}: "
            f"{markup_escape(field.placeholder)}[/dim]"
        )
    if field.field_type == "select":
        select_default = default if isinstance(default, str) else None
        return questionary.select(
            field.label, choices=list(field.choices), default=select_default
        ).ask()
    if field.field_type == "bool":
        return questionary.confirm(field.label, default=bool(default)).ask()
    if field.field_type == "password":
        return questionary.password(field.label).ask() or ""
    if field.field_type == "int":
        raw = questionary.text(
            field.label, default=str(default if default is not None else 0)
        ).ask() or "0"
        return int(raw)
    if field.field_type == "float":
        raw = questionary.text(
            field.label, default=str(default if default is not None else 0.0)
        ).ask() or "0"
        return float(raw)
    return questionary.text(field.label, default=str(default or "")).ask() or ""


def _ask_channel_fields(
    questionary,
    spec: ChannelSetupSpec,
    *,
    type_name: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answers: dict[str, Any] = {"type": type_name, **(current or {})}
    for field in spec.fields:
        if field.default is not None and field.name not in answers:
            answers[field.name] = field.default

    controls = _channel_control_fields(spec)
    for field in spec.fields:
        if field.show_when:
            continue
        if not _should_prompt_channel_field(field, controls=controls, answers=answers):
            continue
        default = _channel_prompt_default(
            field,
            current=answers.get(field.name),
            type_name=type_name,
        )
        answers[field.name] = _ask_channel_field(questionary, field, default)

    for field in spec.fields:
        if not field.show_when:
            continue
        if not _should_prompt_channel_field(field, controls=controls, answers=answers):
            continue
        default = _channel_prompt_default(
            field,
            current=answers.get(field.name),
            type_name=type_name,
        )
        answers[field.name] = _ask_channel_field(questionary, field, default)

    return answers


def _print_channel_intro(spec: ChannelSetupSpec) -> None:
    console.print(
        f"[bold {ACCENT}]▌[/] [bold]{markup_escape(spec.label)}[/]"
        f" [dim]· {markup_escape(spec.description)}[/dim]"
    )
    if spec.help:
        console.print(f"  [dim]{markup_escape(spec.help)}[/dim]")
    if spec.requires_public_url:
        console.print(
            f"  [{ACCENT_SOFT}]webhook[/] "
            "[dim]needs a public HTTPS URL reachable by the platform[/dim]"
        )
    console.print(
        "  [dim]minimal-field wizard · advanced/webhook-only fields editable later[/dim]"
    )


def _warn_channel_dependency_gaps(spec: ChannelSetupSpec, answers: dict[str, Any]) -> None:
    """Warn about optional channel dependencies that will fail at gateway start."""
    if spec.type == "feishu" and answers.get("connection_mode") == "websocket":
        if importlib.util.find_spec("lark_oapi") is None:
            console.print(
                warning_panel(
                    "Feishu websocket mode requires the optional feishu extra "
                    "(lark-oapi).\n\n"
                    "[bold]Installed command:[/]\n"
                    "  pwsh -ExecutionPolicy Bypass -File install.ps1 -Extras feishu\n"
                    "  OPENSQUILLA_INSTALL_EXTRAS=feishu bash install.sh\n"
                    "  opensquilla gateway restart\n\n"
                    "[bold]Development checkout:[/]\n"
                    "  uv sync --extra recommended --extra feishu\n"
                    "  uv run opensquilla gateway restart --json\n\n"
                    "[bold yellow]Restarting alone will not install Python packages.[/]",
                    title="Channel dependency missing",
                )
            )


def _print_channel_saved(name: str) -> None:
    console.print(
        f"[bold {ACCENT}]◆[/] [bold]Channel configured, not connected yet.[/]"
    )
    console.print(
        "  [dim]Restart the gateway process to load the channel adapter.[/dim]"
    )
    console.print(
        f"  [dim]Verify after restart:[/dim] "
        f"[{ACCENT_SOFT}]opensquilla channels status "
        f"{markup_escape(name)} --json[/]"
    )


def run_interactive_onboard(options: OnboardOptions) -> PersistResult:
    cfg = load_config()
    if options.if_needed and get_onboarding_status(cfg).llm_configured:
        return persist_config(cfg, restart_required=False, backup=False)

    if not _is_tty():
        return _print_noninteractive_hint()

    import questionary as _qmod
    questionary = _styled(_qmod)

    console.print(
        banner_panel(
            "OpenSquilla Onboarding",
            "Provider · Router · Channel · Search",
        )
    )
    spec, provider_id = _ask_provider_choice(questionary, options)
    answers = _ask_provider_fields(questionary, spec, options)
    res = upsert_llm_provider(
        cfg,
        provider_id=provider_id,
        model=answers["model"],
        api_key=answers.get("api_key", ""),
        api_key_env=answers.get("api_key_env", ""),
        base_url=answers.get("base_url", ""),
    )
    cfg_after_provider = res.config
    if options.router_mode:
        router_payload = _ask_router_fields(
            questionary,
            cfg_after_provider,
            provider_id=provider_id,
            requested_mode=options.router_mode,
        )
        router_res = upsert_router(
            cfg_after_provider,
            mode=router_payload["mode"],
            default_tier=router_payload.get("defaultTier"),
            tiers=router_payload.get("tiers"),
        )
        cfg_after_provider = router_res.config
    persist = persist_config(cfg_after_provider, restart_required=False)

    if options.minimal:
        return persist

    if not options.skip_channels and questionary.confirm(
        "Configure a messaging channel now?", default=False
    ).ask():
        run_interactive_channel_add(None)

    if not options.skip_search and questionary.confirm(
        "Configure web search now?", default=False
    ).ask():
        run_interactive_search_configure()

    if not options.skip_image_generation and questionary.confirm(
        "Enable image generation now?", default=False
    ).ask():
        run_interactive_image_generation_configure()

    return persist


def run_interactive_channel_add(type_name: str | None) -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint()

    import questionary as _qmod
    questionary = _styled(_qmod)

    if type_name is None:
        type_name = questionary.select(
            "Channel type",
            choices=[s.type for s in list_channel_setup_specs()],
        ).ask()
    spec = get_channel_setup_spec(type_name)
    _print_channel_intro(spec)
    answers = _ask_channel_fields(questionary, spec, type_name=type_name)
    _warn_channel_dependency_gaps(spec, answers)

    cfg = load_config()
    res = upsert_channel(cfg, entry_payload=answers)
    persisted = persist_config(res.config, restart_required=True)
    _print_channel_saved(str(res.public_payload.get("name") or answers.get("name")))
    return persisted


def run_interactive_channel_edit(name: str | None = None) -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint()

    import questionary as _qmod
    questionary = _styled(_qmod)

    cfg = load_config()
    existing_entries = [e.model_dump(mode="python") for e in cfg.channels.channels]
    if not existing_entries:
        console.print(
            f"[{ACCENT_DIM}]no channels to edit[/]"
            " [dim]· run `configure --section channels` to add one[/dim]"
        )
        return persist_config(cfg, restart_required=False, backup=False)

    if name is None:
        name = questionary.select(
            "Channel to edit",
            choices=[e["name"] for e in existing_entries],
        ).ask()
    target_entry = next(e for e in existing_entries if e["name"] == name)
    type_name = target_entry["type"]
    spec = get_channel_setup_spec(type_name)

    _print_channel_intro(spec)
    answers = _ask_channel_fields(
        questionary,
        spec,
        type_name=type_name,
        current={**target_entry, "name": name},
    )
    _warn_channel_dependency_gaps(spec, answers)

    res = upsert_channel(cfg, entry_payload=answers)
    persisted = persist_config(res.config, restart_required=True)
    _print_channel_saved(str(res.public_payload.get("name") or name))
    return persisted


def run_interactive_configure(section: str | None = None) -> PersistResult | None:
    if not _is_tty():
        _print_noninteractive_hint()
        return None

    import questionary as _qmod
    questionary = _styled(_qmod)

    section = section or questionary.select(
        "Section",
        choices=["providers", "channels", "search", "image-generation"],
    ).ask()
    if section == "providers":
        return run_interactive_onboard(
            OnboardOptions(skip_channels=True, skip_search=True)
        )
    if section == "channels":
        existing = load_config().channels.channels
        if existing:
            mode = questionary.select(
                "Channel action",
                choices=["add", "edit"],
                default="add",
            ).ask()
            if mode == "edit":
                return run_interactive_channel_edit(None)
        return run_interactive_channel_add(None)
    if section == "search":
        return run_interactive_search_configure()
    if section in {"image-generation", "image_generation"}:
        return run_interactive_image_generation_configure()
    console.print(
        f"[{ACCENT_DIM}]section[/] [{ACCENT_SOFT}]{markup_escape(repr(section))}[/]"
        " [dim]not yet supported in the wizard · edit "
        "~/.opensquilla/config.toml directly[/dim]"
    )
    return None
