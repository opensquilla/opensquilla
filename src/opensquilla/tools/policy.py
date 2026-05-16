"""Tool policy resolution for runtime tool visibility and dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase

from opensquilla.tools.types import InteractionMode, ToolContext

_TOOL_GROUPS: Mapping[str, frozenset[str]] = {
    "group:runtime": frozenset({"exec_command", "background_process"}),
    "group:fs": frozenset(
        {
            "read_file",
            "write_file",
            "edit_file",
            "apply_patch",
            "list_dir",
            "glob_search",
            "grep_search",
        }
    ),
    "group:sessions": frozenset(
        {"sessions_list", "sessions_history", "sessions_send", "sessions_spawn", "session_status"}
    ),
    "group:memory": frozenset({"memory_search", "memory_get"}),
    "group:web": frozenset({"web_search", "web_fetch", "http_request"}),
    "group:messaging": frozenset({"message"}),
    # Trusted host/gateway tools intentionally do not imply OS sandbox
    # execution. They remain addressable for explicit allow/deny policy so the
    # sandboxed-agent tool surface is not confused with operator-owned host
    # mutation paths.
    "group:trusted_host": frozenset(
        {
            "install_skill_deps",
            "skill_create",
            "skill_edit",
            "skill_delete",
        }
    ),
}

_IMAGE_GENERATION_TOOL_NAMES: frozenset[str] = frozenset(
    {"image_generate"}
)
_SESSION_READ_TOOL_NAMES: frozenset[str] = frozenset(
    {"session_status", "sessions_history", "sessions_list"}
)
_SESSION_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset(
    {"sessions_send", "sessions_spawn", "sessions_yield"}
)
_CHANNEL_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"message"})
_ADMIN_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"agents_list", "subagents"})
_GATEWAY_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"gateway"})
_SCHEDULER_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"cron"})


@dataclass(frozen=True)
class ToolSurfaceCapabilities:
    """Runtime dependencies that determine whether registered tools can work."""

    session_manager: bool = False
    task_runtime: bool = False
    scheduler: bool = False
    gateway_config: bool = False
    channel_backing: bool = False
    image_generation: bool = True


def _detect_image_generation_capability() -> bool:
    try:
        from opensquilla.provider.image_generation_runtime import image_generation_available

        return image_generation_available()
    except Exception:
        return False


def tool_surface_capabilities_from_runtime(
    *,
    session_manager: object | None = None,
    task_runtime: object | None = None,
    scheduler: object | None = None,
    gateway_config: object | None = None,
    channel_manager: object | None = None,
    originating_envelope: object | None = None,
    image_generation: bool | None = None,
) -> ToolSurfaceCapabilities:
    """Build tool-surface capabilities from injected runtime dependencies."""

    return ToolSurfaceCapabilities(
        session_manager=session_manager is not None,
        task_runtime=task_runtime is not None,
        scheduler=scheduler is not None,
        gateway_config=gateway_config is not None,
        channel_backing=channel_manager is not None or originating_envelope is not None,
        image_generation=(
            _detect_image_generation_capability()
            if image_generation is None
            else image_generation
        ),
    )


_TOOL_PROFILES: Mapping[str, frozenset[str] | None] = {
    "full": None,
    "minimal": frozenset({"session_status"}),
    "memory_only": _TOOL_GROUPS["group:memory"],
    "coding": (
        _TOOL_GROUPS["group:fs"]
        | _TOOL_GROUPS["group:runtime"]
        | _TOOL_GROUPS["group:sessions"]
        | _TOOL_GROUPS["group:memory"]
    ),
    "messaging": _TOOL_GROUPS["group:messaging"]
    | frozenset({"sessions_list", "sessions_history", "sessions_send", "session_status"}),
}


@dataclass(frozen=True)
class ToolPolicy:
    """Declarative tool policy layer.

    ``profile`` sets the base allowlist; ``allow`` and ``also_allow`` add
    selectors; ``deny`` removes selectors. Selectors can be exact tool names,
    ``group:*`` names, ``*``, or fnmatch-style patterns.
    """

    profile: str | None = None
    allow: frozenset[str] = frozenset()
    deny: frozenset[str] = frozenset()
    also_allow: frozenset[str] = frozenset()
    by_sender: Mapping[str, ToolPolicy] = field(default_factory=dict)


def _expand_selectors(selectors: frozenset[str], available_tools: frozenset[str]) -> set[str]:
    expanded: set[str] = set()
    for selector in selectors:
        item = selector.strip()
        if not item:
            continue
        if item == "*":
            expanded.update(available_tools)
            continue
        if item in _TOOL_GROUPS:
            expanded.update(_TOOL_GROUPS[item] & available_tools)
            continue
        if any(ch in item for ch in "*?[]"):
            expanded.update(tool for tool in available_tools if fnmatchcase(tool, item))
            continue
        if item in available_tools:
            expanded.add(item)
    return expanded


def _profile_allowlist(profile: str | None, available_tools: frozenset[str]) -> set[str] | None:
    if not profile:
        return None
    key = profile.strip().lower()
    if key not in _TOOL_PROFILES:
        raise ValueError(f"unknown tool profile: {profile}")
    expanded = _TOOL_PROFILES[key]
    if expanded is None:
        return None
    return set(expanded & available_tools)


def _add_allowed(
    allowed_tools: set[str] | None,
    additions: set[str],
) -> set[str] | None:
    if allowed_tools is None:
        return None
    return allowed_tools | additions


def _apply_base_policy(
    allowed_tools: set[str] | None,
    denied_tools: set[str],
    policy: ToolPolicy | None,
    available_tools: frozenset[str],
    *,
    profile_overrides: bool = False,
) -> tuple[set[str] | None, set[str]]:
    if policy is None:
        return allowed_tools, denied_tools

    profile_allowed = _profile_allowlist(policy.profile, available_tools)
    if profile_allowed is not None or (profile_overrides and policy.profile == "full"):
        allowed_tools = profile_allowed

    allowed_tools = _add_allowed(
        allowed_tools,
        _expand_selectors(policy.allow | policy.also_allow, available_tools),
    )
    denied_tools = denied_tools | _expand_selectors(policy.deny, available_tools)
    if allowed_tools is not None:
        allowed_tools -= denied_tools
    return allowed_tools, denied_tools


def _matches_sender(selector: str, sender_id: str | None) -> bool:
    if selector == "*":
        return True
    if not sender_id:
        return False
    return selector == f"id:{sender_id}" or selector == sender_id


def _get_field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _string_set(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(str(item) for item in value if str(item).strip())
    return frozenset()


def _policy_from_config(value: object) -> ToolPolicy | None:
    if value is None:
        return None
    if isinstance(value, ToolPolicy):
        return value

    tools_value = _get_field(value, "tools")
    sender_value = _get_field(value, "toolsBySender", _get_field(value, "tools_by_sender"))
    if tools_value is not None or sender_value is not None:
        base = _policy_from_config(tools_value) or ToolPolicy()
        return ToolPolicy(
            profile=base.profile,
            allow=base.allow,
            deny=base.deny,
            also_allow=base.also_allow,
            by_sender=_sender_policies_from_config(sender_value),
        )

    profile = _get_field(value, "profile")
    return ToolPolicy(
        profile=str(profile) if profile is not None else None,
        allow=_string_set(_get_field(value, "allow")),
        deny=_string_set(_get_field(value, "deny")),
        also_allow=_string_set(_get_field(value, "alsoAllow", _get_field(value, "also_allow"))),
        by_sender=_sender_policies_from_config(
            _get_field(value, "by_sender", _get_field(value, "bySender"))
        ),
    )


def _sender_policies_from_config(value: object) -> Mapping[str, ToolPolicy]:
    if not isinstance(value, Mapping):
        return {}
    policies: dict[str, ToolPolicy] = {}
    for selector, policy_value in value.items():
        policy = _policy_from_config(policy_value)
        if policy is not None:
            policies[str(selector)] = policy
    return policies


def _sender_policy(policy: ToolPolicy | None, sender_id: str | None) -> ToolPolicy | None:
    if policy is None:
        return None
    for selector, candidate in policy.by_sender.items():
        if _matches_sender(selector, sender_id):
            return candidate
    return None


def _remove_denied_from_allowed(
    allowed_tools: set[str] | None,
    denied_tools: set[str],
) -> set[str] | None:
    if allowed_tools is not None:
        allowed_tools -= denied_tools
    return allowed_tools


def resolve_runtime_tool_surface(
    ctx: ToolContext,
    *,
    capabilities: ToolSurfaceCapabilities | None = None,
) -> ToolContext:
    """Resolve runtime-capability tool visibility into the context denylist."""

    caps = capabilities or ToolSurfaceCapabilities()
    denied_tools = set(ctx.denied_tools)
    allowed_tools = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None

    if not caps.image_generation:
        denied_tools |= set(_IMAGE_GENERATION_TOOL_NAMES)
    if not caps.session_manager:
        denied_tools |= set(_SESSION_READ_TOOL_NAMES | _SESSION_RUNTIME_TOOL_NAMES)
    if not caps.task_runtime:
        denied_tools |= set(_SESSION_RUNTIME_TOOL_NAMES)
    if not caps.scheduler:
        denied_tools |= set(_SCHEDULER_RUNTIME_TOOL_NAMES)
    if not caps.gateway_config:
        denied_tools |= set(_GATEWAY_RUNTIME_TOOL_NAMES)

    if ctx.interaction_mode is InteractionMode.UNATTENDED:
        if not caps.channel_backing:
            denied_tools |= set(_CHANNEL_RUNTIME_TOOL_NAMES)
        denied_tools |= set(_ADMIN_RUNTIME_TOOL_NAMES)

    allowed_tools = _remove_denied_from_allowed(allowed_tools, denied_tools)
    return replace(ctx, allowed_tools=allowed_tools, denied_tools=denied_tools)


def detect_runtime_tool_surface_capabilities(
    *,
    channel_backing: bool = False,
) -> ToolSurfaceCapabilities:
    """Detect tool runtime dependencies from the currently wired built-ins."""

    session_manager = False
    task_runtime = False
    scheduler = False
    gateway_config = False
    image_generation = True
    try:
        from opensquilla.tools.builtin import sessions

        session_manager = sessions.session_manager_available()
        task_runtime = sessions.task_runtime_available()
    except Exception:
        pass
    try:
        from opensquilla.tools.builtin import admin

        scheduler = admin.scheduler_available()
        gateway_config = admin.gateway_config_available()
    except Exception:
        pass
    try:
        image_generation = _detect_image_generation_capability()
    except Exception:
        image_generation = False
    return ToolSurfaceCapabilities(
        session_manager=session_manager,
        task_runtime=task_runtime,
        scheduler=scheduler,
        gateway_config=gateway_config,
        channel_backing=channel_backing,
        image_generation=image_generation,
    )


def _agent_policy_from_config(config: object, agent_id: str) -> ToolPolicy | None:
    agents = _get_field(config, "agents")
    if isinstance(agents, Mapping):
        return _policy_from_config(_get_field(agents.get(agent_id), "tools"))

    entries = agents if isinstance(agents, list | tuple) else _get_field(agents, "list", [])
    if isinstance(entries, list | tuple):
        for entry in entries:
            if _get_field(entry, "id") == agent_id:
                return _policy_from_config(_get_field(entry, "tools"))
    return None


def _channel_entry_policy_from_config(
    config: object, ctx: ToolContext
) -> tuple[
    ToolPolicy | None,
    ToolPolicy | None,
]:
    if not ctx.channel_kind:
        return None, None

    channels = _get_field(config, "channels")
    channel_cfg = _get_field(channels, ctx.channel_kind)
    if channel_cfg is None:
        return None, None

    entries: object = None
    for field_name in ("groups", "channels", "rooms"):
        entries = _get_field(channel_cfg, field_name)
        if isinstance(entries, Mapping):
            break
    if not isinstance(entries, Mapping):
        return None, None

    default_policy = _policy_from_config(entries.get("*"))
    specific_policy = _policy_from_config(entries.get(ctx.channel_id or ""))
    return default_policy, specific_policy


def _apply_channel_layer(
    allowed_tools: set[str] | None,
    channel_denied: set[str],
    policy: ToolPolicy | None,
    available_tools: frozenset[str],
) -> tuple[set[str] | None, set[str]]:
    if policy is None:
        return allowed_tools, channel_denied
    allowed_tools = _add_allowed(
        allowed_tools,
        _expand_selectors(policy.allow | policy.also_allow, available_tools),
    )
    channel_denied |= _expand_selectors(policy.deny, available_tools)
    return allowed_tools, channel_denied


def _apply_sender_layer(
    allowed_tools: set[str] | None,
    channel_denied: set[str],
    policy: ToolPolicy | None,
    available_tools: frozenset[str],
) -> tuple[set[str] | None, set[str]]:
    if policy is None:
        return allowed_tools, channel_denied
    also_allowed = _expand_selectors(policy.also_allow, available_tools)
    channel_denied -= also_allowed
    allowed_tools = _add_allowed(allowed_tools, _expand_selectors(policy.allow, available_tools))
    allowed_tools = _add_allowed(allowed_tools, also_allowed)
    channel_denied |= _expand_selectors(policy.deny, available_tools)
    return allowed_tools, channel_denied


def apply_tool_policy(
    ctx: ToolContext,
    *,
    available_tools: list[str],
    global_policy: ToolPolicy | None = None,
    agent_policy: ToolPolicy | None = None,
    default_channel_policy: ToolPolicy | None = None,
    channel_policy: ToolPolicy | None = None,
) -> ToolContext:
    """Return a ``ToolContext`` with resolved allow/deny sets.

    Global and agent policy establish the base allowlist and hard denies.
    Agent profile overrides global profile. Channel/default/sender layers can
    further restrict or add tools, but global/agent denies still win.
    """

    available = frozenset(available_tools)
    allowed_tools = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None
    denied_tools = set(ctx.denied_tools)

    allowed_tools, denied_tools = _apply_base_policy(
        allowed_tools,
        denied_tools,
        global_policy,
        available,
    )
    allowed_tools, denied_tools = _apply_base_policy(
        allowed_tools,
        denied_tools,
        agent_policy,
        available,
        profile_overrides=True,
    )
    hard_denied = set(denied_tools)

    channel_denied: set[str] = set()
    allowed_tools, channel_denied = _apply_channel_layer(
        allowed_tools,
        channel_denied,
        default_channel_policy,
        available,
    )
    allowed_tools, channel_denied = _apply_sender_layer(
        allowed_tools,
        channel_denied,
        _sender_policy(default_channel_policy, ctx.sender_id),
        available,
    )
    allowed_tools, channel_denied = _apply_channel_layer(
        allowed_tools,
        channel_denied,
        channel_policy,
        available,
    )
    allowed_tools, channel_denied = _apply_sender_layer(
        allowed_tools,
        channel_denied,
        _sender_policy(channel_policy, ctx.sender_id),
        available,
    )

    denied_tools = hard_denied | channel_denied
    if allowed_tools is not None:
        allowed_tools -= denied_tools

    return replace(ctx, allowed_tools=allowed_tools, denied_tools=denied_tools)


def apply_tool_policy_layer(
    ctx: ToolContext,
    policy: object,
    *,
    available_tools: list[str] | set[str] | frozenset[str],
    hard_denied: set[str] | frozenset[str] | None = None,
) -> ToolContext:
    """Apply one declarative policy layer to an existing context.

    This is used for persisted cron job policy carried through route metadata.
    It intentionally keeps the caller's current allowlist unless the policy
    selects a narrower named profile, and reapplies ``hard_denied`` at the end
    so lower layers cannot revive denied tools.
    """

    parsed = _policy_from_config(policy)
    if parsed is None:
        return ctx
    allowed_tools = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None
    denied_tools = set(ctx.denied_tools)
    allowed_tools, denied_tools = _apply_base_policy(
        allowed_tools,
        denied_tools,
        parsed,
        frozenset(available_tools),
        profile_overrides=False,
    )
    if hard_denied:
        denied_tools |= set(hard_denied)
    if allowed_tools is not None:
        allowed_tools -= denied_tools
    return replace(ctx, allowed_tools=allowed_tools, denied_tools=denied_tools)


def apply_tool_policy_from_config(
    ctx: ToolContext,
    *,
    available_tools: list[str],
    config: object | None,
) -> ToolContext:
    """Apply config-shaped tool policy to a context.

    Supported config shape intentionally mirrors the documented policy concepts:
    ``config.tools``, ``config.agents[agent_id].tools`` or
    ``config.agents.list[].tools``, and channel entries such as
    ``config.channels.telegram.groups["room"].tools`` with optional
    ``toolsBySender``.
    """

    if config is None:
        return ctx
    default_channel_policy, channel_policy = _channel_entry_policy_from_config(config, ctx)
    return apply_tool_policy(
        ctx,
        available_tools=available_tools,
        global_policy=_policy_from_config(_get_field(config, "tools")),
        agent_policy=_agent_policy_from_config(config, ctx.agent_id),
        default_channel_policy=default_channel_policy,
        channel_policy=channel_policy,
    )
