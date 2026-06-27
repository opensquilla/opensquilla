"""Shared, surface-agnostic approval-prompt contract for chat channels.

A channel-originated turn that hits an approval-gated tool (e.g. a warned
shell command) blocks on the approval queue. This module renders the prompt
that asks the originating user to approve or deny, and parses their reply,
without binding to any single adapter:

- :func:`render_approval_prompt` returns an interactive card payload when the
  adapter declares ``interactive_cards``, otherwise a plain-text prompt that
  works on every adapter via the universal ``/approve``/``/deny`` commands.
- :func:`parse_approval_action` recognises either a Feishu card action
  (``opensquilla_action == "approval_resolve"``) or the universal text
  command and returns ``(code, approved)``.

The user-facing handle is a SHORT base32 code (default 4 chars,
case-insensitive), never the raw approval/exec id. Raw ids leak in group
history and are hidden elsewhere in the product, so the code is the only
thing shown to a channel and the only thing a user types back. The
code→approval_id binding (and the originating ``sender_id`` for owner-only
resolution) lives server-side in :data:`_CODE_REGISTRY`.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any

# Crockford-style base32 alphabet minus easily-confused glyphs (I, L, O, U).
# 4 chars over a 28-symbol alphabet => 614 656 combinations, ample for the
# handful of approvals a single session has outstanding at once.
_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CODE_LENGTH = 4

# Universal text command. A leading slash avoids bare-word collisions with
# ordinary chat ("approve the budget" must not resolve anything).
_TEXT_COMMAND_RE = re.compile(
    r"^\s*/(approve|deny)\b\s*([0-9A-Za-z]{2,12})?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ApprovalPromptRequest:
    """Surface-agnostic description of one pending channel approval.

    ``short_code`` is the human handle bound to ``approval_id`` server-side;
    ``session_key`` and ``namespace`` mirror the queue entry so the bridge can
    route the prompt back to the originating channel.
    """

    approval_id: str
    namespace: str
    session_key: str
    command_or_tool: str
    agent: str
    short_code: str


@dataclass(frozen=True)
class _CodeBinding:
    approval_id: str
    namespace: str
    session_key: str
    owner_sender_id: str


# code (uppercased) -> binding. Process-local, mirroring the approval queue's
# single-process model. Pruned when the bound approval is resolved.
_CODE_REGISTRY: dict[str, _CodeBinding] = {}
# Reverse index so a re-notified request reuses its existing code rather than
# minting a second one for the same approval.
_APPROVAL_TO_CODE: dict[str, str] = {}


def _mint_code() -> str:
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        if code not in _CODE_REGISTRY:
            return code


def normalize_code(code: str) -> str:
    """Canonicalise a user-typed code for case-insensitive lookup."""
    return code.strip().upper()


def bind_short_code(
    approval_id: str,
    *,
    namespace: str,
    session_key: str,
    owner_sender_id: str,
) -> str:
    """Bind ``approval_id`` to a fresh short code (idempotent per approval).

    Returns the existing code when this approval was already bound so a
    re-``requested`` notification does not mint a duplicate handle.
    """
    existing = _APPROVAL_TO_CODE.get(approval_id)
    if existing is not None and existing in _CODE_REGISTRY:
        return existing
    code = _mint_code()
    _CODE_REGISTRY[code] = _CodeBinding(
        approval_id=approval_id,
        namespace=namespace,
        session_key=session_key,
        owner_sender_id=owner_sender_id,
    )
    _APPROVAL_TO_CODE[approval_id] = code
    return code


def resolve_short_code(code: str) -> _CodeBinding | None:
    """Look up a code's binding, or ``None`` for an unknown/expired code."""
    return _CODE_REGISTRY.get(normalize_code(code))


def release_short_code(approval_id: str) -> None:
    """Drop the binding for a resolved approval (best-effort, idempotent)."""
    code = _APPROVAL_TO_CODE.pop(approval_id, None)
    if code is not None:
        _CODE_REGISTRY.pop(code, None)


def reset_short_codes() -> None:
    """Clear all bindings (test helper)."""
    _CODE_REGISTRY.clear()
    _APPROVAL_TO_CODE.clear()


def _adapter_supports_interactive_cards(profile: Any) -> bool:
    return bool(getattr(profile, "interactive_cards", False))


