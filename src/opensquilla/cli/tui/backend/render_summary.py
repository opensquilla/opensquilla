"""Backend-neutral summaries for compact tool rows."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-?]*[ -/]*[@-~]"
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|P[^\x1b]*\x1b\\"
    r"|[@-Z\\-_]"
    r")"
)
_C0_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_RESULT_DECORATION_ONLY_RE = re.compile(r"^[\s═─=\-]{3,}$")
_RESULT_DECORATION_BANNER_RE = re.compile(r"^[\s═─=\-]{2,}.+[\s═─=\-]{2,}$")


def summarize_args(name: str, args: dict | None) -> str:
    """Return a short human-readable summary of a tool call's key argument."""
    if not args:
        return ""
    if name in {"exec_command", "background_process"}:
        cmd = args.get("command") or args.get("cmd") or ""
        return clip_arg(str(cmd)) if cmd else ""
    if name == "execute_code":
        code = args.get("code") or args.get("source") or ""
        first_line = str(code).split("\n", 1)[0]
        return clip_arg(first_line) if first_line else ""
    if name in {"read_file", "write_file", "list_dir", "apply_patch"}:
        path = args.get("path") or args.get("file_path") or args.get("target") or ""
        return clip_arg(str(path), keep_end=True) if path else ""
    if name == "web_search":
        query = args.get("query") or ""
        return clip_arg(str(query)) if query else ""
    if name == "web_fetch":
        url = args.get("url") or args.get("uri") or ""
        return clip_arg(str(url)) if url else ""
    return ""


def clip_arg(value: str, *, limit: int = 90, keep_end: bool = False) -> str:
    """Clip a tool-call argument for the inline tool row."""
    if len(value) <= limit:
        return value
    if keep_end:
        return f"...{value[-(limit - 3):]}"
    return f"{value[: limit - 3]}..."


def summarize_result(result: Any | None, *, max_chars: int = 220) -> str:
    """Return a compact, terminal-safe tool result preview."""
    if result is None:
        return ""
    text = _stringify_result_for_summary(result)
    text = _sanitize_stream_text(text).strip()
    if not text:
        return ""
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not _is_result_decoration_line(line)
        and not _is_useless_result_line(line)
    ]
    if not lines:
        return ""
    preview = "\n".join(lines[:3])
    if len(preview) > max_chars:
        preview = f"{preview[: max_chars - 3].rstrip()}..."
    return preview


def _sanitize_stream_text(delta: str) -> str:
    return _C0_RE.sub("", _ANSI_RE.sub("", delta))


def _stringify_result_for_summary(result: Any) -> str:
    msg_text = _stringify_msg_event_payloads(result)
    if msg_text is not None:
        return msg_text
    return _stringify_result_value(result)


def _stringify_msg_event_payloads(result: Any) -> str | None:
    if isinstance(result, dict):
        payload = _msg_event_payload(result)
        if payload is None:
            return None
        return _stringify_result_value(payload)
    if not isinstance(result, list):
        return None

    parts: list[str] = []
    for item in result:
        payload = _msg_event_payload(item)
        if payload is None:
            continue
        rendered = _stringify_result_value(payload).strip()
        if rendered:
            parts.append(rendered)
    return "\n".join(parts) if parts else None


def _msg_event_payload(event: Any) -> Any | None:
    if not isinstance(event, dict) or event.get("type") != "msg" or "msg" not in event:
        return None
    return event["msg"]


def _stringify_result_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _is_result_decoration_line(line: str) -> bool:
    stripped = line.strip()
    return bool(
        _RESULT_DECORATION_ONLY_RE.fullmatch(stripped)
        or _RESULT_DECORATION_BANNER_RE.fullmatch(stripped)
    )


def _is_useless_result_line(line: str) -> bool:
    stripped = line.strip()
    if stripped == "exit_code=0":
        return True
    if len(stripped) <= 1:
        return True
    return all(unicodedata.category(char).startswith("P") for char in stripped)
