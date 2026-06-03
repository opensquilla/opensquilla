"""Runtime facade for the sandbox subsystem.

This module owns the *process-wide* glue between:

* :class:`~opensquilla.sandbox.config.SandboxSettings` — operator configuration
* :class:`~opensquilla.sandbox.governance.ApprovalGate` — human approval bridge
* :class:`~opensquilla.sandbox.governance.DenialLedger` — §8.5 denial bookkeeping
* :class:`~opensquilla.sandbox.stale_output_cache.StaleOutputCache` — §8.3 hygiene
* :class:`~opensquilla.sandbox.backend.Backend` — the concrete isolation layer

The rest of the code base talks to the sandbox through three entry points:

* :func:`configure_runtime` — called exactly once during gateway boot.
* :func:`get_runtime` — cheap accessor for tool handlers.
* :func:`sandboxed` — a decorator factory for async tool handlers that
  threads the governance gate and (optionally) a real backend execution.

The decorator is intentionally conservative: it consults the gate with the
resolved policy and denies with a structured envelope before the wrapped
handler runs. Whether the handler then also delegates to a sandbox backend
for the actual command is an orthogonal decision — the filesystem tools run
in-process after the gate, while the shell tools additionally spawn through
:meth:`Backend.run`.

Nothing in this module performs isolation by itself; it routes to whichever
backend :func:`opensquilla.sandbox.backend.select_backend` picked for the current
host.
"""

from __future__ import annotations

import contextvars
import dataclasses
import functools
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from opensquilla.sandbox.backend import Backend, NoopBackend, select_backend
from opensquilla.sandbox.config import EffectiveMode, SandboxSettings
from opensquilla.sandbox.domain_validation import validate_domain_pattern
from opensquilla.sandbox.escalation import (
    build_backend_failure_approval_params,
    build_network_approval_params,
    consume_persisted_temporary_network_grant,
    consume_temporary_network_grant,
    context_with_temporary_network_grants,
    current_tool_run_context,
    has_temporary_network_grant,
    remember_resolved_run_context,
    request_sandbox_approval,
    reset_resolved_run_context_overlays,
)
from opensquilla.sandbox.governance import (
    ApprovalGate,
    DenialLedger,
    action_fingerprint,
    gate_execution,
    on_successful_exec,
)
from opensquilla.sandbox.network_guard import NetworkDecision, decide_network_access
from opensquilla.sandbox.network_proxy import SandboxProxyServer
from opensquilla.sandbox.path_validation import (
    decide_path_access,
    normalize_mount_access,
    normalize_path,
)
from opensquilla.sandbox.policy import LevelHints, build_policy, select_level
from opensquilla.sandbox.run_context import DomainGrant, RunContext
from opensquilla.sandbox.run_context_service import auto_add_trusted_domain_grant
from opensquilla.sandbox.run_mode import RunMode, normalize_run_mode
from opensquilla.sandbox.stale_output_cache import StaleOutputCache, get_stale_output_cache
from opensquilla.sandbox.types import (
    ALLOW,
    ApprovalDecision,
    DenialReason,
    DenialResult,
    FollowupTag,
    MountSpec,
    NetworkMode,
    NetworkProxySpec,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SandboxResult,
    SecurityLevel,
    SuggestedNextStep,
)

log = logging.getLogger(__name__)

_MANAGED_NETWORK_PROXY_URL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "opensquilla_managed_network_proxy_url",
    default=None,
)

_IN_PROCESS_NETWORK_TAGS: frozenset[str] = frozenset(
    {"network.fetch", "network.http", "web.fetch"}
)
_SEARCH_PROVIDER_SYSTEM_DOMAINS: dict[str, tuple[str, ...]] = {
    "brave": ("api.search.brave.com",),
    "duckduckgo": ("html.duckduckgo.com",),
}


# ─── Approval queue / context protocols ──────────────────────────────────


class _ApprovalQueueLike(Protocol):
    """Structural subset of :class:`opensquilla.gateway.approval_queue.ApprovalQueue`."""

    def request(self, namespace: str = ..., params: dict | None = ...) -> str: ...

    async def wait(self, approval_id: str, timeout: float | None = ...) -> bool: ...

    def resolve(self, approval_id: str, approved: bool) -> None: ...


# ─── Runtime state ────────────────────────────────────────────────────────


@dataclass
class SandboxRuntime:
    """Process-wide sandbox runtime assembled from settings.

    The object is immutable after construction from the caller's point of
    view; callers either pass it around explicitly (tests) or fetch it via
    :func:`get_runtime`.
    """

    settings: SandboxSettings
    effective: EffectiveMode
    backend: Backend
    gate: ApprovalGate
    ledger: DenialLedger
    cache: StaleOutputCache
    workspace: Path


