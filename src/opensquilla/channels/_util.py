"""Shared channel utilities: deduplication, rate limiting, retry logic.

Also hosts the ``ChannelAccessPolicy`` primitive that adapters declare to
describe their admit/deny semantics. Item-5 adapter adoptions wire the
``policy`` attribute through; future dispatch refactors will consume
``evaluate_policy`` directly.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Channel access policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelAccessPolicy:
    """Per-adapter admit/deny declaration consumed by ``evaluate_policy``.

    The fields capture every dimension currently exercised by gateway
    dispatch (DM allow, group allow, mention requirement, sender allowlist)
    plus the ``allowlist`` slot reserved for item-5b/c/d/e per-adapter
    adoption. ``allowlist`` empty means "no sender filtering"; populated
    means strict allow-only.
    """

    dm_allowed: bool = True
    group_allowed: bool = True
    mention_required_in_group: bool = True
    allowlist: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """Result of ``evaluate_policy`` — paired with a stable reason code."""

    admit: bool
    reason: Literal[
        "dm_admitted",
        "dm_denied",
        "group_admitted",
        "group_denied",
        "not_mentioned_in_group",
        "not_in_allowlist",
    ]


def evaluate_policy(
    policy: ChannelAccessPolicy,
    *,
    is_group: bool,
    mentioned: bool,
    sender_id: str = "",
) -> AccessDecision:
    """Evaluate a single inbound message against a channel's access policy.

    Pure function. Adapters provide the policy; dispatch provides the runtime
    inputs (``is_group``, ``mentioned``, ``sender_id``). ``ChannelAccessPolicy``
    instances must be tuned so this evaluator preserves each adapter's access
    baseline when that adapter adopts the shared evaluator.
    """
    if is_group:
        if not policy.group_allowed:
            return AccessDecision(admit=False, reason="group_denied")
        if policy.mention_required_in_group and not mentioned:
            return AccessDecision(admit=False, reason="not_mentioned_in_group")
        if policy.allowlist and sender_id not in policy.allowlist:
            return AccessDecision(admit=False, reason="not_in_allowlist")
        return AccessDecision(admit=True, reason="group_admitted")
    if not policy.dm_allowed:
        return AccessDecision(admit=False, reason="dm_denied")
    if policy.allowlist and sender_id not in policy.allowlist:
        return AccessDecision(admit=False, reason="not_in_allowlist")
    return AccessDecision(admit=True, reason="dm_admitted")


class EventDedupeCache:
    """Bounded set for deduplicating event IDs."""

    def __init__(self, max_size: int = 10_000) -> None:
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._max_size = max_size

    def check_and_add(self, event_id: str) -> bool:
        """Return True if the event_id is new (not a duplicate)."""
        if event_id in self._seen:
            self._seen.move_to_end(event_id)
            return False
        self._seen[event_id] = None
        if len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
        return True


@dataclass
class RateLimiter:
    """Async token-bucket rate limiter for HTTP API calls."""

    max_tokens: int = 30
    refill_rate: float = 30.0  # tokens per second
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.max_tokens)
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        """Wait until a token is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.refill_rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


# ---------------------------------------------------------------------------
# Streaming resilience helpers (item 4)
# ---------------------------------------------------------------------------
#
# Slack and discord stream chat output by posting an "open" message and then
# editing it with each accumulated chunk. The previous inline implementations
# raced when a fast producer fired two edits concurrently and crashed the
# whole consumer when a single edit raised mid-stream. The two helpers below
# add the minimum-radius safety net: an in-flight serializer with push-back
# semantics, and an adaptive strike counter that flips a circuit when the
# remote keeps returning 429.
#
# Feishu is a non-consumer of this module: ``feishu.send_streaming`` collects
# the entire stream and posts once at the end, so neither helper applies.
# Keeping Feishu outside this helper avoids importing streaming-throttle state
# into its post-once delivery path.


