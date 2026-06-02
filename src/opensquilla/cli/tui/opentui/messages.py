"""Typed JSON-line messages exchanged with the OpenTUI footer host."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any


class HostToPythonMessageError(ValueError):
    """Raised when the OpenTUI host emits an invalid control message."""


@dataclass(frozen=True)
class RouterPluginState:
    model: str
    route: str
    saving: str
    context: str
    style: str = "normal"
    baseline_model: str = ""
    source: str = ""
    routing_applied: bool = True
    rollout_phase: str = "full"


@dataclass(frozen=True)
class TurnBegin:
    id: str


@dataclass(frozen=True)
class TurnEnd:
    id: str
    cancelled: bool = False


@dataclass(frozen=True)
class PromptEcho:
    text: str


@dataclass(frozen=True)
class ModelText:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    summary: str = ""
    status: str = "running"
    id: str | None = None


@dataclass(frozen=True)
class ToolDetail:
    text: str
    tool_id: str | None = None


@dataclass(frozen=True)
class BlockBegin:
    id: str
    kind: str
    meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class BlockAppend:
    id: str
    delta: str


@dataclass(frozen=True)
class BlockUpdate:
    id: str
    patch: dict[str, Any]


@dataclass(frozen=True)
class BlockEnd:
    id: str


@dataclass(frozen=True)
class Usage:
    text: str


@dataclass(frozen=True)
class ComposerState:
    placeholder: str = "send a message"
    text: str = ""
    disabled: bool = False


@dataclass(frozen=True)
class CompletionCandidate:
    label: str
    description: str
    insert_text: str
    category: str


@dataclass(frozen=True)
class CompletionContext:
    catalog: tuple[CompletionCandidate, ...] = ()
    files: tuple[str, ...] = ()
    filters_sensitive_paths: bool = True


@dataclass(frozen=True)
class TurnStatusState:
    phase: str
    label: str
    active: bool
    style: str = "normal"


@dataclass(frozen=True)
class ScrollbackWrite:
    text: str


@dataclass(frozen=True)
class HostReady:
    pass


@dataclass(frozen=True)
class HostInputSubmit:
    text: str


@dataclass(frozen=True)
class HostInputCancel:
    pass


@dataclass(frozen=True)
class HostInputEof:
    pass


@dataclass(frozen=True)
class HostResize:
    width: int
    height: int


@dataclass(frozen=True)
class HostCompletionRequest:
    kind: str
    query: str
    request_id: int


@dataclass(frozen=True)
class HostError:
    message: str
    detail: str | None = None


type HostToPythonMessage = (
    HostReady
    | HostInputSubmit
    | HostInputCancel
    | HostInputEof
    | HostResize
    | HostCompletionRequest
    | HostError
)


def python_message_to_json(message_type: str, payload: object | None = None) -> str:
    """Serialize a Python-to-host message as one newline-terminated JSON object."""

    message: dict[str, Any] = {"type": message_type}
    if payload is not None:
        message.update(_payload_dict(payload))
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"


def host_message_from_json(raw: str) -> HostToPythonMessage:
    """Parse one JSON object emitted by the OpenTUI host."""

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HostToPythonMessageError(f"Invalid OpenTUI host JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise HostToPythonMessageError("OpenTUI host message must be a JSON object")

    message_type = payload.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise HostToPythonMessageError("OpenTUI host message requires string field 'type'")

    if message_type == "ready":
        return HostReady()
    if message_type == "input.submit":
        return HostInputSubmit(text=_required_str(payload, "input.submit.text", "text"))
    if message_type == "input.cancel":
        return HostInputCancel()
    if message_type == "input.eof":
        return HostInputEof()
    if message_type == "resize":
        return HostResize(
            width=_required_int(payload, "resize.width", "width"),
            height=_required_int(payload, "resize.height", "height"),
        )
    if message_type == "completion.request":
        return HostCompletionRequest(
            kind=_required_str(payload, "completion.kind", "kind"),
            query=_required_str(payload, "completion.query", "query"),
            request_id=_required_int(payload, "completion.request_id", "request_id"),
        )
    if message_type == "error":
        return HostError(
            message=_required_str(payload, "error.message", "message"),
            detail=_optional_str(payload, "detail"),
        )

    raise HostToPythonMessageError(f"Unknown OpenTUI host message type: {message_type}")


def _payload_dict(payload: object) -> dict[str, Any]:
    if is_dataclass(payload) and not isinstance(payload, type):
        return asdict(payload)
    if isinstance(payload, dict):
        return dict(payload)
    raise TypeError(
        "OpenTUI Python message payload must be a dataclass instance or mapping"
    )


def _required_str(payload: dict[str, Any], label: str, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise HostToPythonMessageError(f"OpenTUI host message requires {label}")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HostToPythonMessageError(f"OpenTUI host message field {key} must be text")
    return value


def _required_int(payload: dict[str, Any], label: str, key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise HostToPythonMessageError(f"OpenTUI host message requires {label}")
    return value