_runtime: SandboxRuntime | None = None


def configure_runtime(
    settings: SandboxSettings,
    *,
    approval_queue: _ApprovalQueueLike | None = None,
    stale_cache: StaleOutputCache | None = None,
    workspace: Path | None = None,
) -> SandboxRuntime:
    """Build the process-wide :class:`SandboxRuntime`.

    Called exactly once from :func:`opensquilla.gateway.boot.build_services` after
    :meth:`SandboxSettings.validate_combination` has emitted its log line.
    Tests may call it repeatedly; each call replaces the prior runtime.
    """
    global _runtime

    effective = settings.validate_combination()
    cache = stale_cache if stale_cache is not None else get_stale_output_cache()
    ledger = DenialLedger(
        threshold=max(1, settings.denial_threshold),
        stale_output_cache=cache,
    )
    backend: Backend
    if not effective.sandbox_enabled:
        backend = NoopBackend()
    else:
        backend = select_backend(settings)
        if backend.name == "noop" and settings.backend != "noop":
            raise SandboxBackendError(
                "sandbox=true requires a real backend; refusing implicit noop fallback"
            )

    if approval_queue is not None:
        gate = ApprovalGate(approval_queue)
    else:
        # Lazy import: avoids a circular import when gateway is not yet loaded.
        from opensquilla.gateway.approval_queue import get_approval_queue

        gate = ApprovalGate(get_approval_queue())

    ws = workspace if workspace is not None else Path.cwd()
    _runtime = SandboxRuntime(
        settings=settings,
        effective=effective,
        backend=backend,
        gate=gate,
        ledger=ledger,
        cache=cache,
        workspace=ws,
    )
    log.info(
        "sandbox.runtime_configured: backend=%s level=%s grading=%s insecure=%s",
        backend.name,
        effective.default_level.label,
        effective.grading_enabled,
        effective.insecure_mode,
    )
    return _runtime


def get_runtime() -> SandboxRuntime | None:
    """Return the configured runtime or ``None`` when unconfigured.

    ``None`` is *not* an implicit opt-out: :func:`gate_action` fails closed
    (``DenialReason.RUNTIME_
    UNCONFIGURED``) whenever the runtime is missing. Callers that genuinely
    want sandbox-off behaviour in tests / CLI one-shots must call
    :func:`configure_runtime` with ``SandboxSettings(sandbox=False)`` rather
    than relying on the ``None`` branch.
    """
    return _runtime


def reset_runtime() -> None:
    """Drop the process-wide runtime. Test helper."""
    global _runtime
    _runtime = None
    reset_resolved_run_context_overlays()


# ─── Core helpers ─────────────────────────────────────────────────────────


def _default_argv(action_kind: str, arguments: dict[str, Any]) -> tuple[str, ...]:
    """Derive a stable argv-like tuple from tool kwargs for fingerprinting.

    We avoid guessing: the caller can pass an explicit ``argv_factory`` to
    :func:`sandboxed`. When nothing is supplied we fall back to a simple
    serialisation of the arguments so the fingerprint is still deterministic
    per call site.
    """
    if "command" in arguments and isinstance(arguments["command"], str):
        return (action_kind, arguments["command"])
    if "argv" in arguments and isinstance(arguments["argv"], (list, tuple)):
        return (action_kind, *(str(x) for x in arguments["argv"]))
    payload = json.dumps({k: _stringify(v) for k, v in sorted(arguments.items())})
    return (action_kind, payload)


def _stringify(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stringify(x) for x in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}={_stringify(v)}" for k, v in sorted(value.items())) + "}"
    return type(value).__name__


def _resolve_session_id(runtime: SandboxRuntime, session_id: str | None) -> str:
    if session_id:
        return session_id
    try:
        from opensquilla.tools.types import current_tool_context

        ctx = current_tool_context.get()
    except Exception:  # pragma: no cover - defensive
        ctx = None
    if ctx is not None and getattr(ctx, "session_key", None):
        return str(ctx.session_key)
    return "default"


def _resolve_workspace(runtime: SandboxRuntime, cwd: str | None) -> Path:
    if cwd:
        p = Path(cwd)
        if p.is_absolute():
            return p
    try:
        from opensquilla.tools.types import current_tool_context

        ctx = current_tool_context.get()
    except Exception:  # pragma: no cover - defensive
        ctx = None
    workspace_dir = getattr(ctx, "workspace_dir", None) if ctx is not None else None
    if isinstance(workspace_dir, str) and workspace_dir:
        wp = Path(workspace_dir)
        if wp.is_absolute():
            return wp
    if runtime.workspace.is_absolute():
        return runtime.workspace
    return Path.cwd()


