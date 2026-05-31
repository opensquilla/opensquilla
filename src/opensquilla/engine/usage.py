"""Per-session token usage tracking and cost estimation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .pricing import lookup_price

_current_usage_scope: ContextVar[str | None] = ContextVar(
    "opensquilla_usage_scope",
    default=None,
)


@contextmanager
def usage_scope(scope_key: str | None) -> Iterator[None]:
    """Attribute UsageTracker.add calls in this context to scope_key."""
    if not scope_key:
        yield
        return
    token = _current_usage_scope.set(scope_key)
    try:
        yield
    finally:
        _current_usage_scope.reset(token)


@dataclass
class ModelUsage:
    """Token usage for a single model within a session."""

    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Provider-billed cost accumulated across every raw provider call attributed
    # to this model. New field appended at the end so existing positional
    # callers (ModelUsage(model_id, in, out)) continue to align. When > 0 the
    # model_breakdown serializer prefers this over the pricing-table estimate,
    # avoiding cache-discount drift in the per-model split.
    billed_cost: float = 0.0

    @property
    def cost(self) -> float:
        price = lookup_price(self.model_id)
        return (
            self.input_tokens * price.input_per_m + self.output_tokens * price.output_per_m
        ) / 1_000_000


@dataclass
class SessionUsage:
    """Accumulated token usage and cost for a single session."""

    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""
    _per_model: dict[str, ModelUsage] | None = None
    # New cache counters appended at the end so existing positional callers
    # (e.g. SessionUsage(1, 2, "model")) keep aligning with `model_id`.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def cost(self) -> float:
        """Calculate cost in USD based on pricing table."""
        if self._per_model:
            return sum(m.cost for m in self._per_model.values())
        price = lookup_price(self.model_id)
        input_cost = self.input_tokens * price.input_per_m
        output_cost = self.output_tokens * price.output_per_m
        return (input_cost + output_cost) / 1_000_000

    @property
    def billed_cost(self) -> float:
        """Sum of provider-billed cost across every model in this session.

        Returns 0.0 when no per-model billed data has been captured (e.g.
        provider returned no cost, or session is estimate-only). Callers
        use this to decide whether the session-level row should display
        the actual billed total or fall back to the pricing-table estimate.
        """
        if not self._per_model:
            return 0.0
        return sum(float(getattr(m, "billed_cost", 0.0) or 0.0) for m in self._per_model.values())

    @property
    def total_cost(self) -> float:
        """Best per-session cost: real billed where available, estimate elsewhere.

        Mixed-source sessions need this so the row total doesn't under-report
        the unbilled portion. For each model: prefer ``mu.billed_cost`` when
        > 0, otherwise contribute the pricing-table estimate ``mu.cost``.
        Sum equals the breakdown's per-model ``costUsd`` sum by construction
        (since the breakdown serializer makes the same per-model decision).
        """
        if not self._per_model:
            return self.cost
        return sum(
            (float(getattr(m, "billed_cost", 0.0) or 0.0) or m.cost)
            for m in self._per_model.values()
        )

    @property
    def cost_source(self) -> str:
        """Aggregate cost source for the session row.

        - ``provider_billed``: every per-model entry has a real billed total.
        - ``mixed``: some models billed, others estimate-only.
        - ``opensquilla_estimate``: no billed data at all, or provider returned
          no cost for any call.
        """
        if not self._per_model:
            return "opensquilla_estimate"
        billed_count = sum(
            1
            for m in self._per_model.values()
            if float(getattr(m, "billed_cost", 0.0) or 0.0) > 0
        )
        if billed_count == 0:
            return "opensquilla_estimate"
        if billed_count == len(self._per_model):
            return "provider_billed"
        return "mixed"

    def add(
        self,
        input_tokens: int,
        output_tokens: int,
        model_id: str = "",
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        billed_cost: float = 0.0,
    ) -> None:
        """Accumulate token counts, tracking per-model breakdown.

        ``billed_cost`` is the provider-reported real billed cost for this
        accumulation (typically one provider call). Forwarded into the per-model
        ``ModelUsage`` so the breakdown serializer can return the actual billed
        figure instead of the cache-blind pricing-table estimate.
        """
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.cache_write_tokens += cache_write_tokens
        mid = model_id or self.model_id
        if mid:
            if self._per_model is None:
                self._per_model = {}
            mu = self._per_model.get(mid)
            if mu is None:
                mu = ModelUsage(model_id=mid)
                self._per_model[mid] = mu
            mu.input_tokens += input_tokens
            mu.output_tokens += output_tokens
            mu.cache_read_tokens += cache_read_tokens
            mu.cache_write_tokens += cache_write_tokens
            mu.billed_cost += billed_cost

    @staticmethod
    def _breakdown_cost_fields(mu_or_self: ModelUsage | SessionUsage) -> dict:
        """Pick the canonical cost + source for a single breakdown row.

        Prefer the real provider-billed cost when present; otherwise fall back
        to the local pricing-table estimate. This is what lets the WebUI show
        per-model values that actually sum to the row total without prorating.
        """
        billed = float(getattr(mu_or_self, "billed_cost", 0.0) or 0.0)
        estimate = float(mu_or_self.cost or 0.0)
        if billed > 0:
            return {
                "costUsd": round(billed, 6),
                "billedCostUsd": round(billed, 6),
                "estimatedCostUsd": round(estimate, 6),
                "costSource": "provider_billed",
            }
        return {
            "costUsd": round(estimate, 6),
            "billedCostUsd": 0.0,
            "estimatedCostUsd": round(estimate, 6),
            "costSource": "opensquilla_estimate" if estimate > 0 else "unavailable",
        }

    @property
    def model_breakdown(self) -> list[dict]:
        """Per-model usage breakdown for RPC serialisation."""
        if not self._per_model:
            if self.model_id:
                return [
                    {
                        "model": self.model_id,
                        "inputTokens": self.input_tokens,
                        "outputTokens": self.output_tokens,
                        "cacheReadTokens": self.cache_read_tokens,
                        "cacheWriteTokens": self.cache_write_tokens,
                        **SessionUsage._breakdown_cost_fields(self),
                    }
                ]
            return []
        return [
            {
                "model": mu.model_id,
                "inputTokens": mu.input_tokens,
                "outputTokens": mu.output_tokens,
                "cacheReadTokens": mu.cache_read_tokens,
                "cacheWriteTokens": mu.cache_write_tokens,
                **SessionUsage._breakdown_cost_fields(mu),
            }
            # Sort by the canonical cost (billed when present, estimate otherwise)
            # so the row order stays predictable even when some models lack
            # billed data.
            for mu in sorted(
                self._per_model.values(),
                key=lambda m: float(getattr(m, "billed_cost", 0.0) or 0.0) or m.cost,
                reverse=True,
            )
        ]


def _clone_session_usage(usage: SessionUsage) -> SessionUsage:
    clone = SessionUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model_id=usage.model_id,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
    )
    if usage._per_model:
        clone._per_model = {
            mid: ModelUsage(
                model_id=mu.model_id,
                input_tokens=mu.input_tokens,
                output_tokens=mu.output_tokens,
                cache_read_tokens=mu.cache_read_tokens,
                cache_write_tokens=mu.cache_write_tokens,
                billed_cost=mu.billed_cost,
            )
            for mid, mu in usage._per_model.items()
        }
    return clone


def _model_delta_cost(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    billed_cost: float,
) -> float:
    if billed_cost > 0.0:
        return billed_cost
    price = lookup_price(model_id)
    return (input_tokens * price.input_per_m + output_tokens * price.output_per_m) / 1_000_000


@dataclass
class SessionTotalsSnapshot:
    """Point-in-time aggregate of a session's token usage and cost.

    Embedded in `DoneEvent` so consumers do not need a follow-up
    `usage.status` RPC to render session totals. `None` on `DoneEvent`
    means "no snapshot available" (legacy replay), distinct from a
    populated snapshot whose numeric fields happen to be zero.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    billed_cost: float = 0.0

    @classmethod
    def from_session(cls, usage: SessionUsage) -> SessionTotalsSnapshot:
        return cls(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=usage.total_cost,
            billed_cost=usage.billed_cost,
        )