def _prompt_text(request: ApprovalPromptRequest) -> str:
    command = request.command_or_tool or "(unknown command)"
    return (
        "Approval needed to run a privileged command.\n"
        f"Command: {command}\n"
        f"Code: {request.short_code}\n"
        f"Reply /approve {request.short_code} to allow, or "
        f"/deny {request.short_code} to refuse."
    )


def _interactive_card(request: ApprovalPromptRequest) -> dict[str, Any]:
    """Build a Feishu-style interactive card with Approve/Deny buttons.

    The action ``value`` carries the short code (not the raw approval id) plus
    the ``opensquilla_action`` discriminator that :func:`parse_approval_action`
    keys on, paralleling the existing clarify-card contract.
    """
    command = request.command_or_tool or "(unknown command)"
    approve_value = {
        "opensquilla_action": "approval_resolve",
        "code": request.short_code,
        "decision": "approve",
    }
    deny_value = {
        "opensquilla_action": "approval_resolve",
        "code": request.short_code,
        "decision": "deny",
    }
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Approval needed"},
            "template": "orange",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"Run a privileged command?\n**Command:** `{command}`\n"
                        f"**Code:** `{request.short_code}`"
                    ),
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Approve"},
                        "type": "primary",
                        "value": approve_value,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Deny"},
                        "type": "danger",
                        "value": deny_value,
                    },
                ],
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": (
                            f"Or reply /approve {request.short_code} "
                            f"or /deny {request.short_code}."
                        ),
                    }
                ],
            },
        ],
    }


def render_approval_prompt(
    profile: Any,
    request: ApprovalPromptRequest,
) -> dict[str, Any]:
    """Render the prompt for ``request`` against an adapter ``profile``.

    Returns a dict with ``text`` always present (the universal fallback that
    every adapter can deliver) and, when the adapter declares
    ``interactive_cards``, an additional ``card`` payload. ``profile`` is the
    adapter's :class:`ChannelCapabilityProfile` (or ``None``).
    """
    payload: dict[str, Any] = {"text": _prompt_text(request)}
    if _adapter_supports_interactive_cards(profile):
        payload["card"] = _interactive_card(request)
    return payload


def parse_approval_action(inbound: Any) -> tuple[str, bool] | None:
    """Recognise an approval action from inbound channel data.

    Accepts either:

    - a Feishu card action dict carrying
      ``value.opensquilla_action == "approval_resolve"`` (already-parsed
      ``IncomingMessage.metadata`` or a raw ``{"value": {...}}`` mapping), or
    - a plain-text body of the form ``/approve <code>`` / ``/deny <code>``.

    Returns ``(short_code, approved)`` or ``None`` when the input is not an
    approval action. A missing code yields ``None`` (treated as "no pending"
    by the caller) rather than a silent no-op.
    """
    card = _card_action(inbound)
    if card is not None:
        return card
    text = _inbound_text(inbound)
    if text is None:
        return None
    match = _TEXT_COMMAND_RE.match(text)
    if match is None:
        return None
    code = match.group(2)
    if not code:
        return None
    approved = match.group(1).lower() == "approve"
    return normalize_code(code), approved


def _card_action(inbound: Any) -> tuple[str, bool] | None:
    value = _card_action_value(inbound)
    if value is None:
        return None
    if value.get("opensquilla_action") != "approval_resolve":
        return None
    code = value.get("code")
    if not isinstance(code, str) or not code.strip():
        return None
    decision = str(value.get("decision") or "").lower()
    if decision not in {"approve", "deny"}:
        return None
    return normalize_code(code), decision == "approve"


def _card_action_value(inbound: Any) -> dict[str, Any] | None:
    if isinstance(inbound, dict):
        value = inbound.get("value")
        if isinstance(value, dict):
            return value
        action = inbound.get("action")
        if isinstance(action, dict):
            action_value = action.get("value")
            if isinstance(action_value, dict):
                return action_value
        meta = inbound.get("metadata")
        if isinstance(meta, dict):
            meta_action = meta.get("approval_action")
            if isinstance(meta_action, dict):
                return meta_action
        return None
    metadata = getattr(inbound, "metadata", None)
    if isinstance(metadata, dict):
        meta_action = metadata.get("approval_action")
        if isinstance(meta_action, dict):
            return meta_action
    return None


def _inbound_text(inbound: Any) -> str | None:
    if isinstance(inbound, str):
        return inbound
    if isinstance(inbound, dict):
        content = inbound.get("content")
        return content if isinstance(content, str) else None
    content = getattr(inbound, "content", None)
    return content if isinstance(content, str) else None