def _session_mounts_for_policy(workspace: Path) -> tuple[MountSpec, ...]:
    try:
        from opensquilla.tools.types import current_tool_context

        ctx = current_tool_context.get()
    except Exception:  # pragma: no cover - defensive
        ctx = None
    raw_mounts = getattr(ctx, "sandbox_mounts", None) if ctx is not None else None
    if not isinstance(raw_mounts, list):
        return ()

    mounts: list[MountSpec] = []
    for item in raw_mounts:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        access = normalize_mount_access(item.get("access"))
        try:
            host_path = normalize_path(raw_path)
            decision = decide_path_access(
                host_path,
                workspace=workspace,
                mounts=(),
                write=access == "rw",
            )
        except (OSError, RuntimeError):
            continue
        if decision.status == "blocked":
            continue
        mounts.append(
            MountSpec(
                host_path=host_path,
                sandbox_path=host_path,
                mode=access,
                required=False,
            )
        )
    return tuple(mounts)


def build_request(
    *,
    action_kind: str,
    argv: tuple[str, ...],
    cwd: Path,
    policy: SandboxPolicy,
    env: dict[str, str] | None = None,
    reason: str = "",
) -> SandboxRequest:
    """Assemble a :class:`SandboxRequest` for the current action.

    Exposed for callers (notably shell.py) that want to fingerprint a
    command without going through the decorator.
    """
    return SandboxRequest(
        argv=argv,
        cwd=cwd,
        action_kind=action_kind,
        policy=policy,
        env=dict(env or {}),
        reason=reason,
    )


async def gate_action(
    *,
    action_kind: str,
    argv: tuple[str, ...],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    followup_tag: FollowupTag = FollowupTag.NONE,
    hints: LevelHints | None = None,
    session_id: str | None = None,
    reason: str = "",
    runtime: SandboxRuntime | None = None,
) -> tuple[ApprovalDecision, SandboxPolicy, SandboxRequest]:
    """Consult the approval gate for an action.

    Returns a triple ``(decision, policy, request)``. The ``request`` and
    ``policy`` are always populated even on denial so callers can log
    action fingerprints and levels uniformly.
    """
    rt = runtime or get_runtime()
    if rt is None:
        # Fail-closed: a side-effecting tool reached the sandbox gate before
        # ``configure_runtime()`` ran. Silently allowing would turn a boot
        # order bug into unsandboxed host execution. Callers that genuinely
        # want sandbox off must pass an explicit ``SandboxSettings(sandbox=
        # False)`` runtime (via :func:`configure_runtime`) rather than
        # relying on ``None``.
        ws = Path(cwd) if cwd and Path(cwd).is_absolute() else Path.cwd()
        settings = SandboxSettings(sandbox=False, security_grading=False)
        policy = build_policy(SecurityLevel.STANDARD, action_kind, ws, settings, trusted=True)
        req = build_request(
            action_kind=action_kind,
            argv=argv,
            cwd=ws,
            policy=policy,
            env=env,
            reason=reason,
        )
        from opensquilla.sandbox.governance import action_fingerprint

        log.warning(
            "sandbox.runtime_unconfigured: action_kind=%s — denying fail-closed",
            action_kind,
        )
        denial = DenialResult(
            reason=DenialReason.RUNTIME_UNCONFIGURED,
            suggested_next_step=SuggestedNextStep.ASK_USER,
            level=policy.level,
            action_fingerprint=action_fingerprint(req),
            message=(
                "Sandbox runtime is not configured. Side-effecting tools "
                "refuse to run until configure_runtime() has been called. "
                "This is a fail-closed guard; do not retry without fixing "
                "the boot order."
            ),
            retryable=False,
        )
        return denial, policy, req

    workspace = _resolve_workspace(rt, str(cwd) if cwd else None)
    level = (
        select_level(action_kind, hints)
        if rt.effective.grading_enabled
        else rt.effective.default_level
    )
    policy = build_policy(
        level,
        action_kind,
        workspace,
        rt.settings,
        trusted=(hints is None or hints.trusted_source),
        session_mounts=_session_mounts_for_policy(workspace),
    )
    request = build_request(
        action_kind=action_kind,
        argv=argv,
        cwd=workspace,
        policy=policy,
        env=env,
        reason=reason,
    )
    decision = await gate_execution(
        request,
        policy,
        session_id=_resolve_session_id(rt, session_id),
        ledger=rt.ledger,
        approval_gate=rt.gate,
        followup_tag=followup_tag,
    )
    return decision, policy, request


