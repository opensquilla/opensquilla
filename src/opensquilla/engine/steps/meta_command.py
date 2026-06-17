"""Pipeline step + store for the manual ``/meta`` command launch path.

The ``/meta`` command surface does NOT start a meta-skill turn directly.
Instead the ``meta.run`` RPC stamps a *pending launch* into a small
session-keyed, in-process store; the surface then sends a normal turn.
On that next turn the :func:`meta_command_launch` pipeline step pops the
pending launch and writes ``ctx.metadata["meta_launch"] = {"name": ...}``,
which the agent bootstrap stage copies onto ``config.metadata`` so the
agent's turn generator dispatches ``Agent._run_meta_launch(name)``.

The store is intentionally minimal:

* keyed by session id (the pipeline's ``session_key``);
* one-shot — :func:`pending_meta_launch_pop` consumes the entry atomically
  so a launch fires on exactly one turn;
* in-memory only (lost on gateway restart, which is fine: a restart drops
  any half-issued ``/meta`` command and the surface can re-issue it);
* no TTL — the marker is consumed on the very next turn.

The locking pattern mirrors the sticky-cache helpers in
``opensquilla.engine.steps.meta_resolution`` (``_sticky_get`` /
``_sticky_put`` / ``_sticky_drop``).
"""

from __future__ import annotations

import threading

from opensquilla.engine.pipeline import TurnContext

# Module-level, process-wide pending-launch store. Guarded by ``_pending_lock``
# so concurrent turns/RPCs on different sessions never tear the dict.
_pending_lock = threading.Lock()
_pending_meta_launch: dict[str, str] = {}


def pending_meta_launch_put(session_id: str, name: str) -> None:
    """Stamp a pending meta-skill launch for ``session_id``.

    No-op when either argument is empty. A later launch for the same
    session overwrites any earlier (unconsumed) one — the most recent
    ``/meta`` command wins.
    """
    if not session_id or not name:
        return
    with _pending_lock:
        _pending_meta_launch[session_id] = name


def pending_meta_launch_pop(session_id: str) -> str | None:
    """Atomically consume and return the pending launch for ``session_id``.

    Returns the stamped meta-skill name and removes the entry, so a second
    call (with no intervening :func:`pending_meta_launch_put`) returns
    ``None``. Returns ``None`` for an empty session id or no pending entry.
    """
    if not session_id:
        return None
    with _pending_lock:
        return _pending_meta_launch.pop(session_id, None)


async def meta_command_launch(ctx: TurnContext) -> TurnContext:
    """Seed ``meta_launch`` from a pending ``/meta`` command, if any.

    Always-on (NOT gated on ``auto_trigger``): the whole point of the
    ``/meta`` command is to launch a meta-skill in manual-only mode. The
    step is a cheap no-op when there is no pending launch for the session.
    """
    session_id = getattr(ctx, "session_key", "") or ""
    name = pending_meta_launch_pop(session_id)
    if name:
        ctx.metadata["meta_launch"] = {"name": name}
    return ctx
