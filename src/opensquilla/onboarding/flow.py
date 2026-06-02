"""Coordinate interactive and non-interactive onboarding flows."""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
from opensquilla.onboarding.errors import UserCancelledError
from opensquilla.onboarding.image_generation_specs import (
    ImageGenerationProviderSetupSpec,
    get_image_generation_provider_setup_spec,
    list_image_generation_provider_setup_specs,
)
from opensquilla.onboarding.memory_embedding_specs import (
    MemoryEmbeddingProviderSetupSpec,
    get_memory_embedding_provider_setup_spec,
    list_memory_embedding_provider_setup_specs,
)
from opensquilla.onboarding.mutations import (
    upsert_channel,
    upsert_image_generation_provider,
    upsert_llm_provider,
    upsert_memory_embedding,
    upsert_router,
    upsert_search_provider,
)
from opensquilla.onboarding.next_steps import (
    headless_setup_command,
    headless_setup_commands,
    setup_catalog_command,
)
from opensquilla.onboarding.provider_specs import (
    get_provider_setup_spec,
    list_provider_setup_specs,
)
from opensquilla.onboarding.search_specs import (
    get_search_provider_setup_spec,
    list_search_provider_setup_specs,
)
from opensquilla.onboarding.setup_paths import web_setup_url
from opensquilla.onboarding.status import get_onboarding_status
from opensquilla.router_tiers import (
    DEFAULT_TEXT_TIER,
    IMAGE_TIER,
    TEXT_TIERS,
    normalize_text_tier,
)
from opensquilla.ui import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_SOFT,
    banner_panel,
    console,
    markup_escape,
    questionary_style,
    warning_panel,
)

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
    try:
        import questionary.prompts.common as questionary_common

        questionary_common.INDICATOR_SELECTED = "☑"
        questionary_common.INDICATOR_UNSELECTED = "☐"
    except Exception:
        pass

    def _wrap(name):
        fn = getattr(q, name)
        return lambda *a, **kw: fn(*a, **{"style": style, **kw})

    return SimpleNamespace(
        select=_wrap("select"),
        text=_wrap("text"),
        confirm=_wrap("confirm"),
        password=_wrap("password"),
        checkbox=_wrap("checkbox"),
        Choice=getattr(q, "Choice", None),
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
    proxy: str | None = None
    router_mode: str = "recommended"
    minimal: bool = False
    skip_migration: bool = False
    config_path: str | Path | None = None


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _flush_stdin_typeahead() -> None:
    """Drop keys typed before the visible setup prompt was flushed."""
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return
        msvcrt_mod = cast(Any, msvcrt)
        while msvcrt_mod.kbhit():
            msvcrt_mod.getwch()
        return

    if not sys.stdin.isatty():
        return
    try:
        import termios
    except ImportError:
        return
    termios_mod = cast(Any, termios)
    termios_mod.tcflush(sys.stdin, termios_mod.TCIFLUSH)


def _wait_for_setup_start() -> None:
    console.print(f"[{ACCENT}]◆[/] Press Enter to start setup")
    flush = getattr(getattr(console, "file", None), "flush", None)
    if callable(flush):
        flush()
    _flush_stdin_typeahead()
    input()


def run_noninteractive_provider_configure(
    provider_id: str,
    values: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> PersistResult:
    from opensquilla.onboarding.setup_engine import SetupEngine

    engine = SetupEngine(path=path)
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
    type_name: str,
    values: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> PersistResult:
    cfg = load_config(path)
    payload = {"type": type_name, **values}
    result = upsert_channel(cfg, entry_payload=payload)
    return persist_config(result.config, path=path, restart_required=True)


def run_noninteractive_search_configure(
    provider_id: str,
    values: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> PersistResult:
    cfg = load_config(path)
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
    return persist_config(result.config, path=path, restart_required=False)


def _config_cli_arg(config_path: str | Path | None) -> str:
    if config_path is None:
        return ""
    return f" --config {shlex.quote(str(config_path))}"


def _first_blocking_setup_section(cfg: Any) -> str:
    status = get_onboarding_status(cfg)
    for name in status.sections:
        if status.section_details.get(name, {}).get("blocking"):
            return name
    return "provider"


def _print_noninteractive_hint(
    cfg: Any,
    config_path: str | Path | None = None,
    *,
    section: str | None = None,
) -> PersistResult:
    if config_path is None and isinstance(cfg, (str, Path)):
        config_path = cfg
        cfg = load_config(config_path)
    config_arg = _config_cli_arg(config_path)
    normalized = (section or _first_blocking_setup_section(cfg)).replace("_", "-")
    headless_commands = headless_setup_commands(normalized)
    if not headless_commands:
        headless_commands = [
            headless_setup_command("provider")
            or (
                "Provider recipes",
                "opensquilla onboard catalog providers",
            )
        ]
    guided_command = (
        f"opensquilla onboard configure {normalized}{config_arg}"
        if section
        else f"opensquilla onboard --if-needed{config_arg}"
    )
    lines = [
        "Onboarding requires a TTY-compatible interactive terminal for the guided wizard.",
        "Use a runnable setup path from this shell:",
    ]
    setup_url = web_setup_url(cfg)
    if setup_url:
        lines.append(f"  Web UI: opensquilla gateway run{config_arg} -> {setup_url}")
    catalog_label, catalog_command = setup_catalog_command(config_arg)
    lines.append(f"  {catalog_label}: {catalog_command}")
    for label, command in headless_commands:
        lines.append(f"  {label}: {command}{config_arg}")
    lines.extend(
        [
            f"  Guided CLI: {guided_command} (interactive terminal only)",
            f"  Check status: opensquilla onboard status{config_arg}",
        ]
    )
    print("\n".join(lines))
    return PersistResult(
        path=default_config_path(),
        backup_path=None,
        restart_required=False,
        warnings=["tty_required"],
    )


def _ask_or_cancel(prompt, section: str) -> Any:
    """Run a questionary prompt and convert a ``None`` answer into ``UserCancelledError``.

    ``questionary`` returns ``None`` when the user aborts (Ctrl+C / Esc). Letting
    that flow into downstream validation or upsert calls produces misleading
    error messages — convert it to a typed cancellation at the input boundary
    so callers can route the user back to a resumable state.
    """
    value = prompt.ask()
    if value is None:
        raise UserCancelledError(section=section)
    return value


def _ask_provider_choice(questionary, options: OnboardOptions):
    if options.provider_id:
        spec = get_provider_setup_spec(options.provider_id)
        return spec, spec.provider_id
    supported = [s for s in list_provider_setup_specs() if s.runtime_supported]
    choices = [f"{s.provider_id} ({s.label})" for s in supported]
    default = next((choice for choice in choices if choice.startswith("openrouter ")), None)
    pid = _ask_or_cancel(
        questionary.select("LLM provider", choices=choices, default=default),
        section="provider",
    )
    pid_clean = pid.split(" ")[0]
    return get_provider_setup_spec(pid_clean), pid_clean


def _required_value(label: str):
    def _validate(value: str) -> bool | str:
        if str(value or "").strip():
            return True
        return f"{label} is required"

    return _validate


_PASTE_API_KEY_CHOICE = "Paste API key now"
_DETECTED_ENV_SUFFIX = " (detected)"
_TERMINAL_ESCAPE_RE = re.compile(r"\x1b")
_LEADING_TERMINAL_KEY_RE = re.compile(r"^\[[0-9;?]+~")


def _api_key_env_choice(env_key: str, *, detected: bool = False) -> str:
    suffix = _DETECTED_ENV_SUFFIX if detected else ""
    return f"Use environment variable {env_key}{suffix}"


def _api_key_env_from_choice(choice: str) -> str:
    prefix = "Use environment variable "
    if not choice.startswith(prefix):
        return ""
    env_key = choice[len(prefix) :]
    if env_key.endswith(_DETECTED_ENV_SUFFIX):
        env_key = env_key[: -len(_DETECTED_ENV_SUFFIX)]
    return env_key


def _api_key_source_choices(env_key: str) -> list[str]:
    choices = [_PASTE_API_KEY_CHOICE]
    if env_key:
        choices.append(
            _api_key_env_choice(env_key, detected=bool(os.environ.get(env_key)))
        )
    return choices


def _api_key_source_default(env_key: str) -> str:
    if env_key and os.environ.get(env_key):
        return _api_key_env_choice(env_key, detected=True)
    return _PASTE_API_KEY_CHOICE


def _secret_value_validator(label: str):
    required = _required_value(label)

    def _validate(value: str) -> bool | str:
        result = cast(bool | str, required(value))
        if result is not True:
            return result
        stripped = str(value or "").strip()
        if _TERMINAL_ESCAPE_RE.search(stripped) or _LEADING_TERMINAL_KEY_RE.search(
            stripped
        ):
            return (
                "Paste was not read correctly by this terminal. Use right-click, "
                "Shift+Insert, or the environment variable option."
            )
        return True

    return _validate


def _search_api_key_prompt(spec) -> str:
    if getattr(spec, "provider_id", "") == "brave":
        return (
            "Brave Search API key "
            "(create one at https://api-dashboard.search.brave.com/app/keys)"
        )
    return "Search API key"


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
        else:
            key_source = questionary.select(
                "LLM API key source",
                choices=_api_key_source_choices(env_key or ""),
                default=_api_key_source_default(env_key or ""),
            ).ask()
            selected_env_key = _api_key_env_from_choice(key_source or "")
            answers["api_key_env"] = selected_env_key
            answers["api_key"] = ""
            if not selected_env_key:
                answers["api_key"] = _ask_or_cancel(
                    questionary.password(
                        "API key",
                        validate=_secret_value_validator("API key"),
                    ),
                    section="provider",
                )
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
    answers["proxy"] = options.proxy or ""
    return answers


def _ask_search_choice(questionary):
    supported = [s for s in list_search_provider_setup_specs() if s.runtime_supported]
    provider_id = _ask_or_cancel(
        questionary.select(
            "Search provider",
            choices=[f"{s.provider_id} ({s.label})" for s in supported],
        ),
        section="search",
    )
    provider_id_clean = provider_id.split(" ")[0]
    return get_search_provider_setup_spec(provider_id_clean), provider_id_clean


def _ask_search_fields(questionary, spec) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    if spec.requires_api_key:
        env_key = spec.env_key or ""
        use_env_key = False
        if env_key and os.environ.get(env_key):
            use_env_key = bool(
                _ask_or_cancel(
                    questionary.confirm(
                        f"Use {env_key} from environment?",
                        default=True,
                    ),
                    section="search",
                )
            )
        if use_env_key:
            answers["api_key"] = ""
            answers["api_key_env"] = env_key
        else:
            answers["api_key"] = _ask_or_cancel(
                questionary.password(
                    _search_api_key_prompt(spec),
                    validate=_secret_value_validator("Search API key"),
                ),
                section="search",
            )
            answers["api_key_env"] = ""
    else:
        answers["api_key"] = ""
        answers["api_key_env"] = ""
    max_results = _ask_or_cancel(
        questionary.text("Max search results", default="5"), section="search"
    ) or "5"
    answers["max_results"] = int(max_results)
    answers["proxy"] = _ask_or_cancel(
        questionary.text("Search HTTP proxy", default=""), section="search"
    )
    answers["use_env_proxy"] = bool(
        _ask_or_cancel(
            questionary.confirm("Use environment proxy for search?", default=False),
            section="search",
        )
    )
    fallback_choice = _ask_or_cancel(
        questionary.select(
            "Search fallback policy",
            choices=list(_SEARCH_FALLBACK_LABELS.values()),
            default=_SEARCH_FALLBACK_LABELS["off"],
        ),
        section="search",
    )
    answers["fallback_policy"] = _search_fallback_choice_to_value(fallback_choice)
    answers["diagnostics"] = bool(
        _ask_or_cancel(
            questionary.confirm(_SEARCH_DIAGNOSTICS_PROMPT, default=False),
            section="search",
        )
    )
    return answers


def run_interactive_search_configure(
    config_path: str | Path | None = None,
) -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint(config_path, section="search")

    import questionary as _qmod
    questionary = _styled(_qmod)

    console.print(banner_panel("Search Setup", "Wire a web search provider"))
    spec, provider_id = _ask_search_choice(questionary)
    answers = _ask_search_fields(questionary, spec)
    cfg = load_config(config_path)
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
    return persist_config(result.config, path=config_path, restart_required=False)


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
    llm_choice = "Reuse matching LLM provider key"
    if config.llm.provider == spec.provider_id and config.llm.api_key:
        key_choices.append(llm_choice)
    env_choice = (
        _api_key_env_choice(spec.env_key)
        if spec.env_key
        else ""
    )
    if env_choice and os.environ.get(spec.env_key):
        key_choices.append(env_choice)
    key_choices.append(_PASTE_API_KEY_CHOICE)
    if env_choice and not os.environ.get(spec.env_key):
        key_choices.append(env_choice)

    key_source = questionary.select(
        "Image API key source",
        choices=key_choices,
        default=key_choices[0],
    ).ask()
    selected_env_key = _api_key_env_from_choice(key_source or "")
    if key_source == _PASTE_API_KEY_CHOICE:
        answers["api_key"] = (
            questionary.password(
                "Image API key",
                validate=_secret_value_validator("Image API key"),
            ).ask()
            or ""
        )
        answers["api_key_env"] = ""
    elif selected_env_key:
        answers["api_key"] = ""
        answers["api_key_env"] = selected_env_key
    else:
        answers["api_key"] = ""
        answers["api_key_env"] = ""

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


def run_interactive_image_generation_configure(
    config_path: str | Path | None = None,
) -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint(config_path, section="image-generation")

    import questionary as _qmod
    questionary = _styled(_qmod)

    cfg = load_config(config_path)
    spec, provider_id = _ask_image_generation_choice(questionary, cfg)
    _print_image_generation_intro(spec)
    answers = _ask_image_generation_fields(questionary, spec, cfg)
    result = upsert_image_generation_provider(
        cfg,
        provider_id=provider_id,
        primary=answers.get("primary", ""),
        api_key=answers.get("api_key", ""),
        api_key_env=answers.get("api_key_env", ""),
        base_url=answers.get("base_url", ""),
        enabled=bool(answers.get("enabled", True)),
    )
    persisted = persist_config(result.config, path=config_path, restart_required=False)
    _print_image_generation_saved(provider_id)
    return persisted


def _memory_embedding_choice_label(spec: MemoryEmbeddingProviderSetupSpec) -> str:
    return f"{spec.provider_id} ({spec.label})"


def _memory_embedding_choice_to_provider_id(choice: str | None) -> str:
    return (choice or "").split(" ", 1)[0]


def _ask_memory_embedding_choice(
    questionary,
    config,
) -> tuple[MemoryEmbeddingProviderSetupSpec, str]:
    providers = [
        s
        for s in list_memory_embedding_provider_setup_specs()
        if s.runtime_supported
    ]
    current_provider = getattr(config.memory.embedding, "requested_provider", "auto")
    default_spec = next(
        (s for s in providers if s.provider_id == current_provider),
        providers[0],
    )
    choice = _ask_or_cancel(
        questionary.select(
            "Memory embedding provider",
            choices=[_memory_embedding_choice_label(s) for s in providers],
            default=_memory_embedding_choice_label(default_spec),
        ),
        section="memory embedding",
    )
    provider_id = _memory_embedding_choice_to_provider_id(choice)
    return get_memory_embedding_provider_setup_spec(provider_id), provider_id


def _memory_embedding_key_choices(
    spec: MemoryEmbeddingProviderSetupSpec,
    config,
) -> list[str]:
    embedding = config.memory.embedding
    current_env = str(getattr(embedding.remote, "api_key_env", "") or "").strip()
    current_key = str(
        getattr(embedding.remote, "api_key", "")
        or getattr(embedding, "api_key", "")
        or ""
    ).strip()
    choices: list[str] = []
    if current_key:
        choices.append("Keep stored memory API key")
    env_key = current_env or spec.env_key
    if env_key:
        choices.append(
            _api_key_env_choice(env_key, detected=bool(os.environ.get(env_key)))
        )
    choices.append(_PASTE_API_KEY_CHOICE)
    return choices


def _ask_memory_embedding_fields(
    questionary,
    spec: MemoryEmbeddingProviderSetupSpec,
    config,
) -> dict[str, Any]:
    embedding = config.memory.embedding
    answers: dict[str, Any] = {}
    if spec.provider_id == "none":
        return answers
    if spec.provider_id == "local":
        answers["onnx_dir"] = _ask_or_cancel(
            questionary.text(
                "Local ONNX directory",
                default=(
                    embedding.local.onnx_dir
                    if embedding.requested_provider == "local"
                    else ""
                ),
            ),
            section="memory embedding",
        )
        return answers
    if spec.provider_id in {"openai", "openai-compatible"}:
        answers["model"] = _ask_or_cancel(
            questionary.text(
                "Memory embedding model",
                default=embedding.remote.model
                or embedding.model
                or "text-embedding-3-small",
            ),
            section="memory embedding",
        )
        key_source = _ask_or_cancel(
            questionary.select(
                "Memory API key source",
                choices=_memory_embedding_key_choices(spec, config),
            ),
            section="memory embedding",
        )
        selected_env_key = _api_key_env_from_choice(key_source or "")
        if key_source == _PASTE_API_KEY_CHOICE:
            answers["api_key"] = _ask_or_cancel(
                questionary.password(
                    "Memory embedding API key",
                    validate=_secret_value_validator("Memory embedding API key"),
                ),
                section="memory embedding",
            )
            answers["api_key_env"] = ""
        elif selected_env_key:
            answers["api_key"] = ""
            answers["api_key_env"] = selected_env_key
        else:
            answers["api_key"] = ""
            answers["api_key_env"] = ""
        answers["base_url"] = _ask_or_cancel(
            questionary.text(
                "Memory embedding base URL",
                default=embedding.remote.base_url
                or embedding.base_url
                or "https://api.openai.com/v1",
            ),
            section="memory embedding",
        )
        return answers
    if spec.provider_id == "ollama":
        answers["model"] = _ask_or_cancel(
            questionary.text(
                "Memory embedding model",
                default=embedding.ollama.model or "nomic-embed-text",
            ),
            section="memory embedding",
        )
        answers["base_url"] = _ask_or_cancel(
            questionary.text(
                "Memory embedding base URL",
                default=embedding.ollama.base_url or "http://localhost:11434",
            ),
            section="memory embedding",
        )
    return answers


def run_interactive_memory_embedding_configure(
    config_path: str | Path | None = None,
) -> PersistResult:
    if not _is_tty():
        cfg = load_config(config_path)
        return _print_noninteractive_hint(cfg, config_path, section="memory-embedding")

    import questionary as _qmod
    questionary = _styled(_qmod)

    cfg = load_config(config_path)
    spec, provider_id = _ask_memory_embedding_choice(questionary, cfg)
    answers = _ask_memory_embedding_fields(questionary, spec, cfg)
    result = upsert_memory_embedding(
        cfg,
        provider=provider_id,
        model=answers.get("model"),
        api_key=answers.get("api_key"),
        api_key_env=answers.get("api_key_env"),
        base_url=answers.get("base_url"),
        onnx_dir=answers.get("onnx_dir"),
    )
    persisted = persist_config(result.config, path=config_path, restart_required=False)
    console.print(
        f"[bold {ACCENT}]◆[/] [bold]Memory embedding configured.[/]"
    )
    console.print(
        f"  [dim]Provider:[/dim] [{ACCENT_SOFT}]{markup_escape(provider_id)}[/]"
        " [dim]· new memory indexing will use this setting[/dim]"
    )
    return persisted


_TEXT_ROUTER_TIERS = TEXT_TIERS
_EXPOSED_ROUTER_TIERS = (*TEXT_TIERS, IMAGE_TIER)
_TEXT_TIER_LABELS = {
    "c0": "Route c0",
    "c1": "Route c1",
    "c2": "Route c2",
    "c3": "Route c3",
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
    normalized = normalize_text_tier(tier) or DEFAULT_TEXT_TIER
    return _TEXT_TIER_LABELS.get(normalized, _TEXT_TIER_LABELS[DEFAULT_TEXT_TIER])


def _text_tier_to_internal(selected: str | None) -> str:
    normalized = normalize_text_tier(selected)
    if normalized:
        return normalized
    if selected in _TEXT_ROUTER_TIERS:
        return str(selected)
    for tier, label in _TEXT_TIER_LABELS.items():
        if selected == label:
            return tier
    return DEFAULT_TEXT_TIER


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
    default_tier = _text_tier_to_internal(getattr(router, "default_tier", None))
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
        default=_text_tier_label(str(preview.squilla_router.default_tier or "c1")),
    ).ask()
    default_tier = _text_tier_to_internal(default_tier_choice)
    preview = upsert_router(config, mode=mode, default_tier=default_tier).config
    _print_router_defaults(preview)

    payload: dict[str, Any] = {"mode": mode, "defaultTier": default_tier}
    if questionary.confirm("Edit router tier models now?", default=False).ask():
        payload["tiers"] = _router_tier_overrides(questionary, preview)
    return payload


def run_interactive_router_configure(
    *, config_path: str | Path | None = None
) -> PersistResult:
    cfg = load_config(config_path)
    if not _is_tty():
        return _print_noninteractive_hint(cfg, config_path, section="router")

    import questionary as _qmod

    questionary = _styled(_qmod)
    provider_id = _provider_id_from_config(cfg)
    requested_mode = "recommended" if cfg.squilla_router.enabled else "disabled"
    payload = _ask_router_fields(
        questionary,
        cfg,
        provider_id=provider_id,
        requested_mode=requested_mode,
    )
    result = upsert_router(
        cfg,
        mode=payload["mode"],
        default_tier=payload.get("defaultTier"),
        tiers=payload.get("tiers"),
    )
    return persist_config(result.config, path=config_path, restart_required=False)


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
        return not field.advanced
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
        return (
            questionary.password(
                field.label,
                validate=_secret_value_validator(field.label),
            ).ask()
            or ""
        )
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
                    "Feishu websocket mode requires the base lark-oapi dependency "
                    "(lark-oapi).\n\n"
                    "[bold]Portable zip:[/]\n"
                    "  Use the latest recommended portable package, then restart.\n\n"
                    "[bold]Installed command:[/]\n"
                    "  irm https://opensquilla.ai/install.ps1 | iex\n"
                    "  curl -LsSf https://opensquilla.ai/install.sh | bash -s --\n"
                    "  opensquilla gateway restart\n\n"
                    "[bold]Development checkout:[/]\n"
                    "  uv sync --extra recommended\n"
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


_MIGRATION_SOURCE_LABELS = {
    "openclaw": "OpenClaw",
    "hermes": "Hermes Agent",
}


@dataclass(frozen=True)
class DetectedMigrationSource:
    name: str
    path: Path


@dataclass(frozen=True)
class MigrationBatchOptions:
    config: Path
    apply: bool
    migrate_secrets: bool
    overwrite: bool
    preset: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    skill_conflict: str
    persona_conflict: str


@dataclass(frozen=True)
class MigrationBatchResult:
    selected: tuple[str, ...]
    reports: dict[str, dict[str, Any]]
    apply: bool

    @property
    def has_error(self) -> bool:
        return any(
            item.get("status") == "error"
            for report in self.reports.values()
            for item in report.get("items", [])
            if isinstance(item, dict)
        )


def _config_path_from_loaded_config(cfg: Any) -> Path:
    raw = getattr(cfg, "config_path", "") or default_config_path()
    return Path(raw).expanduser()


def _migration_orchestrator() -> Any:
    return importlib.import_module("opensquilla.migration.orchestrator")


def detect_default_sources() -> list[Any]:
    return cast(list[Any], _migration_orchestrator().detect_default_sources())


def run_migration_batch(
    detected: list[Any], selected: list[str] | tuple[str, ...], options: Any
) -> Any:
    migration = _migration_orchestrator()
    if isinstance(options, MigrationBatchOptions):
        options = migration.MigrationBatchOptions(
            config=options.config,
            apply=options.apply,
            migrate_secrets=options.migrate_secrets,
            overwrite=options.overwrite,
            preset=options.preset,
            include=options.include,
            exclude=options.exclude,
            skill_conflict=options.skill_conflict,
            persona_conflict=options.persona_conflict,
        )
    return migration.run_migration_batch(detected, selected, options)


def report_status_counts(report: dict[str, Any]) -> dict[str, int]:
    return cast(dict[str, int], _migration_orchestrator().report_status_counts(report))


def _run_onboard_migration_step(
    questionary,
    *,
    config_path: Path,
) -> Any | None:
    """Run the interactive onboarding migration pre-step.

    Migration is intentionally isolated from the rest of onboarding: detection,
    dry-run, apply, and report rendering failures all degrade to "skip migration"
    so provider setup can continue normally.
    """

    migration = None
    try:
        migration = _migration_orchestrator()
        detected = detect_default_sources()
        if not detected:
            return None
        _print_detected_migration_sources(detected)
        should_migrate = bool(
            _ask_or_cancel(
                questionary.confirm(
                    "Review migration options now?",
                    default=True,
                ),
                section="migration",
            )
        )
        if not should_migrate:
            console.print("[dim]Migration skipped.[/dim]")
            return None

        selected = _ask_migration_sources(questionary, detected)
        if not selected:
            console.print("[yellow]No migration source selected; skipping migration.[/yellow]")
            return None
        _print_selected_migration_sources(detected, selected)

        migrate_secrets = bool(
            _ask_or_cancel(
                questionary.confirm(
                    "Import saved API keys/tokens from detected legacy .env files?",
                    default=False,
                ),
                section="migration",
            )
        )
        dry_run_options = _onboard_migration_options(
            migration=migration,
            config_path=config_path,
            apply=False,
            migrate_secrets=migrate_secrets,
        )
        dry_run = run_migration_batch(detected, selected, dry_run_options)
        _print_migration_summary(dry_run, title="Migration preview")
        if dry_run.has_error:
            console.print(
                warning_panel(
                    "Migration preview found errors. Onboarding will continue without "
                    "applying migration; retry later with `opensquilla migrate --apply`."
                )
            )
            return None

        apply_now = bool(
            _ask_or_cancel(
                questionary.confirm("Apply this migration now?", default=True),
                section="migration",
            )
        )
        if not apply_now:
            console.print("[dim]Migration not applied.[/dim]")
            return None

        applied_options = _onboard_migration_options(
            migration=migration,
            config_path=config_path,
            apply=True,
            migrate_secrets=migrate_secrets,
        )
        applied = run_migration_batch(detected, selected, applied_options)
        _print_migration_summary(applied, title="Migration complete")
        if applied.has_error:
            console.print(
                warning_panel(
                    "Migration reported errors after apply. Onboarding will continue; "
                    "review the migration report before relying on imported data."
                )
            )
            return None
        return applied
    except UserCancelledError:
        console.print("[yellow]Migration setup cancelled — continuing onboarding.[/yellow]")
        return None
    except KeyboardInterrupt:
        console.print("[yellow]Migration interrupted — continuing onboarding.[/yellow]")
        return None
    except Exception as exc:
        option_error = getattr(migration, "MigrationOptionError", None)
        if isinstance(option_error, type) and isinstance(exc, option_error):
            console.print(
                warning_panel(
                    f"Migration options were rejected: {exc}. "
                    "Onboarding will continue without migration."
                )
            )
            return None
        console.print(
            warning_panel(
                f"Migration failed before onboarding completed: {exc}. "
                "Onboarding will continue without migration."
            )
        )
        return None


def _onboard_migration_options(
    *,
    migration: Any,
    config_path: Path,
    apply: bool,
    migrate_secrets: bool,
) -> Any:
    return MigrationBatchOptions(
        config=config_path,
        apply=apply,
        migrate_secrets=migrate_secrets,
        overwrite=False,
        preset="full",
        include=(),
        exclude=(),
        skill_conflict="skip",
        persona_conflict="use-opensquilla",
    )


def _print_detected_migration_sources(detected: list[Any]) -> None:
    console.print(f"[bold {ACCENT}]◆[/] [bold]Existing agent data detected[/]")
    for source in detected:
        label = _MIGRATION_SOURCE_LABELS.get(source.name, source.name)
        console.print(f"  [{ACCENT_SOFT}]✓[/] {label} [dim]{source.path}[/dim]")


def _print_selected_migration_sources(
    detected: list[Any],
    selected: list[str],
) -> None:
    selected_names = set(selected)
    console.print(f"[bold {ACCENT}]◆[/] [bold]Selected migration sources[/]")
    for source in detected:
        if source.name not in selected_names:
            continue
        label = _MIGRATION_SOURCE_LABELS.get(source.name, source.name)
        console.print(f"  [{ACCENT_SOFT}]☑[/] {label} [dim]{source.path}[/dim]")


def _ask_migration_sources(
    questionary,
    detected: list[Any],
) -> list[str]:
    if len(detected) == 1:
        return [detected[0].name]
    choice_cls = getattr(questionary, "Choice", None)
    if choice_cls is None:
        choices = [
            f"{_MIGRATION_SOURCE_LABELS.get(source.name, source.name)} - {source.path}"
            for source in detected
        ]
        selected = _ask_or_cancel(
            questionary.checkbox(
                "Select sources to import",
                choices=choices,
                instruction="Space select | Enter continue | A toggle all",
            ),
            section="migration",
        )
        selected_text = {str(value).split(" ", 1)[0].lower() for value in selected}
        return [source.name for source in detected if source.name in selected_text]
    choices = [
        choice_cls(
            title=_MIGRATION_SOURCE_LABELS.get(source.name, source.name),
            value=source.name,
            checked=True,
            description=str(source.path),
        )
        for source in detected
    ]
    selected = _ask_or_cancel(
        questionary.checkbox(
            "Select sources to import",
            choices=choices,
            instruction="Space select | Enter continue | A toggle all",
        ),
        section="migration",
    )
    return [str(value) for value in selected]


def _print_migration_summary(result: Any, *, title: str) -> None:
    console.print(f"[bold {ACCENT}]◆[/] [bold]{title}[/]")
    mode = "applied" if result.apply else "dry-run"
    for name in result.selected:
        report = result.reports.get(name, {})
        label = _MIGRATION_SOURCE_LABELS.get(name, name)
        counts = report_status_counts(report)
        pieces = [
            f"{status}={count}"
            for status, count in sorted(counts.items())
            if count
        ]
        summary = ", ".join(pieces) if pieces else "no changes"
        console.print(f"  {label}: {mode}; {summary}")
        output_dir = str(report.get("output_dir") or "")
        report_file = Path(output_dir) / "report.json" if output_dir else None
        if output_dir and (result.apply or (report_file is not None and report_file.is_file())):
            console.print(f"    [dim]Report:[/dim] {output_dir}")


def _migration_result_path(
    cfg: Any,
    migration_result: Any | None,
    *,
    config_path: Path,
) -> PersistResult:
    if migration_result is None:
        return PersistResult(
            path=_config_path_from_loaded_config(cfg),
            backup_path=None,
            restart_required=False,
        )
    return PersistResult(
        path=config_path,
        backup_path=None,
        restart_required=bool(migration_result.apply),
    )


def _reload_after_migration(config_path: Path, fallback: Any):
    try:
        return load_config(config_path)
    except Exception as exc:
        console.print(
            warning_panel(
                f"Imported configuration could not be reloaded: {exc}. "
                "Continuing with the pre-migration onboarding state."
            )
        )
        return fallback


def _keep_imported_provider(questionary, cfg: Any) -> bool:
    llm = getattr(cfg, "llm", None)
    provider = str(getattr(llm, "provider", "") or "")
    model = str(getattr(llm, "model", "") or "")
    router_supported = _imported_provider_router_supported(cfg)
    if provider:
        console.print(
            f"[bold {ACCENT}]◆[/] [bold]Imported provider settings found[/]"
        )
        console.print(f"  Provider: [{ACCENT_SOFT}]{markup_escape(provider)}[/]")
        if router_supported:
            console.print(
                "  Model: [dim]will use SquillaRouter defaults; "
                "old direct model is not imported[/dim]"
            )
        elif model:
            console.print(f"  Model: [{ACCENT_SOFT}]{markup_escape(model)}[/]")
    return bool(
        _ask_or_cancel(
            questionary.confirm("Use imported provider credentials?", default=True),
            section="provider",
        )
    )


def _imported_provider_router_supported(cfg: Any) -> bool:
    llm = getattr(cfg, "llm", None)
    provider = str(getattr(llm, "provider", "") or "")
    if not provider:
        return False
    try:
        spec = get_provider_setup_spec(provider)
    except KeyError:
        return False
    return bool(getattr(spec, "router_supported", False))


def _provider_id_from_config(cfg: Any) -> str:
    llm = getattr(cfg, "llm", None)
    return str(getattr(llm, "provider", "") or "")


def _imported_provider_key_payload(llm: Any) -> dict[str, str]:
    api_key = str(getattr(llm, "api_key", "") or "")
    api_key_env = str(getattr(llm, "api_key_env", "") or "")
    if api_key:
        api_key_env = ""
    return {"api_key": api_key, "api_key_env": api_key_env}


def _use_imported_provider_credentials_with_router_defaults(
    questionary,
    cfg: Any,
    *,
    requested_mode: str,
):
    llm = getattr(cfg, "llm", None)
    provider = _provider_id_from_config(cfg)
    key_payload = _imported_provider_key_payload(llm)
    res = upsert_llm_provider(
        cfg,
        provider_id=provider,
        model="",
        api_key=key_payload["api_key"],
        api_key_env=key_payload["api_key_env"],
        base_url=str(getattr(llm, "base_url", "") or ""),
        proxy=str(getattr(llm, "proxy", "") or ""),
        provider_routing=dict(getattr(llm, "provider_routing", {}) or {}),
    )
    cfg_after_provider = res.config
    if requested_mode:
        router_payload = _ask_router_fields(
            questionary,
            cfg_after_provider,
            provider_id=provider,
            requested_mode=requested_mode,
        )
        router_res = upsert_router(
            cfg_after_provider,
            mode=router_payload["mode"],
            default_tier=router_payload.get("defaultTier"),
            tiers=router_payload.get("tiers"),
        )
        cfg_after_provider = router_res.config
    return cfg_after_provider


def _complete_imported_provider_credentials(questionary, cfg: Any):
    llm = getattr(cfg, "llm", None)
    provider = str(getattr(llm, "provider", "") or "")
    model = str(getattr(llm, "model", "") or "")
    base_url = str(getattr(llm, "base_url", "") or "")
    imported_env_key = str(getattr(llm, "api_key_env", "") or "")
    if not provider or not model:
        return None
    try:
        spec = get_provider_setup_spec(provider)
    except KeyError:
        return None
    if not spec.runtime_supported or not spec.requires_api_key:
        return None
    if spec.requires_base_url and not base_url:
        return None

    console.print(
        warning_panel(
            "Provider settings were imported, but no usable API key is available. "
            "Set the key now to finish onboarding."
        )
    )
    credentials = _ask_imported_provider_credentials(
        questionary,
        spec,
        imported_env_key=imported_env_key,
    )
    res = upsert_llm_provider(
        cfg,
        provider_id=provider,
        model="" if _imported_provider_router_supported(cfg) else model,
        api_key=credentials["api_key"],
        api_key_env=credentials["api_key_env"],
        base_url=base_url,
    )
    return res.config


def _ask_imported_provider_credentials(
    questionary,
    spec,
    *,
    imported_env_key: str,
) -> dict[str, str]:
    choices = [_PASTE_API_KEY_CHOICE]
    seen_env_keys: set[str] = set()
    for env_key in (imported_env_key, spec.env_key):
        if env_key and env_key not in seen_env_keys:
            seen_env_keys.add(env_key)
            choices.append(
                _api_key_env_choice(env_key, detected=bool(os.environ.get(env_key)))
            )
    detected_choice = next((choice for choice in choices if _DETECTED_ENV_SUFFIX in choice), None)
    key_source = _ask_or_cancel(
        questionary.select(
            "LLM API key source",
            choices=choices,
            default=detected_choice or _PASTE_API_KEY_CHOICE,
        ),
        section="provider",
    )
    selected_env_key = _api_key_env_from_choice(key_source or "")
    if selected_env_key:
        return {"api_key": "", "api_key_env": selected_env_key}
    return {
        "api_key": _ask_or_cancel(
            questionary.password(
                "API key",
                validate=_secret_value_validator("API key"),
            ),
            section="provider",
        ),
        "api_key_env": "",
    }


def run_interactive_onboard(options: OnboardOptions) -> PersistResult:
    cfg = load_config(options.config_path)
    status = get_onboarding_status(cfg)
    if options.if_needed and status.has_config and not status.needs_onboarding:
        return persist_config(
            cfg,
            path=options.config_path,
            restart_required=False,
            backup=False,
        )

    if not _is_tty():
        return _print_noninteractive_hint(cfg, options.config_path)

    import questionary as _qmod
    questionary = _styled(_qmod)

    console.print(
        banner_panel(
            "OpenSquilla Onboarding",
            "Migration · Provider · SquillaRouter · Channels · Capabilities",
        )
    )
    _wait_for_setup_start()
    if options.if_needed and status.has_config and status.llm_configured:
        _run_action_required_optional_sections(
            questionary,
            status,
            options=options,
        )
        return persist_config(
            load_config(options.config_path),
            path=options.config_path,
            restart_required=False,
            backup=False,
        )

    config_path = _config_path_from_loaded_config(cfg)
    migration_result: Any | None = None
    if not options.skip_migration:
        migration_result = _run_onboard_migration_step(
            questionary,
            config_path=config_path,
        )
        if migration_result is not None:
            cfg = _reload_after_migration(config_path, cfg)
            status = get_onboarding_status(cfg)

    keep_imported = (
        migration_result is not None
        and not migration_result.has_error
        and status.llm_configured
        and _keep_imported_provider(questionary, cfg)
    )
    if keep_imported:
        try:
            if _imported_provider_router_supported(cfg):
                cfg_after_provider = _use_imported_provider_credentials_with_router_defaults(
                    questionary,
                    cfg,
                    requested_mode=options.router_mode,
                )
                persist = persist_config(
                    cfg_after_provider,
                    path=options.config_path,
                    restart_required=False,
                )
            else:
                cfg_after_provider = cfg
                persist = _migration_result_path(cfg, migration_result, config_path=config_path)
        except Exception as exc:
            keep_imported = False
            console.print(
                warning_panel(
                    f"Imported provider settings could not be finalized: {exc}. "
                    "Continue provider setup to finish onboarding."
                )
            )
    if not keep_imported:
        completed_imported = (
            _complete_imported_provider_credentials(questionary, cfg)
            if migration_result is not None and not status.llm_configured
            else None
        )
        if completed_imported is not None:
            cfg_after_provider = completed_imported
            if _imported_provider_router_supported(cfg_after_provider) and options.router_mode:
                router_payload = _ask_router_fields(
                    questionary,
                    cfg_after_provider,
                    provider_id=_provider_id_from_config(cfg_after_provider),
                    requested_mode=options.router_mode,
                )
                router_res = upsert_router(
                    cfg_after_provider,
                    mode=router_payload["mode"],
                    default_tier=router_payload.get("defaultTier"),
                    tiers=router_payload.get("tiers"),
                )
                cfg_after_provider = router_res.config
        else:
            if migration_result is not None and not status.llm_configured:
                console.print(
                    warning_panel(
                        "Provider settings were not fully usable after migration. "
                        "Continue provider setup to finish onboarding."
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
                proxy=answers.get("proxy", ""),
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
        persist = persist_config(
            cfg_after_provider,
            path=options.config_path,
            restart_required=False,
        )

    if options.minimal:
        return persist

    if not options.skip_channels and questionary.confirm(
        "Configure a messaging channel now?", default=False
    ).ask():
        _run_optional_section(
            section="channel",
            label="channel",
            runner=run_interactive_channel_add,
            args=(None,),
            config_path=options.config_path,
        )

    if not options.skip_search and questionary.confirm(
        "Configure web search now?", default=False
    ).ask():
        _run_optional_section(
            section="search",
            label="search",
            runner=run_interactive_search_configure,
            config_path=options.config_path,
        )

    if not options.skip_image_generation and questionary.confirm(
        "Enable image generation now?", default=False
    ).ask():
        _run_optional_section(
            section="image-generation",
            label="image generation",
            runner=run_interactive_image_generation_configure,
            config_path=options.config_path,
        )

    refreshed_status = get_onboarding_status(load_config(options.config_path))
    _run_action_required_optional_sections(
        questionary,
        refreshed_status,
        options=options,
        sections=("memory_embedding",),
    )

    return persist


def _run_optional_section(
    *,
    section: str,
    label: str,
    runner,
    args: tuple[Any, ...] = (),
    kwargs: dict | None = None,
    config_path: str | Path | None = None,
) -> None:
    """Run an optional onboarding step, isolating cancellation from siblings.

    ``section`` is the slug consumed by ``opensquilla onboard configure <section>``;
    ``label`` is the user-facing wording (which can contain spaces). Only
    cancellation-shaped exceptions are caught here — real validation or
    programming errors propagate so they surface in the operator's terminal
    instead of being silently buried alongside the "skipping" message.
    """
    try:
        runner_kwargs = {**(kwargs or {})}
        if config_path is not None:
            runner_kwargs.setdefault("config_path", config_path)
        runner(*args, **runner_kwargs)
    except UserCancelledError:
        config_arg = _config_cli_arg(config_path)
        console.print(
            f"[yellow]{label} setup cancelled — skipping.[/yellow]"
        )
        console.print(
            f"  [dim]Resume later with[/dim] "
            f"[{ACCENT_SOFT}]opensquilla onboard configure {section}{config_arg}[/]"
        )
    except KeyboardInterrupt:
        console.print(
            f"[yellow]{label} setup interrupted — skipping.[/yellow]"
        )


def _section_needs_action(status, section: str) -> bool:
    detail = status.section_details.get(section, {})
    return bool(detail.get("blocking") or detail.get("actionRequired"))


def _run_action_required_optional_sections(
    questionary,
    status,
    *,
    options: OnboardOptions,
    sections: tuple[str, ...] = (
        "router",
        "channels",
        "search",
        "image_generation",
        "memory_embedding",
    ),
) -> None:
    actions = {
        "router": {
            "prompt": "Configure SquillaRouter now?",
            "section": "router",
            "label": "router",
            "runner": run_interactive_router_configure,
            "skip": False,
        },
        "channels": {
            "prompt": "Configure messaging channels now?",
            "section": "channels",
            "label": "channel",
            "runner": run_interactive_channel_add,
            "args": (None,),
            "skip": options.skip_channels,
        },
        "search": {
            "prompt": "Configure web search now?",
            "section": "search",
            "label": "search",
            "runner": run_interactive_search_configure,
            "skip": options.skip_search,
        },
        "image_generation": {
            "prompt": "Fix image generation now?",
            "section": "image-generation",
            "label": "image generation",
            "runner": run_interactive_image_generation_configure,
            "skip": options.skip_image_generation,
        },
        "memory_embedding": {
            "prompt": "Configure memory embeddings now?",
            "section": "memory-embedding",
            "label": "memory embedding",
            "runner": run_interactive_memory_embedding_configure,
            "skip": False,
        },
    }
    for name in sections:
        action = actions.get(name)
        if not action or action.get("skip") or not _section_needs_action(status, name):
            continue
        if not questionary.confirm(str(action["prompt"]), default=True).ask():
            continue
        _run_optional_section(
            section=str(action["section"]),
            label=str(action["label"]),
            runner=action["runner"],
            args=cast(tuple[Any, ...], action.get("args", ())),
            config_path=options.config_path,
        )


def run_interactive_channel_add(
    type_name: str | None,
    *,
    config_path: str | Path | None = None,
) -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint(config_path, section="channels")

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

    cfg = load_config(config_path)
    res = upsert_channel(cfg, entry_payload=answers)
    persisted = persist_config(res.config, path=config_path, restart_required=True)
    _print_channel_saved(str(res.public_payload.get("name") or answers.get("name")))
    return persisted


def run_interactive_channel_edit(
    name: str | None = None,
    *,
    config_path: str | Path | None = None,
) -> PersistResult:
    if not _is_tty():
        return _print_noninteractive_hint(config_path, section="channels")

    import questionary as _qmod
    questionary = _styled(_qmod)

    cfg = load_config(config_path)
    existing_entries = [e.model_dump(mode="python") for e in cfg.channels.channels]
    if not existing_entries:
        console.print(
            f"[{ACCENT_DIM}]no channels to edit[/]"
            " [dim]· run `opensquilla onboard configure channels` to add one[/dim]"
        )
        return persist_config(
            cfg,
            path=config_path,
            restart_required=False,
            backup=False,
        )

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
    persisted = persist_config(res.config, path=config_path, restart_required=True)
    _print_channel_saved(str(res.public_payload.get("name") or name))
    return persisted


def run_interactive_configure(
    section: str | None = None,
    *,
    config_path: str | Path | None = None,
) -> PersistResult | None:
    if not _is_tty():
        cfg = load_config(config_path)
        _print_noninteractive_hint(cfg, config_path, section=section)
        return None

    import questionary as _qmod
    questionary = _styled(_qmod)

    section = section or questionary.select(
        "Section",
        choices=[
            "provider",
            "router",
            "channels",
            "search",
            "image-generation",
            "memory-embedding",
        ],
    ).ask()
    if section in {"provider", "providers"}:
        return run_interactive_onboard(
            OnboardOptions(
                skip_channels=True,
                skip_search=True,
                config_path=config_path,
            )
        )
    if section == "router":
        return run_interactive_router_configure(config_path=config_path)
    if section in {"channel", "channels"}:
        existing = load_config(config_path).channels.channels
        if existing:
            mode = questionary.select(
                "Channel action",
                choices=["add", "edit"],
                default="add",
            ).ask()
            if mode == "edit":
                return run_interactive_channel_edit(None, config_path=config_path)
        return run_interactive_channel_add(None, config_path=config_path)
    if section == "search":
        return run_interactive_search_configure(config_path=config_path)
    if section in {"image-generation", "image_generation"}:
        return run_interactive_image_generation_configure(config_path=config_path)
    if section in {"memory-embedding", "memory_embedding"}:
        return run_interactive_memory_embedding_configure(config_path=config_path)
    console.print(
        f"[{ACCENT_DIM}]section[/] [{ACCENT_SOFT}]{markup_escape(repr(section))}[/]"
        " [dim]not yet supported in the wizard · edit "
        "~/.opensquilla/config.toml directly[/dim]"
    )
    return None