async def run_under_backend(
    request: SandboxRequest,
    *,
    runtime: SandboxRuntime | None = None,
) -> SandboxResult:
    """Dispatch ``request`` through the configured backend.

    The gate must already have returned :data:`ALLOW` before this is called.
    A missing runtime is a boot-order or caller-contract bug; callers that
    need noop behavior must configure an explicit runtime with ``backend="noop"``.
    """
    rt = runtime or get_runtime()
    if rt is None:
        raise SandboxBackendError(
            "Sandbox runtime is not configured; refusing to run backend request"
        )
    if (
        request.policy.network == NetworkMode.PROXY_ALLOWLIST
        and request.policy.network_proxy is None
    ):
        return await _run_with_managed_network_proxy(request, rt)
    return await rt.backend.run(request)


def _current_run_context_for_network_proxy() -> RunContext | None:
    return current_tool_run_context()


def _current_sandbox_persistence_handles() -> tuple[Any | None, Any | None]:
    try:
        from opensquilla.tools.builtin import sessions as sessions_mod
    except Exception:  # pragma: no cover - defensive
        return None, None
    return getattr(sessions_mod, "_session_manager", None), getattr(
        sessions_mod,
        "_gateway_config",
        None,
    )


async def _persist_auto_trusted_host_if_available(
    request: SandboxRequest,
    runtime: SandboxRuntime,
    *,
    decision: NetworkDecision,
) -> None:
    if decision.reason != "auto_trusted" or decision.source != "auto_trusted:chat":
        return
    session_key = _resolve_session_id(runtime, None)
    if not session_key:
        return
    session_manager, config = _current_sandbox_persistence_handles()
    if session_manager is None or config is None:
        return
    workspace = str(request.cwd)
    try:
        context = await auto_add_trusted_domain_grant(
            session_manager,
            session_key,
            domain=decision.normalized_host,
            config=config,
            workspace=workspace,
        )
    except Exception:
        return
    remember_resolved_run_context(
        session_key,
        workspace,
        context,
        session_manager=session_manager,
        config=config,
    )


async def _run_with_managed_network_proxy(
    request: SandboxRequest,
    runtime: SandboxRuntime,
) -> SandboxResult:
    context = _current_run_context_for_network_proxy()
    if context is None:
        raise SandboxBackendError(
            "NetworkMode.PROXY_ALLOWLIST requires Run Context grants to start "
            "the managed network proxy"
        )
    fingerprint = action_fingerprint(request)
    context = context_with_temporary_network_grants(
        context,
        fingerprint=fingerprint,
    )
    original_context = _current_run_context_for_network_proxy()
    explicit_targets = _explicit_network_target_hosts(request.action_kind, request.argv)
    for host in explicit_targets:
        decision = decide_network_access(host, context)
        await _persist_auto_trusted_host_if_available(
            request,
            runtime,
            decision=decision,
        )
    consumed_hosts: set[str] = set()

    def _decide(host: str) -> NetworkDecision:
        decision = decide_network_access(host, context)
        if (
            decision.status == "allow"
            and has_temporary_network_grant(
                original_context,
                host=decision.normalized_host,
                fingerprint=fingerprint,
            )
        ):
            consume_temporary_network_grant(
                session_key=_resolve_session_id(runtime, None),
                workspace=str(request.cwd),
                host=decision.normalized_host,
                fingerprint=fingerprint,
            )
            consumed_hosts.add(decision.normalized_host)
        return decision

    proxy = SandboxProxyServer(_decide)
    await proxy.start()
    try:
        policy = dataclasses.replace(
            request.policy,
            network_proxy=NetworkProxySpec(host=proxy.host, port=proxy.port),
        )
        return await runtime.backend.run(request.with_policy(policy))
    finally:
        for host in consumed_hosts:
            await consume_persisted_temporary_network_grant(
                session_key=_resolve_session_id(runtime, None),
                workspace=str(request.cwd),
                host=host,
                fingerprint=fingerprint,
            )
        await proxy.stop()


def current_managed_network_proxy_url() -> str | None:
    """Return the context-local managed proxy URL for in-process network tools."""
    return _MANAGED_NETWORK_PROXY_URL.get()


def managed_network_httpx_kwargs() -> dict[str, object]:
    """Return httpx proxy kwargs for the current managed-network context.

    When a sandboxed in-process network tool is running under
    ``NetworkMode.PROXY_ALLOWLIST``, callers must use an explicit proxy and
    disable ambient env proxy lookup. Outside that context, preserve the
    existing ``opensquilla.env.trust_env()`` behavior.
    """
    proxy_url = current_managed_network_proxy_url()
    if proxy_url:
        return {"proxy": proxy_url, "trust_env": False}
    from opensquilla.env import trust_env

    return {"trust_env": trust_env()}


