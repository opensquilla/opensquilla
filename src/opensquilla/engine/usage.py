"""Per-session token usage tracking and cost estimation."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from .pricing import lookup_price

_current_usage_scope: ContextVar[str | None] = ContextVar(
    "opensquilla_usage_scope",
    default=None,
)


@contextmanager
def usage_scope(scope_key: str | None) -> Iterator[None]:
    """Attribute UsageTracker.add calls in this async context to scope_key."""
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

    def add(
        self,
        input_tokens: int,
        output_tokens: int,
        model_id: str = "",
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        """Accumulate token counts, tracking per-model breakdown."""
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
                        "costUsd": round(self.cost, 6),
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
                "costUsd": round(mu.cost, 6),
            }
            for mu in sorted(self._per_model.values(), key=lambda m: m.cost, reverse=True)
        ]


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
    ) -> None:
        """Record token usage for a session."""
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
            )
            if model_id:
                scoped.model_id = model_id

    def get(self, session_key: str) -> SessionUsage | None:
        """Return accumulated usage for a session, or None."""
        return self._sessions.get(session_key)

    def get_scope(self, session_key: str, scope_key: str) -> SessionUsage | None:
        """Return accumulated usage for a session within one attribution scope."""
        return self._scopes.get((session_key, scope_key))

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
