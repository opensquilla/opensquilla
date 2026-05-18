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

import dataclasses
import functools
import inspect
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from opensquilla.sandbox.backend import Backend, NoopBackend, select_backend
from opensquilla.sandbox.config import EffectiveMode, SandboxSettings
from opensquilla.sandbox.governance import (
    ApprovalGate,
    DenialLedger,
    action_fingerprint,
    gate_execution,
    on_successful_exec,
)
from opensquilla.sandbox.policy import LevelHints, build_policy, select_level
from opensquilla.sandbox.stale_output_cache import StaleOutputCache, get_stale_output_cache
from opensquilla.sandbox.types import (
    ALLOW,
    ApprovalDecision,
    DenialReason,
    DenialResult,
    FollowupTag,
    SandboxBackendError,
    SandboxPolicy,
    SandboxRequest,
    SandboxResult,
    SecurityLevel,
    SuggestedNextStep,
)

log = logging.getLogger(__name__)


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

    settings = _apply_host_compatibility(settings)
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


def _apply_host_compatibility(settings: SandboxSettings) -> SandboxSettings:
    """Adjust unsupported platform defaults before runtime selection.

    Some platforms currently have no executable sandbox backend in this
    package. Treating the generated default ``sandbox=true, backend=auto`` as a
    hard boot failure makes local CLI one-shots unusable, even for read-only
    file tools. Keep explicit backend choices fail-closed, but make the auto
    choice resolve to the same visible insecure mode an operator would get by
    setting ``sandbox=false``.
    """

    if (
        sys.platform.startswith("win")
        and settings.sandbox
        and settings.backend == "auto"
    ):
        log.warning(
            "sandbox.windows_auto_backend_unsupported: "
            "no Windows sandbox backend is available; disabling sandbox for this runtime"
        )
        return settings.model_copy(
            update={
                "sandbox": False,
                "security_grading": False,
            }
        )
    return settings


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
    return await rt.backend.run(request)


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
    escalation_request = dataclasses.replace(request, reason=f"sandbox denied: {notes_str}")
    escalation_policy = dataclasses.replace(policy, require_approval=True)

    decision = await rt.gate.gate(escalation_request, escalation_policy, session_id=session_id)

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


__all__ = [
    "SandboxRuntime",
    "action_fingerprint",
    "build_request",
    "configure_runtime",
    "escalate_backend_denial",
    "gate_action",
    "get_runtime",
    "record_success",
    "reset_runtime",
    "run_under_backend",
    "sandboxed",
]