async def record_success(
    request: SandboxRequest,
    payload: Any,
    *,
    session_id: str | None = None,
    runtime: SandboxRuntime | None = None,
) -> str:
    """Record a successful execution for §8.3 hygiene purposes."""
    rt = runtime or get_runtime()
    cache = rt.cache if rt is not None else get_stale_output_cache()
    sid = _resolve_session_id(rt, session_id) if rt is not None else (session_id or "default")
    return await on_successful_exec(request, payload, session_id=sid, cache=cache)


# ─── Decorator ────────────────────────────────────────────────────────────


HandlerT = Callable[..., Awaitable[Any]]


def sandboxed(
    kind: str,
    *,
    hints: LevelHints | None = None,
    argv_factory: Callable[[dict[str, Any]], tuple[str, ...]] | None = None,
    cwd_factory: Callable[[dict[str, Any]], str | None] | None = None,
    record_payload: bool = True,
) -> Callable[[HandlerT], HandlerT]:
    """Wrap an async tool handler with the sandbox gate.

    Parameters:
        kind: The ``action_kind`` tag (see
            :func:`opensquilla.sandbox.policy.select_level`). Required.
        hints: Optional static :class:`LevelHints`. Tools whose risk profile
            depends on arguments should supply a per-call hints factory by
            using ``@sandboxed`` on a small wrapper instead.
        argv_factory: Custom function to derive the argv-like tuple used for
            fingerprinting. Falls back to a stable serialisation when unset.
        cwd_factory: Custom function to derive the workspace path for the
            call. Falls back to :class:`ToolContext.workspace_dir`.
        record_payload: When ``True`` (the default), record the handler's
            return value in the stale-output cache on success.

    The wrapped handler accepts a hidden keyword argument
    ``_sandbox_followup`` that the agent may set to ``"lower_privilege"``,
    ``"explain"``, or ``"narrower_approval"`` to tag a follow-up after a
    prior denial (see §8.4). The kwarg is consumed before the real handler
    runs so downstream signatures are unaffected.
    """

    def decorator(fn: HandlerT) -> HandlerT:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            followup_raw = kwargs.pop("_sandbox_followup", None)
            followup_tag = _coerce_followup(followup_raw)

            bound_args = _safe_bind(sig, args, kwargs)
            argv = argv_factory(bound_args) if argv_factory else _default_argv(kind, bound_args)
            cwd_raw = cwd_factory(bound_args) if cwd_factory else bound_args.get("workdir")
            cwd = Path(cwd_raw) if isinstance(cwd_raw, str) and cwd_raw else None

            from opensquilla.tools.run_mode import full_host_access_active

            if full_host_access_active():
                return await fn(*args, **kwargs)

            decision, policy, request = await gate_action(
                action_kind=kind,
                argv=argv,
                cwd=cwd,
                env=_string_env(bound_args.get("env")),
                followup_tag=followup_tag,
                hints=hints,
            )
            if isinstance(decision, DenialResult):
                return json.dumps(decision.to_dict())

            if policy.network == NetworkMode.NONE and _is_in_process_network_action(kind):
                rt = get_runtime()
                if rt is None:
                    return json.dumps(
                        DenialResult(
                            reason=DenialReason.RUNTIME_UNCONFIGURED,
                            suggested_next_step=SuggestedNextStep.ASK_USER,
                            level=policy.level,
                            action_fingerprint=action_fingerprint(request),
                            message=(
                                "Sandbox runtime is not configured. "
                                "Network-disabled in-process tools refuse to run."
                            ),
                            retryable=False,
                        ).to_dict()
                    )
                denial = await _managed_in_process_denial(
                    request,
                    rt,
                    "Sandbox network is disabled for this in-process network tool.",
                )
                return json.dumps(denial.to_dict())

            if policy.network == NetworkMode.PROXY_ALLOWLIST:
                rt = get_runtime()
                if rt is None:
                    return json.dumps(
                        DenialResult(
                            reason=DenialReason.RUNTIME_UNCONFIGURED,
                            suggested_next_step=SuggestedNextStep.ASK_USER,
                            level=policy.level,
                            action_fingerprint=action_fingerprint(request),
                            message=(
                                "Sandbox runtime is not configured. "
                                "Managed in-process network tools refuse to run."
                            ),
                            retryable=False,
                        ).to_dict()
                    )
                prepared = await _prepare_in_process_managed_network(request, rt)
                if isinstance(prepared, DenialResult):
                    return json.dumps(prepared.to_dict())
                if isinstance(prepared, dict):
                    return json.dumps(prepared)
                result = await _run_in_process_with_managed_network(
                    fn,
                    args,
                    kwargs,
                    context=prepared,
                )
            else:
                result = await fn(*args, **kwargs)
            if record_payload:
                try:
                    await record_success(request, result)
                except Exception:  # pragma: no cover - cache failures should never break tools
                    log.exception("sandbox.record_success_failed", extra={"kind": kind})
            return result

        setattr(wrapper, "__sandbox_kind__", kind)
        return wrapper

    return decorator


