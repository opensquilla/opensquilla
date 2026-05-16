"""Ports for channel ingress dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ChannelInFlightSetPort(Protocol):
    """Shutdown-facing surface for per-channel reply delivery tracking."""

    async def cancel_all(self) -> None:
        """Cancel and await any in-flight reply deliveries."""
        ...


class ChannelIngressPort(Protocol):
    """Adapter boundary for dispatching channel messages into the runtime."""

    def create_in_flight_set(self, config: Any) -> ChannelInFlightSetPort:
        """Create a per-channel in-flight reply tracker for ``config``."""
        ...

    async def run_dispatch(
        self,
        *,
        channel: Any,
        turn_runner: Any,
        session_manager: Any,
        session_key_builder: Callable[[Any], str],
        session_prefix: str,
        event_bridge: Any = None,
        config: Any = None,
        task_runtime: Any = None,
        rpc_dispatcher: Any = None,
        channel_rpc_context_factory: Callable[[Any], Any] | None = None,
        debounce_coordinator: Any = None,
        debounce_window_s: float = 0.0,
        in_flight: ChannelInFlightSetPort | None = None,
    ) -> None:
        """Run one channel receive/dispatch/respond loop."""
        ...
