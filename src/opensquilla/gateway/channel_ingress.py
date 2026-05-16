"""Gateway adapter for channel ingress dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opensquilla.channels.ingress import ChannelInFlightSetPort
from opensquilla.gateway.channel_dispatch import (
    _ChannelInFlightSet,
    _compute_channel_cap,
    run_channel_dispatch,
)


class GatewayChannelIngress:
    """Bridge channel lifecycle management to the gateway dispatch runtime."""

    def create_in_flight_set(self, config: Any) -> ChannelInFlightSetPort:
        return _ChannelInFlightSet(_compute_channel_cap(config))

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
        await run_channel_dispatch(
            channel=channel,
            turn_runner=turn_runner,
            session_manager=session_manager,
            session_key_builder=session_key_builder,
            session_prefix=session_prefix,
            event_bridge=event_bridge,
            config=config,
            task_runtime=task_runtime,
            rpc_dispatcher=rpc_dispatcher,
            channel_rpc_context_factory=channel_rpc_context_factory,
            debounce_coordinator=debounce_coordinator,
            debounce_window_s=debounce_window_s,
            _in_flight=in_flight,  # type: ignore[arg-type]
        )