def _safe_bind(
    sig: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except TypeError:
        return dict(kwargs)


def _coerce_followup(raw: Any) -> FollowupTag:
    if raw is None:
        return FollowupTag.NONE
    if isinstance(raw, FollowupTag):
        return raw
    if isinstance(raw, str):
        try:
            return FollowupTag(raw)
        except ValueError:
            return FollowupTag.NONE
    return FollowupTag.NONE


def _string_env(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {str(k): str(v) for k, v in value.items()}


async def _prepare_in_process_managed_network(
    request: SandboxRequest,
    runtime: SandboxRuntime,
) -> RunContext | DenialResult | dict[str, object]:
    context = _current_run_context_for_network_proxy()
    if context is None:
        return await _managed_in_process_denial(
            request,
            runtime,
            "NetworkMode.PROXY_ALLOWLIST requires Run Context grants to run "
            "in-process network tools through the managed proxy.",
        )
    fingerprint = action_fingerprint(request)
    original_context = context
    context = context_with_temporary_network_grants(
        context,
        fingerprint=fingerprint,
    )
    system_domains = _system_domain_grants_for_request(request)
    effective_context = _context_with_system_domain_grants(context, system_domains)
    targets = _explicit_network_target_hosts(request.action_kind, request.argv)
    if not targets:
        if system_domains:
            return effective_context
        return await _managed_in_process_denial(
            request,
            runtime,
            "NetworkMode.PROXY_ALLOWLIST requires an explicit URL target for "
            "in-process network tools; provider search actions cannot safely "
            "be constrained without provider-specific plumbing.",
        )
    for host in targets:
        decision = decide_network_access(host, effective_context)
        if decision.status == "allow":
            await _persist_auto_trusted_host_if_available(
                request,
                runtime,
                decision=decision,
            )
            continue
        if decision.status == "ask":
            params = build_network_approval_params(
                decision,
                session_key=_resolve_session_id(runtime, None),
                workspace=str(request.cwd),
                fingerprint=fingerprint,
            )
            if params is not None:
                return request_sandbox_approval(
                    params,
                    message=(
                        "This network target is outside the current managed-network grants. "
                        "Resolve this approval and retry."
                    ),
                )
            return await _managed_in_process_denial(
                request,
                runtime,
                (
                    "NetworkMode.PROXY_ALLOWLIST denied in-process network "
                    f"target {host!r}: {decision.reason}."
                ),
            )
        return await _managed_in_process_denial(
            request,
            runtime,
            (
                "NetworkMode.PROXY_ALLOWLIST denied in-process network "
                f"target {host!r}: {decision.reason}."
            ),
        )
    for host in targets:
        if has_temporary_network_grant(
            original_context,
            host=host,
            fingerprint=fingerprint,
        ):
            consume_temporary_network_grant(
                session_key=_resolve_session_id(runtime, None),
                workspace=str(request.cwd),
                host=host,
                fingerprint=fingerprint,
            )
            await consume_persisted_temporary_network_grant(
                session_key=_resolve_session_id(runtime, None),
                workspace=str(request.cwd),
                host=host,
                fingerprint=fingerprint,
            )
    return effective_context


async def _managed_in_process_denial(
    request: SandboxRequest,
    runtime: SandboxRuntime,
    message: str,
) -> DenialResult:
    denial = DenialResult(
        reason=DenialReason.POLICY_DENIED,
        suggested_next_step=SuggestedNextStep.REPLAN,
        level=request.policy.level,
        action_fingerprint=action_fingerprint(request),
        message=message,
        retryable=False,
    )
    await runtime.ledger.record_denial(
        _resolve_session_id(runtime, None),
        denial.action_fingerprint,
        denial.reason,
    )
    return denial


async def _run_in_process_with_managed_network(
    fn: HandlerT,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    context: RunContext,
) -> Any:
    proxy = SandboxProxyServer(lambda host: decide_network_access(host, context))
    await proxy.start()
    try:
        proxy_url = f"http://{proxy.host}:{proxy.port}"
        token = _MANAGED_NETWORK_PROXY_URL.set(proxy_url)
        try:
            return await fn(*args, **kwargs)
        finally:
            _MANAGED_NETWORK_PROXY_URL.reset(token)
    finally:
        await proxy.stop()


async def guard_in_process_network_action(
    *,
    action_kind: str,
    argv: tuple[str, ...],
    runtime: SandboxRuntime | None = None,
) -> DenialResult | dict[str, object] | None:
    """Fail-close helper for in-process network paths that bypass decorators.

    Returns a denial only when the resolved sandbox policy requires managed
    networking and the action cannot safely run. A ``None`` result means the
    caller may continue with its existing non-managed behavior.
    """
    decision, policy, request = await gate_action(
        action_kind=action_kind,
        argv=argv,
        runtime=runtime,
    )
    if isinstance(decision, DenialResult):
        return decision
    if policy.network == NetworkMode.NONE and _is_in_process_network_action(action_kind):
        rt = runtime or get_runtime()
        if rt is None:
            return None
        return await _managed_in_process_denial(
            request,
            rt,
            "Sandbox network is disabled for this in-process network tool.",
        )
    if policy.network != NetworkMode.PROXY_ALLOWLIST:
        return None
    rt = runtime or get_runtime()
    if rt is None:
        return None
    prepared = await _prepare_in_process_managed_network(request, rt)
    if isinstance(prepared, (DenialResult, dict)):
        return prepared
    return None


async def run_in_process_network_action(
    *,
    action_kind: str,
    argv: tuple[str, ...],
    callback: Callable[[], Awaitable[Any]],
    runtime: SandboxRuntime | None = None,
) -> Any | DenialResult | dict[str, object]:
    """Run an undecorated in-process network action under sandbox networking.

    Some gateway RPC handlers call provider code directly instead of going
    through a registered tool decorator. This helper gives those paths the
    same fail-closed and managed-proxy behavior as :func:`sandboxed`.
    """
    decision, policy, request = await gate_action(
        action_kind=action_kind,
        argv=argv,
        runtime=runtime,
    )
    if isinstance(decision, DenialResult):
        return decision

    if policy.network == NetworkMode.NONE and _is_in_process_network_action(action_kind):
        rt = runtime or get_runtime()
        if rt is None:
            return DenialResult(
                reason=DenialReason.RUNTIME_UNCONFIGURED,
                suggested_next_step=SuggestedNextStep.ASK_USER,
                level=policy.level,
                action_fingerprint=action_fingerprint(request),
                message=(
                    "Sandbox runtime is not configured. "
                    "Network-disabled in-process tools refuse to run."
                ),
                retryable=False,
            )
        return await _managed_in_process_denial(
            request,
            rt,
            "Sandbox network is disabled for this in-process network tool.",
        )

    if policy.network != NetworkMode.PROXY_ALLOWLIST:
        return await callback()

    rt = runtime or get_runtime()
    if rt is None:
        return DenialResult(
            reason=DenialReason.RUNTIME_UNCONFIGURED,
            suggested_next_step=SuggestedNextStep.ASK_USER,
            level=policy.level,
            action_fingerprint=action_fingerprint(request),
            message=(
                "Sandbox runtime is not configured. "
                "Managed in-process network tools refuse to run."
            ),
            retryable=False,
        )
    prepared = await _prepare_in_process_managed_network(request, rt)
    if isinstance(prepared, DenialResult):
        return prepared
    if isinstance(prepared, dict):
        return prepared
    return await _run_in_process_with_managed_network(
        callback,
        (),
        {},
        context=prepared,
    )


def _explicit_network_target_hosts(action_kind: str, argv: tuple[str, ...]) -> tuple[str, ...]:
    tool_name = argv[0] if argv else ""
    if tool_name == "web_search":
        return ()
    hosts: list[str] = []
    for value in argv[1:]:
        host = _explicit_network_target_host(action_kind, value)
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _is_in_process_network_action(action_kind: str) -> bool:
    return action_kind in _IN_PROCESS_NETWORK_TAGS


def _system_domain_grants_for_request(request: SandboxRequest) -> tuple[str, ...]:
    tool_name = request.argv[0] if request.argv else ""
    if tool_name != "web_search":
        return ()
    try:
        from opensquilla.tools.builtin.web import (
            get_active_provider,
            get_search_fallback_policy,
        )

        provider = get_active_provider()
        fallback_policy = get_search_fallback_policy()
    except Exception:  # pragma: no cover - defensive against import-time cycles
        return ()

    domains: list[str] = []
    for domain in _SEARCH_PROVIDER_SYSTEM_DOMAINS.get(provider, ()):
        if domain not in domains:
            domains.append(domain)
    if fallback_policy == "network" and provider != "duckduckgo":
        for domain in _SEARCH_PROVIDER_SYSTEM_DOMAINS.get("duckduckgo", ()):
            if domain not in domains:
                domains.append(domain)
    return tuple(domains)


def _context_with_system_domain_grants(
    context: RunContext,
    domains: tuple[str, ...],
) -> RunContext:
    if not domains:
        return context
    existing = {grant.domain for grant in context.domains}
    grants = list(context.domains)
    for domain in domains:
        if domain in existing:
            continue
        grants.append(DomainGrant(domain=domain, scope="chat", source="system"))
        existing.add(domain)
    if len(grants) == len(context.domains):
        return context
    return dataclasses.replace(context, domains=tuple(grants))


def _explicit_network_target_host(action_kind: str, value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    host = _host_from_http_url(text)
    if host:
        return host
    if action_kind != "web.fetch":
        decision = validate_domain_pattern(text)
        return decision.normalized if decision.status == "allowed" else None
    return None


def _host_from_http_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    return parsed.hostname.lower() if parsed.hostname else None


async def escalate_backend_denial(
    result: SandboxResult,
    request: SandboxRequest,
    policy: SandboxPolicy,
    *,
    runtime: SandboxRuntime | None = None,
) -> ApprovalDecision:
    """Escalate a seatbelt backend denial to the approval queue.

    Called post-execution when ``result.backend_notes`` is non-empty.
    Routes to the existing approval gate with ``require_approval=True`` so
    the user is asked whether to re-run the command without sandbox
    restrictions. Returns :data:`ALLOW` on approval or a
    :class:`DenialResult` with ``retryable=False`` on denial.
    """
    fp = action_fingerprint(request)
    notes_str = "; ".join(result.backend_notes)
    rt = runtime or get_runtime()
    if rt is None:
        return DenialResult(
            reason=DenialReason.SEATBELT_DENIED,
            suggested_next_step=SuggestedNextStep.ASK_USER,
            level=policy.level,
            action_fingerprint=fp,
            message=f"Sandbox denied the command ({notes_str}); no runtime to escalate.",
            retryable=False,
        )

    session_id = _resolve_session_id(rt, None)
    if _runtime_is_full_host_access(rt):
        denial = DenialResult(
            reason=DenialReason.SEATBELT_DENIED,
            suggested_next_step=SuggestedNextStep.ASK_USER,
            level=policy.level,
            action_fingerprint=fp,
            message=(
                f"Sandbox denied the command ({notes_str}). "
                "Full Host Access is active, so no sandbox escalation prompt was created."
            ),
            retryable=False,
        )
        await rt.ledger.record_denial(session_id, fp, denial.reason)
        return denial

    escalation_reason = f"host once requested after sandbox denied: {notes_str}"
    escalation_request = dataclasses.replace(request, reason=escalation_reason)
    escalation_policy = dataclasses.replace(policy, require_approval=True)

    decision = await rt.gate.gate(
        escalation_request,
        escalation_policy,
        session_id=session_id,
        extra_params=build_backend_failure_approval_params(
            session_key=session_id,
            workspace=str(request.cwd),
        ),
    )

    if not isinstance(decision, DenialResult):
        return ALLOW

    denial = DenialResult(
        reason=DenialReason.SEATBELT_DENIED,
        suggested_next_step=SuggestedNextStep.ASK_USER,
        level=policy.level,
        action_fingerprint=fp,
        message=f"Sandbox denied the command ({notes_str}). User did not grant approval.",
        retryable=False,
    )
    await rt.ledger.record_denial(session_id, fp, denial.reason)
    return denial


def _runtime_is_full_host_access(runtime: SandboxRuntime) -> bool:
    if runtime.settings.run_mode is not None:
        return normalize_run_mode(runtime.settings.run_mode) == RunMode.FULL
    context = current_tool_run_context()
    return context is not None and context.run_mode == RunMode.FULL


__all__ = [
    "SandboxRuntime",
    "action_fingerprint",
    "build_request",
    "configure_runtime",
    "current_managed_network_proxy_url",
    "escalate_backend_denial",
    "gate_action",
    "get_runtime",
    "guard_in_process_network_action",
    "managed_network_httpx_kwargs",
    "record_success",
    "reset_runtime",
    "run_in_process_network_action",
    "run_under_backend",
    "sandboxed",
]
