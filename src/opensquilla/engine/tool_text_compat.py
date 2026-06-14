"""Helpers for model text that encodes tool calls."""

from __future__ import annotations

import json
import re
from typing import Any

_PLAIN_JSON_TOOL_CALL_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s*(\{.*\})\s*$",
    re.DOTALL,
)
_PLAIN_JSON_TOOL_PREFIX_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.:-]*)\s*(?=\{)",
)
_FUNCTION_STYLE_TOOL_PREFIX_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s*\(\s*",
)
_WRAPPED_TOOL_CALL_RE = re.compile(
    r"^\s*<\s*tool_call\s*>\s*(\{.*\})\s*</\s*tool_call\s*>\s*(?:<\|role_end\|>)?\s*$",
    re.DOTALL | re.IGNORECASE,
)
_WRAPPED_TOOL_CALL_MARKER_RE = re.compile(r"<\s*tool_call\s*>", re.IGNORECASE)
_TEXT_PROTOCOL_MARKER_RE = re.compile(
    (
        r"<\s*(?:minimax:tool_call|tool_calls?|tvoe_calls|invoke\b|"
        r"parameter\b|effect_calls\b|details\b|angle\s+brackets\b|"
        r"[|｜]\s*DSML\s*[|｜]\s*(?:tool_calls?|invoke\b|parameter\b))|"
        r"<\|role_end\|>"
    ),
    re.IGNORECASE,
)
_ROLE_END_SENTINEL_RE = re.compile(r"<\|role_end\|>", re.IGNORECASE)
_TEXT_PROTOCOL_PARAMETER_RE = re.compile(
    (
        r"<\s*(?:parameter|[|｜]\s*DSML\s*[|｜]\s*parameter)\s+"
        r"name\s*=\s*[\"'](?:path|content|command|code|patch|sheets)[\"']"
    ),
    re.IGNORECASE,
)
_TEXT_PROTOCOL_INVOKE_RE = re.compile(
    (
        r"<\s*(?:invoke|[|｜]\s*DSML\s*[|｜]\s*invoke)\s+"
        r"name\s*=\s*[\"'][A-Za-z_][A-Za-z0-9_.:-]*[\"']"
    ),
    re.IGNORECASE,
)
_TEXT_PROTOCOL_HTML_RE = re.compile(
    r"<!doctype\s+html\b|<html\b|</html\s*>",
    re.IGNORECASE,
)
_TEXT_PROTOCOL_CLOSE_RE = re.compile(
    (
        r"</\s*(?:invoke|[|｜]\s*DSML\s*[|｜]\s*invoke)\s*>|"
        r"</\s*(?:tool_calls?|tvoe_calls|[|｜]\s*DSML\s*[|｜]\s*tool_calls?)\s*>"
    ),
    re.IGNORECASE,
)
_TEXT_PROTOCOL_STANDALONE_MARKER_RE = re.compile(
    (
        r"<\s*(?:parameter|effect_calls|tool_calls?|tvoe_calls|angle\s+brackets|"
        r"[|｜]\s*DSML\s*[|｜]\s*(?:tool_calls?|invoke|parameter))\b"
    ),
    re.IGNORECASE,
)
_TEXT_PROTOCOL_DETAILS_SUMMARY_RE = re.compile(
    r"<\s*details\s*>\s*<\s*summary\s*>\s*View areas around line\b",
    re.IGNORECASE,
)
_TEXT_PROTOCOL_PREFIXES = (
    "<minimax:tool_call",
    "<tool_call",
    "<tool_calls",
    "<tvoe_calls",
    "<|dsml|tool_call",
    "<|dsml|tool_calls",
    "<|dsml|invoke",
    "<|dsml|parameter",
    "<｜dsml｜tool_call",
    "<｜dsml｜tool_calls",
    "<｜dsml｜invoke",
    "<｜dsml｜parameter",
    "<invoke",
    "<parameter",
    "<effect_calls",
    "<details",
    "<summary",
    "<angle brackets",
    "<|role_end|>",
)
_MAX_TEXT_PROTOCOL_PREFIX_LEN = max(len(prefix) for prefix in _TEXT_PROTOCOL_PREFIXES)


