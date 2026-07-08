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
    # Last turn's token traffic ("34.6k/548" = in/out), displayed as its own
    # "io" strip field so the ctx field can stay a pure context-pressure value.
    io: str = ""


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
class NoticeWrite:
    """One captured console line forwarded to the host as a styled notice.

    Carries the raw Rich-rendered text (still ANSI-styled); the host strips the
    control bytes and recolors the line from the active theme so command notices
    render inside the conversation instead of bleeding onto the terminal.
    """

    text: str


@dataclass(frozen=True)
class ApprovalDismiss:
    """Close the host approval overlay for a request Python stopped waiting on.

    Sent when a pending ``approval.request`` resolves without a user decision
    (timeout, turn cancellation) so the stale modal never lingers to swallow
    the user's next keypress.
    """

    id: str


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


@dataclass(frozen=True)
class HostProtocolUnknown:
    """Host reply for a Python message type its dispatcher does not know.

    Sent instead of an ``error`` frame so a version-skewed (usually stale)
    host degrades to one skipped frame instead of a session teardown.
    """

    message_type: str


@dataclass(frozen=True)
class HostApprovalResponse:
    """User decision for an ``approval.request`` overlay shown by the host."""

    id: str
    approved: bool
    choice: str | None = None


type HostToPythonMessage = (
    HostReady
    | HostInputSubmit
    | HostInputCancel
    | HostInputEof
    | HostResize
    | HostCompletionRequest
    | HostError
    | HostProtocolUnknown
    | HostApprovalResponse
)


# Wire inventories, one entry per message type in each direction. These are the
# single source of truth the conformance tests pin against the host's dispatcher
# and emitter source, so a new/renamed type or a dispatcher-less sender fails a
# unit test instead of surfacing as a live protocol error. Values are the
# canonical payload dataclass, or None where the payload is an ad-hoc mapping
# (or absent) at the call site.
PYTHON_TO_HOST_TYPES: dict[str, type | None] = {
    "turn.begin": TurnBegin,
    "turn.end": TurnEnd,
    "turn.status": TurnStatusState,
    "composer.set": ComposerState,
    "completion.context": CompletionContext,
    "completion.response": None,
    "router.update": RouterPluginState,
    "block.begin": BlockBegin,
    "block.append": BlockAppend,
    "block.update": BlockUpdate,
    "block.end": BlockEnd,
    "prompt.echo": PromptEcho,
    "model.text": ModelText,
    "scrollback.write": ScrollbackWrite,
    "notice.write": NoticeWrite,
    "theme.set": None,
    "theme.pick": None,
    "approval.request": None,
    "approval.dismiss": ApprovalDismiss,
    "shutdown": None,
}

HOST_TO_PYTHON_TYPES: dict[str, type] = {
    "ready": HostReady,
    "input.submit": HostInputSubmit,
    "input.cancel": HostInputCancel,
    "input.eof": HostInputEof,
    "resize": HostResize,
    "completion.request": HostCompletionRequest,
    "error": HostError,
    "protocol.unknown": HostProtocolUnknown,
    "approval.response": HostApprovalResponse,
}


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
    if message_type == "protocol.unknown":
        return HostProtocolUnknown(
            message_type=_required_str(payload, "protocol.unknown.messageType", "messageType"),
        )
    if message_type == "approval.response":
        return HostApprovalResponse(
            id=_required_str(payload, "approval.response.id", "id"),
            approved=_required_bool(payload, "approval.response.approved", "approved"),
            choice=_optional_str(payload, "choice"),
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


def _required_bool(payload: dict[str, Any], label: str, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise HostToPythonMessageError(f"OpenTUI host message requires {label}")
    return value