@dataclass
class StreamThrottle:
    """Serialize edit calls against an in-flight network round trip.

    Accumulates incoming chunks; ``maybe_flush`` sends the latest snapshot
    via ``post`` (first call) or ``edit`` (subsequent calls). The
    ``asyncio.Lock`` ensures a second flush cannot start while a first is
    awaiting the network. If a send raises, the accumulated text remains
    intact so the next ``maybe_flush`` retries with the same snapshot.
    """

    interval_s: float = 0.5
    _accumulated: str = field(default="", init=False)
    _last_flush: float = field(default=0.0, init=False)
    _opened: bool = field(default=False, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def add(self, text: str) -> None:
        self._accumulated += text

    @property
    def text(self) -> str:
        return self._accumulated

    @property
    def opened(self) -> bool:
        return self._opened

    async def maybe_flush(
        self,
        *,
        post: Callable[[str], Awaitable[Any]],
        edit: Callable[[str], Awaitable[Any]],
    ) -> Any | None:
        """Send the accumulated snapshot if the throttle window has elapsed."""
        if not self._accumulated:
            return None
        now = time.monotonic()
        if self._opened and now - self._last_flush < self.interval_s:
            return None
        async with self._lock:
            text = self._accumulated
            if not self._opened:
                result = await post(text)
                self._opened = True
            else:
                result = await edit(text)
            self._last_flush = time.monotonic()
            return result

    async def force_flush(
        self,
        *,
        post: Callable[[str], Awaitable[Any]],
        edit: Callable[[str], Awaitable[Any]],
    ) -> Any | None:
        """Final flush bypassing the throttle interval — call at end-of-stream."""
        if not self._accumulated:
            return None
        async with self._lock:
            text = self._accumulated
            if not self._opened:
                result = await post(text)
                self._opened = True
            else:
                result = await edit(text)
            self._last_flush = time.monotonic()
            return result


@dataclass
class FloodStrikeBackoff:
    """Sliding-window strike counter that flips a circuit after N 429s.

    Each ``record_429`` appends a strike timestamp; strikes older than
    ``decay_s`` are dropped before counting. Once ``cap`` consecutive
    strikes accumulate within the window, ``should_fallback`` returns True
    and one ``channel.flood_strike_backoff`` log entry is emitted. The
    fallback latch stays True until ``reset`` is called explicitly so the
    streaming consumer cannot oscillate in/out of fallback every chunk.
    """

    cap: int = 3
    decay_s: float = 30.0
    adapter: str = "unknown"
    _strikes: list[float] = field(default_factory=list, init=False)
    _fallback: bool = field(default=False, init=False)

    def record_429(self) -> None:
        now = time.monotonic()
        self._strikes = [t for t in self._strikes if now - t <= self.decay_s]
        self._strikes.append(now)
        if not self._fallback and len(self._strikes) >= self.cap:
            self._fallback = True
            log.warning(
                "channel.flood_strike_backoff",
                adapter=self.adapter,
                strikes=len(self._strikes),
                cap=self.cap,
                decay_s=self.decay_s,
            )

    def record_success(self) -> None:
        """Successful send drops accumulated strikes — does NOT clear fallback."""
        self._strikes.clear()

    def should_fallback(self) -> bool:
        return self._fallback

    def reset(self) -> None:
        """Operator/manual circuit reset."""
        self._strikes.clear()
        self._fallback = False


async def retry_request(
    func: Callable[..., Awaitable[httpx.Response]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> httpx.Response:
    """Retry an httpx request with exponential backoff on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await func(*args, **kwargs)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", base_delay * (2**attempt)))
                log.warning("rate_limited", retry_after=retry_after, attempt=attempt)
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code in {500, 502, 503, 504} and attempt < max_retries:
                delay = base_delay * (2**attempt) + random.random()
                log.warning("transient_error", status=resp.status_code, delay=delay)
                await asyncio.sleep(delay)
                continue
            return resp
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2**attempt) + random.random()
                await asyncio.sleep(delay)
                continue
            raise
    raise last_exc or RuntimeError("retry_request exhausted")


def split_text_for_channel(text: str, limit: int) -> list[str]:
    """Split ``text`` into chunks no longer than ``limit`` characters.

    Splitting prefers paragraph (blank-line) then line then word boundaries,
    hard-splitting only as a last resort for a single token longer than
    ``limit``. Used to keep outbound replies under a platform's per-message
    length cap (Telegram 4096, Discord 2000, ...) instead of letting the API
    reject the whole message. An empty ``text`` yields ``[""]`` so callers
    always make at least one send; a non-positive ``limit`` disables splitting.
    """
    if limit <= 0 or len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        # Include the chosen separator in the preceding chunk. Splitting via
        # ``str.split`` and reconstructing later loses blank lines/spaces when
        # a boundary itself triggers a flush.
        paragraph_at = remaining.rfind("\n\n", 0, limit)
        if paragraph_at >= 0:
            end = paragraph_at + 2
        else:
            line_at = remaining.rfind("\n", 0, limit)
            if line_at >= 0:
                end = line_at + 1
            else:
                word_at = remaining.rfind(" ", 0, limit)
                end = word_at + 1 if word_at >= 0 else limit
        chunks.append(remaining[:end])
        remaining = remaining[end:]
    chunks.append(remaining)
    return chunks