def _parse_function_style_tool_call_line(line: str) -> tuple[str, dict[str, Any]] | None:
    match = _FUNCTION_STYLE_TOOL_PREFIX_RE.match(line)
    if match is None:
        return None
    try:
        arguments, end = json.JSONDecoder().raw_decode(line, match.end())
    except json.JSONDecodeError:
        return None
    if not isinstance(arguments, dict):
        return None
    suffix = line[end:].strip()
    if suffix not in {"", ")", ");"}:
        return None
    return match.group(1), arguments


def parse_function_style_tool_call_lines(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse standalone ``tool_name({...})`` text-protocol lines."""

    calls: list[tuple[str, dict[str, Any]]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        call = _parse_function_style_tool_call_line(line)
        if call is not None:
            calls.append(call)
    return calls


def _find_function_style_tool_call_suffix_start(text: str, tool_name: str) -> int | None:
    lines = text.splitlines(keepends=True)
    offset = 0
    for index, line in enumerate(lines):
        call = _parse_function_style_tool_call_line(line)
        if call is None or call[0] != tool_name:
            offset += len(line)
            continue
        suffix_is_calls = True
        for suffix_line in lines[index:]:
            if not suffix_line.strip():
                continue
            if _parse_function_style_tool_call_line(suffix_line) is None:
                suffix_is_calls = False
                break
        if suffix_is_calls:
            return offset + (len(line) - len(line.lstrip()))
        offset += len(line)
    return None


def parse_wrapped_tool_call_text(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a complete ``<tool_call>{...}</tool_call>`` text payload."""

    match = _WRAPPED_TOOL_CALL_RE.match(text)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("name")
    arguments = payload.get("arguments", {})
    if not isinstance(tool_name, str) or not tool_name:
        return None
    if not isinstance(arguments, dict):
        return None
    return tool_name, arguments


def _parse_exact_plain_json_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a bare ``tool_name{...}`` assistant text response."""
    candidates = [text]
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if non_empty_lines:
        last_line = non_empty_lines[-1]
        if last_line != text:
            candidates.append(last_line)

    match = None
    for candidate in candidates:
        match = _PLAIN_JSON_TOOL_CALL_RE.match(candidate)
        if match:
            break
    if match is None:
        return None

    try:
        arguments = json.loads(match.group(2))
    except json.JSONDecodeError:
        return None
    if not isinstance(arguments, dict):
        return None
    return match.group(1), arguments


def _parse_trailing_plain_json_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a trailing ``tool_name{...}``, allowing prose before it."""
    decoder = json.JSONDecoder()
    for match in reversed(list(_PLAIN_JSON_TOOL_PREFIX_RE.finditer(text))):
        try:
            arguments, end = decoder.raw_decode(text, match.end())
        except json.JSONDecodeError:
            continue
        if text[end:].strip():
            continue
        if not isinstance(arguments, dict):
            continue
        return match.group(1), arguments
    return None


def parse_plain_json_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a text response ending in ``tool_name{...}``."""
    exact_call = _parse_exact_plain_json_tool_call(text)
    if exact_call is not None:
        return exact_call
    return _parse_trailing_plain_json_tool_call(text)


def _find_trailing_tool_call_start(text: str, tool_name: str) -> int | None:
    decoder = json.JSONDecoder()
    for match in reversed(list(_PLAIN_JSON_TOOL_PREFIX_RE.finditer(text))):
        if match.group(1) != tool_name:
            continue
        try:
            arguments, end = decoder.raw_decode(text, match.end())
        except json.JSONDecodeError:
            continue
        if text[end:].strip():
            continue
        if not isinstance(arguments, dict):
            continue
        return match.start()
    return None


def strip_synthetic_tool_call_text(text: str, tool_name: str) -> str:
    """Remove trailing machine-readable tool-call text synthesized into a tool call."""

    if not text:
        return text

    wrapped_marker = _WRAPPED_TOOL_CALL_MARKER_RE.search(text)
    if wrapped_marker is not None:
        candidate = text[wrapped_marker.start() :]
        wrapped_call = parse_wrapped_tool_call_text(candidate)
        if wrapped_call is not None and wrapped_call[0] == tool_name:
            return text[: wrapped_marker.start()].rstrip()

    if "<minimax:tool_call>" in text:
        return ""

    function_style_start = _find_function_style_tool_call_suffix_start(text, tool_name)
    if function_style_start is not None:
        return text[:function_style_start].rstrip()

    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            candidate = lines[index]
            break
    else:
        return text

    match = _PLAIN_JSON_TOOL_CALL_RE.match(candidate)
    if match is None or match.group(1) != tool_name:
        start = _find_trailing_tool_call_start(text, tool_name)
        if start is None:
            return text
        return text[:start].rstrip()

    prefix = "\n".join(lines[:index]).rstrip()
    return prefix


def _looks_like_text_tool_protocol_suffix(suffix: str) -> bool:
    if _ROLE_END_SENTINEL_RE.fullmatch(suffix.strip()):
        return True
    if re.search(r"<\s*minimax:tool_call\s*>", suffix, re.IGNORECASE):
        return True
    if _TEXT_PROTOCOL_STANDALONE_MARKER_RE.search(suffix):
        return True
    if _TEXT_PROTOCOL_DETAILS_SUMMARY_RE.search(suffix):
        return True
    if _TEXT_PROTOCOL_PARAMETER_RE.search(suffix):
        return True
    if _TEXT_PROTOCOL_INVOKE_RE.search(suffix) and _TEXT_PROTOCOL_CLOSE_RE.search(suffix):
        return True
    if _TEXT_PROTOCOL_HTML_RE.search(suffix) and _TEXT_PROTOCOL_INVOKE_RE.search(suffix):
        return True
    return False


def strip_protocol_text_leak(text: str) -> str:
    """Remove text-encoded tool protocol that should not be user-visible."""

    if not text:
        return text

    for marker in _TEXT_PROTOCOL_MARKER_RE.finditer(text):
        suffix = text[marker.start() :]
        if _looks_like_text_tool_protocol_suffix(suffix):
            return text[: marker.start()].rstrip()
    return text


def _find_protocol_marker_start(text: str) -> int | None:
    marker = _TEXT_PROTOCOL_MARKER_RE.search(text)
    return marker.start() if marker is not None else None


def _find_protocol_prefix_suffix_start(text: str) -> int | None:
    lower_text = text.lower()
    start = max(0, len(text) - _MAX_TEXT_PROTOCOL_PREFIX_LEN)
    for index in range(start, len(text)):
        suffix = lower_text[index:]
        if any(prefix.startswith(suffix) for prefix in _TEXT_PROTOCOL_PREFIXES):
            return index
    return None


def _split_visible_prefix_before_protocol_candidate(text: str) -> tuple[str, str]:
    marker_start = _find_protocol_marker_start(text)
    if marker_start is None:
        marker_start = _find_protocol_prefix_suffix_start(text)
    if marker_start is None:
        return text, ""

    prefix = text[:marker_start]
    visible_prefix = prefix.rstrip()
    return visible_prefix, text[len(visible_prefix) :]


class ProtocolTextLeakGuard:
    """Stateful guard for streamed text that may contain tool protocol."""

    def __init__(self) -> None:
        self._pending = ""
        self._suppressed = False

    def push(self, text: str) -> str:
        if not text or self._suppressed:
            return ""

        combined = self._pending + text
        self._pending = ""
        cleaned = strip_protocol_text_leak(combined)
        if cleaned != combined:
            self._suppressed = True
            return cleaned

        visible, pending = _split_visible_prefix_before_protocol_candidate(combined)
        self._pending = pending
        return visible

    def flush(self) -> str:
        if self._suppressed:
            self._pending = ""
            self._suppressed = False
            return ""
        pending = self._pending
        self._pending = ""
        return strip_protocol_text_leak(pending)

    def flush_before_tool_use(self) -> str:
        if self._suppressed:
            self._pending = ""
            self._suppressed = False
            return ""
        return self.flush()


def strip_synthetic_tool_call_suffix(text: str, tool_names: list[str]) -> str:
    """Remove text-encoded tool calls for any of the supplied synthetic tools."""

    cleaned = text
    for tool_name in tool_names:
        cleaned = strip_synthetic_tool_call_text(cleaned, tool_name)
    return cleaned