class UsageTracker:
    """Tracks per-session token usage and cost."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionUsage] = {}
        self._scopes: dict[tuple[str, str], SessionUsage] = {}

    def add(
        self,
        session_key: str,
        input_tokens: int,
        output_tokens: int,
        model_id: str = "",
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        billed_cost: float = 0.0,
    ) -> None:
        """Record token usage for a session.

        ``billed_cost`` flows through to :py:attr:`ModelUsage.billed_cost` so
        the per-model breakdown can report real provider-billed figures
        instead of the cache-blind pricing-table estimate.
        """
        usage = self._sessions.get(session_key)
        if usage is None:
            usage = SessionUsage(model_id=model_id)
            self._sessions[session_key] = usage
        usage.add(
            input_tokens,
            output_tokens,
            model_id=model_id,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            billed_cost=billed_cost,
        )
        if model_id:
            usage.model_id = model_id
        scope_key = _current_usage_scope.get()
        if scope_key:
            scoped = self._scopes.get((session_key, scope_key))
            if scoped is None:
                scoped = SessionUsage(model_id=model_id)
                self._scopes[(session_key, scope_key)] = scoped
            scoped.add(
                input_tokens,
                output_tokens,
                model_id=model_id,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                billed_cost=billed_cost,
            )
            if model_id:
                scoped.model_id = model_id

    def get(self, session_key: str) -> SessionUsage | None:
        """Return accumulated usage for a session, or None."""
        return self._sessions.get(session_key)

    def session_checkpoint(self, session_key: str) -> SessionUsage | None:
        """Return an immutable-enough copy for later per-turn delta accounting."""
        usage = self._sessions.get(session_key)
        if usage is None:
            return None
        return _clone_session_usage(usage)

    def get_scope(self, session_key: str, scope_key: str) -> SessionUsage | None:
        """Return accumulated usage for a session within one attribution scope."""
        return self._scopes.get((session_key, scope_key))

    def session_snapshot(self, session_key: str) -> SessionTotalsSnapshot | None:
        """Return the current SessionTotalsSnapshot for *session_key*, or None if unknown."""
        usage = self._sessions.get(session_key)
        if usage is None:
            return None
        return SessionTotalsSnapshot.from_session(usage)

    def session_delta_snapshot(
        self,
        session_key: str,
        checkpoint: SessionUsage | None,
    ) -> SessionTotalsSnapshot | None:
        """Return usage added since *checkpoint*.

        Cost is computed from per-model deltas instead of subtracting two
        session totals, because a later provider-billed call can change a
        model's aggregate cost source from estimate to billed.
        """
        usage = self._sessions.get(session_key)
        if usage is None:
            return None
        input_tokens = usage.input_tokens - (checkpoint.input_tokens if checkpoint else 0)
        output_tokens = usage.output_tokens - (checkpoint.output_tokens if checkpoint else 0)
        cache_read_tokens = usage.cache_read_tokens - (
            checkpoint.cache_read_tokens if checkpoint else 0
        )
        cache_write_tokens = usage.cache_write_tokens - (
            checkpoint.cache_write_tokens if checkpoint else 0
        )
        billed_cost = usage.billed_cost - (checkpoint.billed_cost if checkpoint else 0.0)
        cost_usd = 0.0

        if usage._per_model:
            before_models = checkpoint._per_model if checkpoint and checkpoint._per_model else {}
            for mid, mu in usage._per_model.items():
                before = before_models.get(mid) if before_models else None
                delta_input = mu.input_tokens - (before.input_tokens if before else 0)
                delta_output = mu.output_tokens - (before.output_tokens if before else 0)
                delta_billed = mu.billed_cost - (before.billed_cost if before else 0.0)
                if delta_input or delta_output or delta_billed:
                    cost_usd += _model_delta_cost(
                        model_id=mid,
                        input_tokens=max(0, delta_input),
                        output_tokens=max(0, delta_output),
                        billed_cost=max(0.0, delta_billed),
                    )
        else:
            cost_usd = _model_delta_cost(
                model_id=usage.model_id,
                input_tokens=max(0, input_tokens),
                output_tokens=max(0, output_tokens),
                billed_cost=max(0.0, billed_cost),
            )

        return SessionTotalsSnapshot(
            input_tokens=max(0, input_tokens),
            output_tokens=max(0, output_tokens),
            cache_read_tokens=max(0, cache_read_tokens),
            cache_write_tokens=max(0, cache_write_tokens),
            cost_usd=max(0.0, cost_usd),
            billed_cost=max(0.0, billed_cost),
        )

    def get_cost(self, session_key: str) -> float:
        """Return accumulated cost in USD for a session."""
        usage = self._sessions.get(session_key)
        if usage is None:
            return 0.0
        return usage.cost

    def format_usage(self, session_key: str) -> str:
        """Human-readable usage summary for a session."""
        usage = self._sessions.get(session_key)
        if usage is None:
            return "Tokens: 0 in / 0 out | Cost: $0.00"
        return (
            f"Tokens: {usage.input_tokens:,} in / {usage.output_tokens:,} out "
            f"| Cost: ${usage.cost:,.4f}"
        )

    def total_cost(self) -> float:
        """Sum of costs across all sessions."""
        return sum(u.cost for u in self._sessions.values())

    def all_sessions(self) -> dict[str, SessionUsage]:
        """Return all tracked sessions."""
        return dict(self._sessions)

    def check_warning(self, session_key: str, threshold: float = 5.0) -> str | None:
        """Return a warning if session cost exceeds threshold, else None."""
        usage = self._sessions.get(session_key)
        if usage is None:
            return None
        if usage.cost >= threshold:
            return f"Session cost ${usage.cost:,.2f} has exceeded the ${threshold:,.2f} threshold."
        return None
