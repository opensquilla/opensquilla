"""Compatibility facade for read-only gateway chat slash-command workflows."""

from __future__ import annotations

from opensquilla.cli.chat_gateway_models_workflows import (
    GatewayModelListClient as ModelListClient,
)
from opensquilla.cli.chat_gateway_models_workflows import (
    handle_gateway_models_command as handle_models_command,
)
from opensquilla.cli.chat_gateway_sessions_workflows import (
    GatewaySessionListClient as SessionListClient,
)
from opensquilla.cli.chat_gateway_sessions_workflows import (
    handle_gateway_sessions_command as handle_sessions_command,
)

__all__ = [
    "ModelListClient",
    "SessionListClient",
    "handle_models_command",
    "handle_sessions_command",
]
