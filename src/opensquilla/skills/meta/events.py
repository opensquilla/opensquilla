"""Internal event types used between the meta-orchestrator scheduler and its
step executors.

Only :class:`_StepDone` lives here for now — it terminates a step's
streaming sub-iterator and carries the step's final string output back
through the same channel as forwarded ``AgentEvent``\\s, so executors do
not need a side-channel (mutable holder / instance variable) to return
text. The scheduler strips ``_StepDone`` before forwarding the outer
stream to callers; consumers never see it.
"""

from __future__ import annotations

from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class _StepDone:
    """Internal sentinel — terminates a step's streaming sub-iterator.

    Not a public event type; the orchestrator strips these before forwarding
    the outer stream to callers. Carrying the text inline avoids needing a
    side-channel (mutable holder / instance variable) to communicate the
    step's final string output back to ``iter_events``.
    """

    text: str


__all__ = ["_StepDone"]
