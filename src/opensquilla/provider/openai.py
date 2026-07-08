"""OpenAIProvider — streams via OpenAI Chat Completions API using httpx."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast
from uuid import uuid4

import httpx
import structlog

from opensquilla.env import trust_env as _trust_env
from opensquilla.execution_status import compact_provider_status, derive_is_error
from opensquilla.secrets import clean_header_secret

from .compat_policy import OpenAICompatPolicy, compat_policy_for_kind
from .context_capabilities import supports_openrouter_explicit_prompt_cache
from .failures import retry_after_from_headers
from .minimax_compat import contains_minimax_protocol, parse_minimax_tool_calls
from .openrouter_attribution import openrouter_app_headers
from .protocol import ProviderConnectionConfig, ProviderMetadata
from .reasoning_dialects import (
    ReasoningDisableArgs,
    ReasoningEnableArgs,
    apply_reasoning_disable,
    apply_reasoning_enable,
)
from .request_proof import (
    ProviderRequestBudgetExceededError,
    prove_provider_payload_from_env,
)
from .stream_assembly import ReasoningAccumulator, ToolStreamAccumulator
from .trace_recorder import LLMTraceRecorder
from .types import (
    ChatConfig,
    DoneEvent,
    ErrorEvent,
    Message,
    ModelCapabilities,
    ModelInfo,
    ProviderHeartbeatEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolDefinition,
    ToolUseEndEvent,
    ToolUseStartEvent,
)

_OPENAI_API_BASE = "https://api.openai.com"
log = structlog.get_logger(__name__)
_PLAIN_JSON_TOOL_CALL_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_.:-]*)\s*(\{.*\})\s*$",
    re.DOTALL,
)
_PLAIN_JSON_TOOL_PREFIX_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.:-]*)\s*(?=\{)",
)
_QWEN_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(?P<body>[\s\S]*?)\s*</tool_call>",
    re.IGNORECASE,
)
_QWEN_XML_FUNC_RE = re.compile(
    r"<function=([^>]+)>(?P<body>[\s\S]*?)</function>",
    re.IGNORECASE,
)
_QWEN_XML_FUNC_LENIENT_RE = re.compile(
    r"<function=([^>]+)>(?P<body>[\s\S]*?)(?=<function=|</function>|\Z)",
    re.IGNORECASE,
)
_QWEN_XML_PARAM_RE = re.compile(
    r"<parameter=([^>]+)>(?P<body>[\s\S]*?)</parameter>",
    re.IGNORECASE,
)
_QWEN_XML_PARAM_LENIENT_RE = re.compile(
    r"<parameter=([^>]+)>(?P<body>[\s\S]*?)(?=<parameter=|</parameter>|<function=|</function>|\Z)",
    re.IGNORECASE,
)
_DASHSCOPE_PARAMETER_RE = re.compile(
    r"<parameter(?:\s[^>]*)?>(?P<body>[\s\S]*?)</parameter>",
    re.IGNORECASE,
)
_MARKDOWN_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(?P<body>[\s\S]*?)\s*```\s*$",
    re.IGNORECASE,
)

_OPENAI_TOOL_STATUS_OUTPUT_MAX_CHARS = 4000
_VERSIONED_BASE_URL_RE = re.compile(r"/v\d+$")
_EPHEMERAL_CACHE_CONTROL: dict[str, str] = {"type": "ephemeral"}
_DASHSCOPE_MAX_CACHE_MARKERS = 4
_DASHSCOPE_CACHE_MARKER_ROLES = {"system", "user", "assistant", "tool"}
_DASHSCOPE_WORKSPACE_MUTATION_TOOLS = frozenset(
    {
        "apply_patch",
        "edit_file",
        "write_file",
    }
)
_DASHSCOPE_FAILURE_ANCHOR_MARKERS = (
    "assertionerror",
    "traceback",
    "failed",
    "failure",
    "error",
    "exception",
    "expected",
    "actual",
    "exit code:",
    "exit_code=",
)


def _openai_tool_result_content(block: Any) -> str:
    content = block.content if isinstance(block.content, str) else json.dumps(block.content)
    status = getattr(block, "execution_status", None)
    if status is None or not derive_is_error(status):
        return content
    output = content
    if len(output) > _OPENAI_TOOL_STATUS_OUTPUT_MAX_CHARS:
        output = output[:_OPENAI_TOOL_STATUS_OUTPUT_MAX_CHARS]
    return json.dumps(
        {
            "execution_status": compact_provider_status(status),
            "output": output,
        },
        ensure_ascii=False,
    )


def _provider_display_name(provider_kind: str) -> str:
    return {
        "openai": "OpenAI",
        "openrouter": "OpenRouter",
        "deepseek": "DeepSeek",
        "moonshot": "Moonshot",
        "dashscope": "DashScope",
        "gemini": "Gemini",
        "zhipu": "Zhipu",
        "qianfan": "Qianfan",
        "volcengine": "Volcengine",
        "tencent_tokenhub": "Tencent TokenHub",
    }.get(provider_kind, "Provider")


def _dashscope_endpoint_family(base_url: str) -> str:
    url = base_url.strip().lower()
    if "coding-intl.dashscope.aliyuncs.com" in url:
        return "coding_global"
    if "coding.dashscope.aliyuncs.com" in url:
        return "coding_cn"
    if "dashscope-intl.aliyuncs.com" in url:
        return "standard_global"
    if "dashscope.aliyuncs.com" in url:
        return "standard_cn"
    return "custom"


def _http_error_body_text(body: bytes | str) -> str:
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    text = text.strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, str) and message.strip():
        return message.strip()
    return text


def _format_chat_http_error(display_name: str, status_code: int, body: bytes | str) -> str:
    body_text = _http_error_body_text(body) or "empty response body"
    return f"{display_name} chat request failed (HTTP {status_code}): {body_text}"


def _strip_tool_schema_keywords(value: Any, unsupported: frozenset[str]) -> Any:
    if not unsupported:
        return value
    if isinstance(value, dict):
        return {
            key: _strip_tool_schema_keywords(item, unsupported)
            for key, item in value.items()
            if key not in unsupported
        }
    if isinstance(value, list):
        return [_strip_tool_schema_keywords(item, unsupported) for item in value]
    return value


_DASHSCOPE_THINKING_BUDGET_ENV = "OPENSQUILLA_DASHSCOPE_THINKING_BUDGET"
_DASHSCOPE_THINKING_BUDGET_MIN = 1024
_DASHSCOPE_THINKING_BUDGET_MAX = 38_912


def _thinking_budget_tokens_from_env() -> int | None:
    """Read an explicit per-call DashScope thinking budget from the local env.

    Returns a clamped positive token count, or ``None`` when the override is
    unset, blank, or unparseable. This is a provider-local escape hatch for the
    Qwen ``dashscope`` payload branch only; it deliberately does not touch
    ``AgentConfig`` or ``resolve_thinking``, so GLM/``zai`` and the shared
    context-budget governor are unaffected.
    """
    raw = os.environ.get(_DASHSCOPE_THINKING_BUDGET_ENV)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return max(_DASHSCOPE_THINKING_BUDGET_MIN, min(value, _DASHSCOPE_THINKING_BUDGET_MAX))


def _extract_think_tags(text: str) -> str:
    """Extract content from <think> tags. Returns empty string if none found."""
    matches = re.findall(r"<think>([\s\S]*?)</think>", text)
    return "\n".join(matches) if matches else ""


def _strip_think_tags(text: str) -> str:
    """Remove <think> tags from text, including unclosed trailing tags."""
    result = re.sub(r"<think>[\s\S]*?</think>", "", text)
    result = re.sub(r"<think>[\s\S]*$", "", result)
    return result.strip()


def _model_basename(model: str) -> str:
    return model.rsplit("/", 1)[-1].strip().lower()


def _on_official_host(policy: OpenAICompatPolicy, base_url: str) -> bool:
    return bool(policy.official_host) and policy.official_host in base_url.lower()


def _uses_max_completion_tokens(
    policy: OpenAICompatPolicy,
    base_url: str,
    model: str,
) -> bool:
    if not policy.max_completion_tokens_model_prefixes:
        return False
    if not _on_official_host(policy, base_url):
        return False
    return _model_basename(model).startswith(policy.max_completion_tokens_model_prefixes)


def _should_use_max_completion_tokens(
    policy: OpenAICompatPolicy,
    provider_kind: str,
    base_url: str,
    model: str,
    cfg: ChatConfig,
    caps: Any,
) -> bool:
    if _uses_max_completion_tokens(policy, base_url, model):
        return True
    return bool(
        provider_kind == "dashscope"
        and cfg.thinking
        and caps
        and caps.supports_reasoning
        and caps.reasoning_format == "dashscope"
    )


def _should_send_tool_choice(
    provider_kind: str,
    cfg: ChatConfig,
    caps: Any,
) -> bool:
    if cfg.tool_choice is None:
        return False
    if (
        provider_kind == "dashscope"
        and cfg.thinking
        and caps
        and caps.supports_reasoning
        and caps.reasoning_format == "dashscope"
    ):
        return False
    return True


_DASHSCOPE_PRESERVE_THINKING_MODEL_IDS = frozenset(
    {
        "qwen3.6-max-preview",
    }
)


def _dashscope_supports_preserve_thinking(model: str) -> bool:
    model_name = model.rsplit("/", 1)[-1].strip().lower()
    return model_name in _DASHSCOPE_PRESERVE_THINKING_MODEL_IDS


def _should_send_temperature(
    policy: OpenAICompatPolicy,
    base_url: str,
    model: str,
    cfg: ChatConfig,
    caps: Any,
) -> bool:
    if cfg.temperature is None:
        return False
    model_name = _model_basename(model)
    if (
        policy.fixed_sampling_model_prefixes
        and model_name.startswith(policy.fixed_sampling_model_prefixes)
        and cfg.temperature != 1.0
    ):
        return False
    if (
        policy.omit_temperature_when_thinking_model_prefixes
        and _on_official_host(policy, base_url)
        and cfg.thinking
        and bool(caps and caps.supports_reasoning)
        and model_name.startswith(policy.omit_temperature_when_thinking_model_prefixes)
    ):
        return False
    return True


def _resolve_llm_proxy(proxy: str | None) -> str | None:
    if proxy is None:
        return os.environ.get("OPENSQUILLA_LLM_PROXY", "").strip() or None
    return proxy.strip() or None


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


def _parse_plain_json_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a text response ending in ``tool_name{...}``."""
    exact_call = _parse_exact_plain_json_tool_call(text)
    if exact_call is not None:
        return exact_call
    return _parse_trailing_plain_json_tool_call(text)


def _parse_qwen_xml_parameters(body: str, *, lenient: bool = False) -> dict[str, str]:
    pattern = _QWEN_XML_PARAM_LENIENT_RE if lenient else _QWEN_XML_PARAM_RE
    arguments: dict[str, str] = {}
    for match in pattern.finditer(body):
        name = match.group(1).strip()
        if name:
            arguments[name] = match.group("body").strip()
    return arguments


def _parse_qwen_xml_tool_call(raw_text: str) -> tuple[str, dict[str, Any]] | None:
    match = _QWEN_XML_FUNC_RE.search(raw_text)
    if match:
        name = match.group(1).strip()
        if not name:
            return None
        arguments = _parse_qwen_xml_parameters(match.group("body"))
        lenient_arguments = _parse_qwen_xml_parameters(match.group("body"), lenient=True)
        if len(lenient_arguments) > len(arguments):
            arguments = lenient_arguments
        if not arguments and "<parameter=" in match.group("body"):
            return None
        return name, dict(arguments)

    match = _QWEN_XML_FUNC_LENIENT_RE.search(raw_text)
    if not match:
        return None
    name = match.group(1).strip()
    if not name:
        return None
    arguments = _parse_qwen_xml_parameters(match.group("body"), lenient=True)
    if not arguments:
        return None
    return name, dict(arguments)


def _parse_qwen_tool_call_body(raw_text: str) -> tuple[str, dict[str, Any], str] | None:
    stripped = raw_text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    if isinstance(parsed, dict):
        name = parsed.get("name")
        arguments = parsed.get("arguments", {})
        if not isinstance(name, str) or not name.strip():
            return None
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                return None
        if not isinstance(arguments, dict):
            return None
        return name.strip(), arguments, "json"

    xml_call = _parse_qwen_xml_tool_call(stripped)
    if xml_call is None:
        return None
    name, arguments = xml_call
    return name, arguments, "xml"


def _parse_qwen_text_tool_calls(text: str) -> list[tuple[str, dict[str, Any], str]]:
    calls: list[tuple[str, dict[str, Any], str]] = []
    for match in _QWEN_TOOL_CALL_RE.finditer(text):
        parsed = _parse_qwen_tool_call_body(match.group("body"))
        if parsed is not None:
            calls.append(parsed)
    return calls


def _tool_by_name(tools: list[ToolDefinition] | None) -> dict[str, ToolDefinition]:
    if not tools:
        return {}
    return {tool.name: tool for tool in tools}


def _tool_schema_accepts_arguments(
    tool: ToolDefinition | None,
    arguments: dict[str, Any],
) -> bool:
    return not _tool_schema_validation_errors(tool, arguments)


def _tool_schema_validation_errors(
    tool: ToolDefinition | None,
    arguments: dict[str, Any],
) -> list[str]:
    from opensquilla.tools.schema_validation import validate_tool_arguments

    if not isinstance(arguments, dict):
        return ["arguments expected object"]
    if tool is None:
        return []
    schema = tool.input_schema
    return validate_tool_arguments(
        arguments,
        properties=schema.properties or {},
        required=schema.required or [],
        additional_properties=schema.additional_properties,
    )


def _tool_schema_repair_validation_errors(
    tool: ToolDefinition | None,
    arguments: dict[str, Any],
) -> list[str]:
    errors = _tool_schema_validation_errors(tool, arguments)
    if errors or tool is None:
        return errors
    properties = set((tool.input_schema.properties or {}).keys())
    if properties and arguments and not (set(arguments) & properties):
        return ["arguments did not include any known tool properties"]
    return []


def _strip_markdown_json_fence(text: str) -> str:
    match = _MARKDOWN_JSON_FENCE_RE.match(text)
    if not match:
        return text
    return match.group("body").strip()


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    return _extract_json_object_at(text, start)


def _extract_json_object_at(text: str, start: int) -> str | None:
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _json_object_start_positions(text: str, *, limit: int = 128) -> list[int]:
    positions = [index for index, char in enumerate(text) if char == "{"]
    if len(positions) <= limit:
        return positions
    # DashScope corruption often has a valid object after a long invalid prefix.
    # Keep both ends so recovery still sees late embedded tool arguments.
    head = max(1, limit // 4)
    tail = limit - head
    return [*positions[:head], *positions[-tail:]]


def _extract_json_objects(text: str) -> list[str]:
    objects: list[str] = []
    for start in _json_object_start_positions(text):
        candidate = _extract_json_object_at(text, start)
        if candidate is not None and candidate not in objects:
            objects.append(candidate)
    return objects


def _dashscope_tool_argument_candidates_with_source(
    raw_text: str,
) -> list[tuple[str, str]]:
    text = raw_text.strip()
    if not text:
        return []
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(candidate: str | None, source: str) -> None:
        if candidate is None:
            return
        candidate = _strip_markdown_json_fence(candidate.strip())
        if candidate and candidate not in seen:
            candidates.append((candidate, source))
            seen.add(candidate)

    add(text, "direct")
    for match in _DASHSCOPE_PARAMETER_RE.finditer(text):
        add(match.group("body"), "parameter")
    for candidate, _source in list(candidates):
        add(_extract_first_json_object(candidate), "first_json_object")
    for candidate, _source in list(candidates):
        for embedded in _extract_json_objects(candidate):
            add(embedded, "embedded_json_object")
    return candidates


def _dashscope_tool_argument_candidates(raw_text: str) -> list[str]:
    return [
        candidate
        for candidate, _source in _dashscope_tool_argument_candidates_with_source(raw_text)
    ]


def _dashscope_repair_log_name(source: str) -> str:
    if source == "malformed_json":
        return "dashscope_malformed_json"
    if source == "embedded_json_object":
        return "dashscope_embedded_json_object"
    return "dashscope_wrapper_json"


def _escape_invalid_chars_in_json_strings(raw: str) -> str:
    """Escape literal control characters that appear inside JSON strings."""

    output: list[str] = []
    in_string = False
    escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
                output.append(char)
                continue
            if char == "\\":
                escaped = True
                output.append(char)
                continue
            if char == '"':
                in_string = False
                output.append(char)
                continue
            if ord(char) < 0x20:
                output.append(f"\\u{ord(char):04x}")
                continue
            output.append(char)
            continue
        if char == '"':
            in_string = True
        output.append(char)
    return "".join(output)


def _repair_malformed_json_object_candidate(candidate: str) -> dict[str, Any] | None:
    text = candidate.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text, strict=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    else:
        return parsed if isinstance(parsed, dict) else None

    fixed = text
    open_curly = fixed.count("{") - fixed.count("}")
    open_bracket = fixed.count("[") - fixed.count("]")
    if open_bracket > 0:
        fixed += "]" * open_bracket
    if open_curly > 0:
        fixed += "}" * open_curly
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)

    for _ in range(50):
        try:
            parsed = json.loads(fixed)
        except json.JSONDecodeError:
            if fixed.endswith("}") and fixed.count("}") > fixed.count("{"):
                fixed = fixed[:-1]
                continue
            if fixed.endswith("]") and fixed.count("]") > fixed.count("["):
                fixed = fixed[:-1]
                continue
            break
        else:
            return parsed if isinstance(parsed, dict) else None

    escaped = _escape_invalid_chars_in_json_strings(fixed)
    if escaped != fixed:
        try:
            parsed = json.loads(escaped)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_json_object_candidate(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        try:
            nested = json.loads(parsed)
        except json.JSONDecodeError:
            return None
        return nested if isinstance(nested, dict) else None
    return None


def _unwrap_raw_json_arguments(arguments: dict[str, Any]) -> dict[str, Any] | None:
    raw = arguments.get("_raw")
    if set(arguments) != {"_raw"} or not isinstance(raw, str):
        return None
    for candidate in _dashscope_tool_argument_candidates(raw):
        parsed = _parse_json_object_candidate(candidate)
        if parsed is not None:
            return parsed
    return None


def _repair_dashscope_tool_arguments(
    raw_text: str,
    *,
    tool_name: str,
    tools_by_name: Mapping[str, ToolDefinition],
    schema_errors: list[str] | None = None,
    alias_conflicts: list[str] | None = None,
) -> tuple[dict[str, Any], str, list[dict[str, str]]] | None:
    from opensquilla.tools.argument_normalization import (
        canonicalize_tool_arguments,
        format_alias_conflicts,
    )

    tool = tools_by_name.get(tool_name)
    for candidate, source in _dashscope_tool_argument_candidates_with_source(raw_text):
        parsed = _parse_json_object_candidate(candidate)
        repair_source = source
        if parsed is None:
            parsed = _repair_malformed_json_object_candidate(candidate)
            repair_source = "malformed_json"
        if parsed is None:
            continue
        unwrapped = _unwrap_raw_json_arguments(parsed)
        if unwrapped is not None:
            parsed = unwrapped
        normalization = canonicalize_tool_arguments(tool_name, parsed)
        if normalization.conflicts:
            conflict_messages = format_alias_conflicts(normalization.conflicts)
            if alias_conflicts is not None:
                alias_conflicts.extend(conflict_messages)
            if schema_errors is not None:
                schema_errors.extend(conflict_messages)
            continue
        parsed = normalization.arguments
        errors = _tool_schema_repair_validation_errors(tool, parsed)
        if not errors:
            return (
                parsed,
                _dashscope_repair_log_name(repair_source),
                normalization.aliases_applied,
            )
        if schema_errors is not None:
            schema_errors.extend(errors)
    return None


def _parse_openai_tool_arguments(
    *,
    provider_kind: str,
    model: str,
    tool_name: str,
    tool_use_id: str,
    raw_text: str,
    tools_by_name: Mapping[str, ToolDefinition],
) -> tuple[dict[str, Any], bool, bool]:
    """Parse provider tool arguments.

    Returns ``(arguments, json_valid, repaired)``. ``json_valid`` describes the
    executable argument object emitted downstream, not necessarily whether the
    provider's raw bytes were valid as-is.
    """

    if not raw_text:
        return {}, True, False
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        if provider_kind == "dashscope":
            schema_errors: list[str] = []
            alias_conflicts: list[str] = []
            repaired = _repair_dashscope_tool_arguments(
                raw_text,
                tool_name=tool_name,
                tools_by_name=tools_by_name,
                schema_errors=schema_errors,
                alias_conflicts=alias_conflicts,
            )
            if repaired is not None:
                repaired_arguments, repair_name, aliases_applied = repaired
                if aliases_applied:
                    log.warning(
                        "provider.tool_arguments_aliases_applied",
                        provider=provider_kind,
                        model=model,
                        tool=tool_name,
                        tool_use_id=tool_use_id,
                        aliases=aliases_applied,
                    )
                log.warning(
                    "provider.tool_arguments_json_repaired",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    tool_use_id=tool_use_id,
                    raw_chars=len(raw_text),
                    repair=repair_name,
                )
                return repaired_arguments, True, True
            if alias_conflicts:
                log.warning(
                    "provider.tool_arguments_alias_conflict",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    tool_use_id=tool_use_id,
                    raw_chars=len(raw_text),
                    conflicts=alias_conflicts[:5],
                )
            if schema_errors:
                log.warning(
                    "provider.tool_arguments_json_invalid",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    tool_use_id=tool_use_id,
                    raw_chars=len(raw_text),
                    reason="schema_validation_failed",
                    errors=schema_errors[:5],
                )
                return {"_raw": raw_text}, False, False
        log.warning(
            "provider.tool_arguments_json_invalid",
            provider=provider_kind,
            model=model,
            tool=tool_name,
            tool_use_id=tool_use_id,
            raw_chars=len(raw_text),
            error=str(exc),
        )
        return {"_raw": raw_text}, False, False

    if isinstance(parsed, dict):
        if provider_kind == "dashscope":
            unwrapped = _unwrap_raw_json_arguments(parsed)
            if unwrapped is not None and _tool_schema_accepts_arguments(
                tools_by_name.get(tool_name),
                unwrapped,
            ):
                log.warning(
                    "provider.tool_arguments_json_repaired",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    tool_use_id=tool_use_id,
                    raw_chars=len(raw_text),
                    repair="dashscope_nested_raw_json",
                )
                return unwrapped, True, True
        return parsed, True, False

    log.warning(
        "provider.tool_arguments_json_invalid",
        provider=provider_kind,
        model=model,
        tool=tool_name,
        tool_use_id=tool_use_id,
        raw_chars=len(raw_text),
        error=f"tool arguments decoded to {type(parsed).__name__}, expected object",
    )
    return {"_raw": raw_text}, False, False


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_present(*sources: tuple[Mapping[str, Any], str]) -> int:
    """Return the first source[key] that is actually present (key in dict).

    Truthiness chains via ``or`` would skip an explicit ``0`` from the canonical
    field and silently fall through to a less-canonical one — e.g. an
    ``cache_creation_input_tokens=0`` getting overwritten by a non-zero
    ``prompt_tokens_details.cache_write_tokens``. Use ``in`` instead so a real
    zero wins.
    """
    for src, key in sources:
        if isinstance(src, Mapping) and key in src:
            return _coerce_int(src[key])
    return 0


def _usage_fields(usage: Mapping[str, Any] | None) -> tuple[int, int, int, int, int, float]:
    if not usage:
        return 0, 0, 0, 0, 0, 0.0

    input_tokens = _coerce_int(usage.get("prompt_tokens"))
    output_tokens = _coerce_int(usage.get("completion_tokens"))
    completion_details_raw = usage.get("completion_tokens_details") or {}
    completion_details = (
        completion_details_raw if isinstance(completion_details_raw, Mapping) else {}
    )
    reasoning_tokens = _coerce_int(completion_details.get("reasoning_tokens"))
    prompt_details_raw = usage.get("prompt_tokens_details") or {}
    prompt_details = prompt_details_raw if isinstance(prompt_details_raw, Mapping) else {}
    top_cache_creation = usage.get("cache_creation") or {}
    prompt_cache_creation = prompt_details.get("cache_creation") or {}

    # Cache reads: keys we accept, in priority order.
    #   - prompt_tokens_details.cached_tokens  — OpenAI native + most OpenRouter
    #     proxies.
    #   - usage.cached_tokens                 — DashScope OpenAI-compatible alias.
    #   - usage.prompt_cache_hit_tokens        — DeepSeek native shape.
    cached_tokens = _first_present(
        (prompt_details, "cached_tokens"),
        (usage, "cached_tokens"),
        (usage, "prompt_cache_hit_tokens"),
    )

    # Cache writes: keys we accept, in priority order.
    #   - usage.cache_creation_input_tokens          — Anthropic-via-OpenRouter passthrough.
    #   - prompt_tokens_details.cache_write_tokens          — OpenRouter documented field.
    #   - usage.cache_write_tokens                          — top-level alias some proxies use.
    #   - prompt_tokens_details.cache_creation_input_tokens — DashScope OpenAI-compatible.
    #   - *.cache_creation.ephemeral_5m_input_tokens        — DashScope documented object shape.
    #   - prompt_tokens_details.cache_creation_tokens — defensive fallback.
    cache_write_tokens = _first_present(
        (usage, "cache_creation_input_tokens"),
        (prompt_details, "cache_write_tokens"),
        (usage, "cache_write_tokens"),
        (prompt_details, "cache_creation_input_tokens"),
        (top_cache_creation, "ephemeral_5m_input_tokens"),
        (prompt_cache_creation, "ephemeral_5m_input_tokens"),
        (prompt_details, "cache_creation_tokens"),
    )

    billed_cost = _coerce_float(usage.get("cost", usage.get("total_cost")))
    return (
        input_tokens,
        output_tokens,
        reasoning_tokens,
        cached_tokens,
        cache_write_tokens,
        billed_cost,
    )


def _provider_billed_cost(provider_kind: str, raw_billed_cost: float) -> tuple[float, str]:
    """Return trusted provider-billed cost and its source marker."""
    if compat_policy_for_kind(provider_kind).trust_billed_cost and raw_billed_cost > 0.0:
        return raw_billed_cost, "provider_billed"
    return 0.0, "none"


def _resolve_tool_call_index(
    tc: Mapping[str, Any],
    tools_acc: ToolStreamAccumulator,
) -> int:
    """Resolve the accumulator slot for a streamed tool-call delta.

    Most upstreams send an explicit ``index``, but some (Gemini's
    OpenAI-compat endpoint, assorted local gateways) omit it: fall back to
    matching the provider-supplied id against known calls, then to opening a
    new slot — a missing index must never fail the stream.
    """
    if "index" in tc:
        return _coerce_int(tc["index"])
    tool_call_id = tc.get("id")
    if isinstance(tool_call_id, str) and tool_call_id:
        key = tools_acc.find_key_for_tool_call_id(tool_call_id)
        if key is not None:
            return cast(int, key)
        return tools_acc.next_int_key()
    single = tools_acc.single_key()
    if single is not None:
        return cast(int, single)
    return tools_acc.next_int_key()


def _dashscope_tool_call_chunk_is_empty(tc: Mapping[str, Any]) -> bool:
    function = tc.get("function")
    if not isinstance(function, Mapping):
        function = {}
    return not (
        tc.get("id")
        or function.get("name")
        or function.get("arguments")
    )


def _stream_timeout(timeout: float) -> httpx.Timeout:
    connect = _coerce_float(os.environ.get("OPENSQUILLA_LLM_STREAM_CONNECT_TIMEOUT_SECONDS"))
    if connect <= 0:
        connect = 12.0
    connect = min(connect, max(timeout, 1.0))
    write = _coerce_float(os.environ.get("OPENSQUILLA_LLM_STREAM_WRITE_TIMEOUT_SECONDS"))
    if write <= 0:
        write = max(60.0, timeout)
    return httpx.Timeout(timeout, connect=connect, write=write, pool=10.0)


def _synthesize_text_tool_events(
    full_text: str,
    tools: list[ToolDefinition] | None,
    *,
    provider_kind: str,
    model: str,
) -> list[ToolUseStartEvent | ToolUseEndEvent]:
    from opensquilla.tools.argument_normalization import (
        canonicalize_tool_arguments,
        format_alias_conflicts,
    )

    if not tools or not full_text:
        return []

    events: list[ToolUseStartEvent | ToolUseEndEvent] = []
    allowed_tool_names = {tool.name for tool in tools}
    tools_by_name = _tool_by_name(tools)

    if provider_kind == "dashscope" and "<tool_call>" in full_text:
        for tool_name, raw_arguments, parse_format in _parse_qwen_text_tool_calls(full_text):
            if tool_name not in allowed_tool_names:
                log.warning(
                    "provider.qwen_text_tool_call_rejected_unknown_tool",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                )
                continue
            normalization = canonicalize_tool_arguments(tool_name, raw_arguments)
            if normalization.conflicts:
                conflicts = format_alias_conflicts(normalization.conflicts)
                log.warning(
                    "provider.tool_arguments_alias_conflict",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    raw_chars=len(full_text),
                    conflicts=conflicts[:5],
                )
                log.warning(
                    "provider.qwen_text_tool_call_rejected_schema",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    parse_format=parse_format,
                    errors=conflicts[:5],
                )
                continue
            arguments = normalization.arguments
            schema_errors = _tool_schema_repair_validation_errors(
                tools_by_name.get(tool_name),
                arguments,
            )
            if schema_errors:
                log.warning(
                    "provider.qwen_text_tool_call_rejected_schema",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    parse_format=parse_format,
                    errors=schema_errors[:5],
                )
                continue
            if normalization.aliases_applied:
                log.warning(
                    "provider.tool_arguments_aliases_applied",
                    provider=provider_kind,
                    model=model,
                    tool=tool_name,
                    aliases=normalization.aliases_applied,
                )
            tool_use_id = f"qwen_text_{uuid4().hex[:12]}"
            log.warning(
                "provider.qwen_text_tool_call_parsed",
                provider=provider_kind,
                model=model,
                tool=tool_name,
                tool_use_id=tool_use_id,
                parse_format=parse_format,
            )
            events.append(
                ToolUseStartEvent(
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    synthetic_from_text=True,
                )
            )
            events.append(
                ToolUseEndEvent(
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    synthetic_from_text=True,
                )
            )
        return events

    if contains_minimax_protocol(full_text):
        for minimax_call in parse_minimax_tool_calls(full_text):
            if minimax_call.name not in allowed_tool_names:
                continue
            tool_use_id = f"minimax_compat_{uuid4().hex[:12]}"
            events.append(
                ToolUseStartEvent(
                    tool_use_id=tool_use_id,
                    tool_name=minimax_call.name,
                    synthetic_from_text=True,
                )
            )
            events.append(
                ToolUseEndEvent(
                    tool_use_id=tool_use_id,
                    tool_name=minimax_call.name,
                    arguments=dict(minimax_call.arguments),
                    synthetic_from_text=True,
                )
            )
    else:
        plain_call = _parse_plain_json_tool_call(full_text)
        if plain_call is not None:
            tool_name, arguments = plain_call
            if tool_name in allowed_tool_names:
                tool_use_id = f"text_compat_{uuid4().hex[:12]}"
                events.append(
                    ToolUseStartEvent(
                        tool_use_id=tool_use_id,
                        tool_name=tool_name,
                        synthetic_from_text=True,
                    )
                )
                events.append(
                    ToolUseEndEvent(
                        tool_use_id=tool_use_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        synthetic_from_text=True,
                    )
                )
    return events


def _build_openai_tool(
    tool: ToolDefinition,
    *,
    unsupported_keywords: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    schema = tool.input_schema.model_dump(exclude_none=True, by_alias=True)
    schema = _strip_tool_schema_keywords(schema, unsupported_keywords)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        },
    }


def _openrouter_model_likely_supports_explicit_prompt_cache(model: str) -> bool:
    return supports_openrouter_explicit_prompt_cache(model)


def _dashscope_model_likely_supports_explicit_prompt_cache(model: str) -> bool:
    """Return True for DashScope model families with documented context cache support."""
    model_name = model.rsplit("/", 1)[-1].strip().lower()
    exact_models = {
        "qwen3-max",
        "qwen-plus",
        "qwen-flash",
        "deepseek-v3.2",
        "kimi-k2.6",
        "kimi-k2.5",
        "glm-5.1",
    }
    if model_name in exact_models:
        return True
    return model_name.startswith(
        (
            "qwen3.7-max",
            "qwen3.6-max-preview",
            "qwen3.7-plus",
            "qwen3.6-plus",
            "qwen3.5-plus",
            "qwen3.6-flash",
            "qwen3.5-flash",
            "qwen3-coder-plus",
            "qwen3-coder-flash",
            "qwen3-vl-plus",
            "qwen3-vl-flash",
        )
    )


def _supports_explicit_prompt_cache(
    provider_kind: str,
    model: str,
    cache_mode: str,
) -> bool:
    if cache_mode == "off":
        return False
    if provider_kind == "openrouter":
        return cache_mode == "on" or _openrouter_model_likely_supports_explicit_prompt_cache(model)
    if provider_kind == "dashscope":
        return cache_mode == "on" or _dashscope_model_likely_supports_explicit_prompt_cache(model)
    return False


def _openrouter_model_is_anthropic(model: str) -> bool:
    return model.strip().lower().startswith("anthropic/")


def _openrouter_model_uses_alibaba_message_cache(model: str) -> bool:
    model_l = model.strip().lower()
    model_name = model_l.rsplit("/", 1)[-1]
    return model_l.startswith("qwen/") or model_name.startswith(
        ("qwen3.6-flash", "qwen3.5-flash", "qwen3-coder")
    )


def _openrouter_anthropic_should_use_top_level_cache(
    *,
    provider_kind: str,
    model: str,
    cfg: ChatConfig,
) -> bool:
    return (
        provider_kind == "openrouter"
        and cfg.cache_mode in {"auto", "on"}
        and _openrouter_model_is_anthropic(model)
    )


def _build_cache_breakpoint_blocks(
    cache_breakpoints: list[dict[str, str]],
    *,
    max_cache_markers: int | None = None,
) -> list[dict[str, Any]]:
    content_blocks: list[dict[str, Any]] = []
    markers_used = 0
    for bp in cache_breakpoints:
        block: dict[str, Any] = {"type": "text", "text": bp["text"]}
        if bp.get("cache") and (max_cache_markers is None or markers_used < max_cache_markers):
            block["cache_control"] = dict(_EPHEMERAL_CACHE_CONTROL)
            markers_used += 1
        content_blocks.append(block)
    return content_blocks


def _count_explicit_cache_markers(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            total += sum(
                1 for block in content if isinstance(block, dict) and block.get("cache_control")
            )
    return total


def _cache_marker_positions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for message_index, message in enumerate(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if isinstance(block, dict) and block.get("cache_control"):
                positions.append(
                    {
                        "message_index": message_index,
                        "role": message.get("role", ""),
                        "block_index": block_index,
                        "block_type": block.get("type", ""),
                        "text_chars": len(block.get("text", ""))
                        if isinstance(block.get("text"), str)
                        else 0,
                    }
                )
    return positions


def _payload_cache_shape(
    payload: Mapping[str, Any],
    *,
    tools: list[ToolDefinition] | None,
) -> dict[str, Any]:
    messages = payload.get("messages") if isinstance(payload, Mapping) else None
    openai_messages = messages if isinstance(messages, list) else []
    system_payload = (
        openai_messages[0]
        if openai_messages and openai_messages[0].get("role") == "system"
        else None
    )
    non_system_prefix_item_hashes = _openrouter_non_system_prefix_item_hashes(openai_messages)
    return {
        "top_level_cache_control": bool(payload.get("cache_control")),
        "explicit_cache_markers": _cache_marker_positions(openai_messages),
        "explicit_cache_marker_count": _count_explicit_cache_markers(openai_messages),
        "system_hash": _stable_json_hash(system_payload) if system_payload else "",
        "tools_hash": _stable_json_hash(payload.get("tools", [])) if tools else "",
        "messages_prefix_hash": _stable_json_hash(openai_messages[:-1]),
        "first_non_system_hash": (
            non_system_prefix_item_hashes[0] if non_system_prefix_item_hashes else ""
        ),
        "non_system_prefix_item_hashes": non_system_prefix_item_hashes,
        "message_count": len(openai_messages),
    }


def _log_provider_cache_usage(
    *,
    provider_kind: str,
    model: str,
    actual_model: str,
    input_tokens: int,
    cached_tokens: int,
    cache_write_tokens: int,
    cache_shape: Mapping[str, Any],
) -> None:
    if provider_kind != "dashscope":
        return
    log.info(
        f"{provider_kind}.prompt_cache_usage",
        model=model,
        actual_model=actual_model,
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        cached_input_ratio=round(cached_tokens / input_tokens, 6) if input_tokens else 0.0,
        system_hash=cache_shape.get("system_hash", ""),
        tools_hash=cache_shape.get("tools_hash", ""),
        messages_prefix_hash=cache_shape.get("messages_prefix_hash", ""),
        explicit_cache_marker_count=cache_shape.get("explicit_cache_marker_count", 0),
        explicit_cache_markers=cache_shape.get("explicit_cache_markers", []),
        message_count=cache_shape.get("message_count", 0),
    )


def _attach_cache_control_to_latest_text_messages(
    messages: list[dict[str, Any]],
    *,
    max_cache_markers: int,
) -> None:
    def _attach_to_message(message: dict[str, Any]) -> bool:
        content = message.get("content")
        if isinstance(content, str):
            if not content.strip():
                return False
            message["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": dict(_EPHEMERAL_CACHE_CONTROL),
                }
            ]
            return True
        if not isinstance(content, list):
            return False
        for block in reversed(content):
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and block["text"].strip()
                and not block.get("cache_control")
            ):
                block["cache_control"] = dict(_EPHEMERAL_CACHE_CONTROL)
                return True
        return False

    markers_remaining = max_cache_markers - _count_explicit_cache_markers(messages)
    if markers_remaining <= 0:
        return

    # Keep the initial user task pinned. In long agentic coding loops, spending all remaining
    # markers on the moving tail can collapse DashScope hits to the system block.
    pinned_initial_user_index: int | None = None
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        pinned_initial_user_index = index
        if _attach_to_message(message):
            markers_remaining -= 1
        break
    if markers_remaining <= 0:
        return

    for index, message in reversed(list(enumerate(messages))):
        if pinned_initial_user_index is not None and index == pinned_initial_user_index:
            continue
        if message.get("role") not in _DASHSCOPE_CACHE_MARKER_ROLES:
            continue
        if _attach_to_message(message):
            markers_remaining -= 1
            if markers_remaining <= 0:
                return


def _disambiguate_repeated_tool_call_arguments_for_dashscope(
    messages: list[dict[str, Any]],
) -> None:
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, sort_keys=True)

    def _preview_tool_result(tool_call_id: str) -> str:
        result = result_messages_by_id.get(tool_call_id)
        if result is None:
            return "missing"
        content = _content_text(result.get("content", ""))
        preview = content.replace("\n", "\\n")
        if len(preview) > 160:
            preview = preview[:157] + "..."
        return preview

    def _provider_result_details(tool_call_id: str) -> dict[str, Any]:
        result = result_messages_by_id.get(tool_call_id)
        if result is None:
            return {
                "result_is_error": None,
                "exit_code": None,
                "execution_reason": "missing_tool_result",
                "result_sha256": None,
                "result_chars": 0,
                "failure_anchors": [],
            }

        content = _content_text(result.get("content", ""))
        result_text = content
        execution_status: dict[str, Any] | None = None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            status = parsed.get("execution_status")
            if isinstance(status, dict):
                execution_status = status
            output = parsed.get("output")
            if isinstance(output, str):
                result_text = output

        lowered = result_text.lower()
        failure_anchors = [
            line.strip()
            for line in result_text.splitlines()
            if line.strip()
            and any(marker in line.lower() for marker in _DASHSCOPE_FAILURE_ANCHOR_MARKERS)
        ][:3]

        status_value = (
            str(execution_status.get("status") or "") if execution_status is not None else ""
        )
        inferred_failure = bool(failure_anchors) or bool(
            re.search(r"\bexit(?: code|_code)[:=]\s*[1-9][0-9]*\b", lowered)
        )
        result_is_error = (
            status_value in {"error", "timeout", "cancelled"}
            if execution_status is not None
            else inferred_failure
        )
        execution_reason = (
            str(execution_status.get("reason") or "") if execution_status is not None else ""
        )
        if not execution_reason:
            execution_reason = "failure_anchor" if inferred_failure else "unknown"

        return {
            "result_is_error": result_is_error,
            "exit_code": (
                execution_status.get("exit_code") if execution_status is not None else None
            ),
            "execution_reason": execution_reason,
            "result_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
            "result_chars": len(content),
            "failure_anchors": failure_anchors,
        }

    def _summary_for_omitted_duplicate(
        *,
        name: str,
        arguments: dict[str, Any],
        repeat_index: int,
        tool_call_id: str,
        workspace_epoch: int,
        latest_workspace_epoch: int,
    ) -> str:
        result_details = _provider_result_details(tool_call_id)
        anchors = json.dumps(
            result_details["failure_anchors"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        exit_code = result_details["exit_code"]
        exit_code_text = "null" if exit_code is None else str(exit_code)
        result_sha256 = result_details["result_sha256"] or "missing"
        return (
            "[Earlier duplicate tool interaction omitted for DashScope replay "
            f"compatibility: tool={name}, arguments_sha256={_stable_json_hash(arguments)}, "
            f"repeat_index={repeat_index}, workspace_epoch={workspace_epoch}, "
            f"latest_workspace_epoch={latest_workspace_epoch}, "
            f"result_is_error={str(result_details['result_is_error']).lower()}, "
            f"exit_code={exit_code_text}, "
            f"execution_reason={result_details['execution_reason']}, "
            f"result_sha256={result_sha256}, result_chars={result_details['result_chars']}, "
            f"failure_anchors={anchors}, result_preview="
            f"{json.dumps(_preview_tool_result(tool_call_id), ensure_ascii=False)}]"
        )

    result_messages_by_id = {
        message["tool_call_id"]: message
        for message in messages
        if message.get("role") == "tool" and isinstance(message.get("tool_call_id"), str)
    }
    tool_name_by_id: dict[str, str] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_call_id = tool_call.get("id")
            function = tool_call.get("function")
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(tool_call_id, str) and isinstance(name, str):
                tool_name_by_id[tool_call_id] = name

    occurrences: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], int] = {}
    workspace_epoch = 0
    for message_index, message in enumerate(messages):
        if message.get("role") == "tool":
            tool_call_id = message.get("tool_call_id")
            if (
                isinstance(tool_call_id, str)
                and tool_name_by_id.get(tool_call_id) in _DASHSCOPE_WORKSPACE_MUTATION_TOOLS
                and _provider_result_details(tool_call_id)["result_is_error"] is not True
            ):
                workspace_epoch += 1
            continue
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            arguments = function.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, str):
                continue
            try:
                parsed_arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed_arguments, dict):
                continue
            canonical_arguments = json.dumps(
                parsed_arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            key = (name, canonical_arguments)
            repeat_index = seen.get(key, 0)
            seen[key] = repeat_index + 1
            occurrences.append(
                {
                    "key": key,
                    "message_index": message_index,
                    "tool_call": tool_call,
                    "tool_call_id": tool_call.get("id"),
                    "tool": name,
                    "arguments": parsed_arguments,
                    "repeat_index": repeat_index,
                    "workspace_epoch": workspace_epoch,
                }
            )

    if not occurrences:
        return

    last_occurrence_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for occurrence in occurrences:
        last_occurrence_by_key[occurrence["key"]] = occurrence

    omitted_summaries_by_id: dict[str, str] = {}
    for occurrence in occurrences:
        if last_occurrence_by_key.get(occurrence["key"]) is occurrence:
            continue
        tool_call_id = occurrence.get("tool_call_id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            continue
        omitted_summaries_by_id[tool_call_id] = _summary_for_omitted_duplicate(
            name=str(occurrence["tool"]),
            arguments=cast(dict[str, Any], occurrence["arguments"]),
            repeat_index=int(occurrence["repeat_index"]),
            tool_call_id=tool_call_id,
            workspace_epoch=int(occurrence["workspace_epoch"]),
            latest_workspace_epoch=int(
                last_occurrence_by_key[occurrence["key"]].get("workspace_epoch", 0)
            ),
        )

    if not omitted_summaries_by_id:
        return

    rewritten: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "tool" and message.get("tool_call_id") in omitted_summaries_by_id:
            continue
        tool_calls = message.get("tool_calls")
        if message.get("role") != "assistant" or not isinstance(tool_calls, list):
            rewritten.append(message)
            continue

        kept_calls: list[dict[str, Any]] = []
        summaries: list[str] = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                kept_calls.append(tool_call)
                continue
            tool_call_id = tool_call.get("id")
            if isinstance(tool_call_id, str) and tool_call_id in omitted_summaries_by_id:
                summaries.append(omitted_summaries_by_id[tool_call_id])
            else:
                kept_calls.append(tool_call)
        if not summaries:
            rewritten.append(message)
            continue

        summary_text = "\n".join(summaries)
        if kept_calls:
            next_message = dict(message)
            next_message["tool_calls"] = kept_calls
            existing_content = next_message.get("content")
            next_message["content"] = (
                f"{existing_content}\n{summary_text}"
                if isinstance(existing_content, str) and existing_content
                else summary_text
            )
            rewritten.append(next_message)
        else:
            rewritten.append({"role": "assistant", "content": summary_text})
    messages[:] = rewritten


def _stable_json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _openrouter_non_system_prefix_item_hashes(
    messages: list[dict[str, Any]], *, max_items: int = 3
) -> list[str]:
    hashes: list[str] = []
    for message in messages:
        if message.get("role") == "system":
            continue
        hashes.append(_stable_json_hash(message))
        if len(hashes) >= max_items:
            break
    return hashes


def _attach_reasoning_content(
    msg: Message,
    payload: dict[str, Any],
    *,
    include_reasoning_content: bool = True,
    require_assistant_reasoning_content: bool = False,
) -> dict[str, Any]:
    if include_reasoning_content and msg.role == "assistant" and msg.reasoning_content:
        payload["reasoning_content"] = msg.reasoning_content
    elif (
        include_reasoning_content
        and require_assistant_reasoning_content
        and msg.role == "assistant"
    ):
        payload["reasoning_content"] = ""
    return payload


def _requires_assistant_reasoning_content(policy: OpenAICompatPolicy, model: str) -> bool:
    return model.strip().lower() in policy.require_reasoning_content_model_ids


def _should_replay_reasoning_content(
    *,
    policy: OpenAICompatPolicy,
    model: str,
    caps: ModelCapabilities | None,
    thinking: bool = False,
) -> bool:
    if _requires_assistant_reasoning_content(policy, model):
        return True
    if not caps or not caps.supports_reasoning:
        return False
    if caps.reasoning_format == "dashscope":
        if not thinking:
            return False
        return _dashscope_supports_preserve_thinking(model)
    return bool(policy.replay_reasoning_format) and (
        caps.reasoning_format == policy.replay_reasoning_format
    )


def _build_openai_messages(
    msg: Message,
    *,
    include_reasoning_content: bool = True,
    require_assistant_reasoning_content: bool = False,
    replay_provider_state: bool = True,
) -> list[dict[str, Any]]:
    """Convert a opensquilla Message into one or more OpenAI-format message dicts.

    Returns a list because OpenAI requires one ``{"role": "tool"}`` message
    per tool result, while opensquilla packs multiple tool results into a single
    Message.

    Invariant: tool_result blocks never coexist with text/image blocks in the
    same Message (agent.py always packs tool results into a dedicated message).
    """
    if isinstance(msg.content, str):
        return [
            _attach_reasoning_content(
                msg,
                {"role": msg.role, "content": msg.content},
                include_reasoning_content=include_reasoning_content,
                require_assistant_reasoning_content=require_assistant_reasoning_content,
            )
        ]

    parts: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    thinking_signature: str | None = None

    for block in msg.content:
        if block.type == "text":
            parts.append({"type": "text", "text": block.text})
        elif block.type == "thinking":
            sig = getattr(block, "signature", None)
            if isinstance(sig, str) and sig:
                thinking_signature = sig
        elif block.type == "tool_use":
            tc_dict: dict[str, Any] = {
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                },
            }
            tool_calls.append(tc_dict)
        elif block.type == "image":
            if block.source_type == "url":
                parts.append({"type": "image_url", "image_url": {"url": block.data}})
            else:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{block.media_type};base64,{block.data}"},
                    }
                )
        elif block.type == "tool_result":
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": block.tool_use_id,
                    "content": _openai_tool_result_content(block),
                }
            )

    # Tool results → one message per result (OpenAI requirement)
    if tool_results:
        return tool_results

    # Assistant message with tool_calls (preserve text alongside calls)
    if tool_calls:
        # Gemini requires thought_signature on the first tool_call in each
        # step of the current turn. Attach it if a ContentBlockThinking with
        # a signature preceded the tool_use blocks — but never replay a
        # signature to a provider that did not mint it.
        if thinking_signature and tool_calls and replay_provider_state:
            tool_calls[0]["extra_content"] = {
                "google": {"thought_signature": thinking_signature},
            }
        result: dict[str, Any] = {"role": msg.role, "tool_calls": tool_calls}
        text_content = " ".join(p["text"] for p in parts if p.get("type") == "text")
        if text_content:
            result["content"] = text_content
        return [
            _attach_reasoning_content(
                msg,
                result,
                include_reasoning_content=include_reasoning_content,
                require_assistant_reasoning_content=require_assistant_reasoning_content,
            )
        ]

    # If parts contain mixed content (text + images), return as list for multimodal
    has_non_text = any(p["type"] != "text" for p in parts)
    if has_non_text:
        return [
            _attach_reasoning_content(
                msg,
                {"role": msg.role, "content": parts},
                include_reasoning_content=include_reasoning_content,
                require_assistant_reasoning_content=require_assistant_reasoning_content,
            )
        ]
    content_text = " ".join(p["text"] for p in parts if p["type"] == "text")
    return [
        _attach_reasoning_content(
            msg,
            {"role": msg.role, "content": content_text},
            include_reasoning_content=include_reasoning_content,
            require_assistant_reasoning_content=require_assistant_reasoning_content,
        )
    ]


class OpenAIProvider:
    """Streams from OpenAI-compatible Chat Completions API (SSE)."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = _OPENAI_API_BASE,
        org_id: str | None = None,
        proxy: str | None = None,
        provider_kind: str | None = None,
        provider_routing: Mapping[str, str] | None = None,
        compat: OpenAICompatPolicy | None = None,
        replay_provider_state: bool = True,
    ) -> None:
        self._api_key = clean_header_secret(api_key, label="LLM API key")
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._proxy = _resolve_llm_proxy(proxy)
        self._org_id = org_id
        if not provider_kind:
            # Fallback for direct construction only (tests, ad-hoc
            # embedding): every production path flows through
            # selector._build_provider, which always passes the registry
            # spec's provider_kind. The base-url sniff keeps a bare
            # OpenAIProvider(base_url="https://openrouter.ai/...") resolving
            # the OpenRouter dialect instead of silently degrading.
            provider_kind = "openrouter" if "openrouter.ai" in self._base_url else "openai"
        self._provider_kind = provider_kind
        self._compat = compat or compat_policy_for_kind(self._provider_kind)
        self._replay_provider_state = replay_provider_state
        self._provider_routing: Mapping[str, str] = provider_routing or {}

    @property
    def model(self) -> str:
        """Model id this provider was configured with.

        Public so callers (e.g. derived-cache key construction) can identify
        the underlying model without prying at private state.
        """
        return self._model

    def provider_metadata(self) -> ProviderMetadata:
        """Return read-only non-secret provider metadata for consumers."""
        return ProviderMetadata(
            provider_name=self.provider_name,
            provider_kind=self._provider_kind,
            model=self._model,
            base_url=self._base_url,
        )

    def provider_connection_config(self) -> ProviderConnectionConfig:
        """Return provider-owned connection fields for internal runtime calls."""
        return ProviderConnectionConfig(
            provider_kind=self._provider_kind,
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
        )

    def _api_url(self, path: str) -> str:
        """Build an API URL without duplicating the version prefix.

        A base URL already carrying a version segment (``/v1``…``/vN``, e.g.
        Qianfan's ``/v2``, Volcengine's ``/api/v3``, Zhipu's ``/paas/v4``)
        absorbs the canonical ``/v1`` path prefix.
        """
        if path.startswith("/v1/") and _VERSIONED_BASE_URL_RE.search(self._base_url):
            return f"{self._base_url}{path[3:]}"
        return f"{self._base_url}{path}"

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        cfg = config or ChatConfig()
        return self._stream(messages, tools, cfg)

    async def _stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        cfg: ChatConfig,
    ) -> AsyncIterator[StreamEvent]:
        openai_messages: list[dict[str, Any]] = []
        caps = cfg.model_capabilities
        include_reasoning_content = _should_replay_reasoning_content(
            policy=self._compat,
            model=self._model,
            caps=caps,
            thinking=cfg.thinking,
        )
        if cfg.system:
            explicit_cache_supported = (
                self._compat.supports_explicit_prompt_cache
                and _supports_explicit_prompt_cache(
                    self._provider_kind,
                    self._model,
                    cfg.cache_mode,
                )
            )
            if cfg.cache_breakpoints and explicit_cache_supported:
                # Split system prompt into cached base + dynamic parts
                content_blocks = _build_cache_breakpoint_blocks(
                    cfg.cache_breakpoints,
                    max_cache_markers=(
                        _DASHSCOPE_MAX_CACHE_MARKERS if self._provider_kind == "dashscope" else None
                    ),
                )
                openai_messages.append({"role": "system", "content": content_blocks})
            else:
                openai_messages.append({"role": "system", "content": cfg.system})
        for m in messages:
            openai_messages.extend(
                _build_openai_messages(
                    m,
                    include_reasoning_content=include_reasoning_content,
                    require_assistant_reasoning_content=(
                        _requires_assistant_reasoning_content(self._compat, self._model)
                    ),
                    replay_provider_state=self._replay_provider_state,
                )
            )
        if self._provider_kind == "dashscope" and cfg.cache_mode == "on":
            _attach_cache_control_to_latest_text_messages(
                openai_messages,
                max_cache_markers=_DASHSCOPE_MAX_CACHE_MARKERS,
            )
        elif (
            self._provider_kind == "openrouter"
            and cfg.cache_mode in {"auto", "on"}
            and explicit_cache_supported
            and _openrouter_model_uses_alibaba_message_cache(self._model)
        ):
            _attach_cache_control_to_latest_text_messages(
                openai_messages,
                max_cache_markers=_DASHSCOPE_MAX_CACHE_MARKERS,
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self._provider_kind == "dashscope" and include_reasoning_content:
            payload["preserve_thinking"] = True
        if _should_use_max_completion_tokens(
            self._compat,
            self._provider_kind,
            self._base_url,
            self._model,
            cfg,
            caps,
        ):
            payload["max_completion_tokens"] = cfg.max_tokens
        else:
            payload["max_tokens"] = cfg.max_tokens
        if self._compat.sends_usage_include:
            payload["usage"] = {"include": True}
        if self._compat.sends_disable_fallbacks:
            # Gateway proxies must not silently substitute another model:
            # SquillaRouter is the single routing authority.
            payload["disable_fallbacks"] = True
        if (
            self._compat.anthropic_top_level_cache
            and cfg.cache_mode in {"auto", "on"}
            and _openrouter_model_is_anthropic(self._model)
        ):
            payload["cache_control"] = {"type": "ephemeral"}
        if _should_send_temperature(
            self._compat,
            self._base_url,
            self._model,
            cfg,
            caps,
        ):
            payload["temperature"] = cfg.temperature
        if cfg.top_p is not None:
            payload["top_p"] = cfg.top_p
        if cfg.stop_sequences:
            payload["stop"] = cfg.stop_sequences
        if tools:
            payload["tools"] = [
                _build_openai_tool(
                    t,
                    unsupported_keywords=self._compat.tool_schema_unsupported_keywords,
                )
                for t in tools
            ]
            tool_names = [tool.get("function", {}).get("name", "") for tool in payload["tools"]]
            tool_schema_hash = hashlib.sha256(
                json.dumps(payload["tools"], ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
            log.info(
                "provider.request_tool_surface",
                provider=self._provider_kind,
                model=self._model,
                provider_visible_tool_names=tool_names,
                tool_schema_hash=tool_schema_hash,
                temperature=payload.get("temperature"),
                top_p=payload.get("top_p"),
            )
            if _should_send_tool_choice(self._provider_kind, cfg, caps):
                payload["tool_choice"] = cfg.tool_choice
        if self._compat.supports_provider_routing_pin:
            pinned_provider = self._provider_routing.get(self._model)
            if pinned_provider:
                payload["provider"] = {
                    "order": [pinned_provider],
                    "allow_fallbacks": True,
                }

        # Reasoning injection (gated on thinking being enabled). Gating —
        # which model/capability profile triggers a payload at all — lives
        # here; how each dialect spells it lives in reasoning_dialects.
        thinking_toggle_model = (
            self._model.strip().lower() in self._compat.thinking_toggle_model_ids
        )
        if (caps and caps.supports_reasoning and cfg.thinking) or (
            thinking_toggle_model and cfg.thinking
        ):
            reasoning_format = (
                caps.reasoning_format
                if caps is not None
                else self._compat.default_reasoning_format
            )
            apply_reasoning_enable(
                payload,
                reasoning_format,
                ReasoningEnableArgs(
                    thinking_level=cfg.thinking_level,
                    thinking_budget_tokens=cfg.thinking_budget_tokens,
                ),
            )
            if reasoning_format == "dashscope":
                # DashScope thinking budget: the local env override wins;
                # without an explicit per-call budget the field is omitted
                # entirely so the endpoint applies its own default.
                env_thinking_budget = _thinking_budget_tokens_from_env()
                if env_thinking_budget is not None:
                    payload["thinking_budget"] = env_thinking_budget
                elif not cfg.thinking_budget_explicit:
                    payload.pop("thinking_budget", None)
        elif thinking_toggle_model:
            # Toggle models need an explicit off payload even without a
            # capability profile (policy gating, independent of dialect).
            payload["thinking"] = {"type": "disabled"}
        elif caps and caps.supports_reasoning:
            apply_reasoning_disable(
                payload,
                caps.reasoning_format,
                ReasoningDisableArgs(
                    model=self._model,
                    disable_reasoning_by_default_models=(
                        self._compat.disable_reasoning_by_default_models
                    ),
                ),
            )

        if self._provider_kind == "dashscope":
            log.info(
                "provider.qwen_provider_profile",
                provider=self._provider_kind,
                model=self._model,
                endpoint_family=_dashscope_endpoint_family(self._base_url),
                thinking_enabled=bool(payload.get("enable_thinking")),
                thinking_budget=payload.get("thinking_budget"),
                temperature=payload.get("temperature"),
                top_p=payload.get("top_p"),
                cache_mode=cfg.cache_mode,
                text_tool_parser="qwen_tags",
                stream_fallback="non_stream_once",
            )

        fallback_reason = (
            "native_is_error_unavailable"
            if any(message.get("role") == "tool" for message in openai_messages)
            else None
        )
        from opensquilla.engine.context_budget import coordinate_provider_context_budget

        budget_decision = coordinate_provider_context_budget(
            payload,
            projection_adapter=self._provider_kind,
            proof_budget=cfg.provider_request_max_chars,
            status_projection_mode="content_envelope",
            fallback_reason=fallback_reason,
        )
        if budget_decision.action == "budget_limited":
            proof = budget_decision.proof or {}
            log.warning("provider.request_budget_exhausted", **proof)
            yield ErrorEvent(
                message=json.dumps(proof, ensure_ascii=False, sort_keys=True),
                code="provider_request_budget_exhausted",
            )
            return
        payload = budget_decision.payload or payload
        if budget_decision.proof is not None:
            log.info("provider.request_proof", **budget_decision.proof)
        try:
            prove_provider_payload_from_env(
                payload,
                projection_adapter=self._provider_kind,
                status_projection_mode="content_envelope",
                fallback_reason=fallback_reason,
            )
        except ProviderRequestBudgetExceededError as exc:
            log.warning("provider.request_budget_exhausted", **exc.proof)
            yield ErrorEvent(
                message=json.dumps(exc.proof, ensure_ascii=False, sort_keys=True),
                code="provider_request_budget_exhausted",
            )
            return

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        headers.update(openrouter_app_headers(self._base_url))
        if self._org_id:
            headers["OpenAI-Organization"] = self._org_id

        tools_acc = ToolStreamAccumulator()
        # Gemini thought_signature streamed on a non-FC text delta. Kept
        # separate from the tool accumulator (whose keys MUST stay int — see
        # _resolve_tool_call_index's next_int_key) so a str key can never
        # poison the next-index computation with a TypeError.
        streamed_thought_signature: str | None = None
        reasoning = ReasoningAccumulator()
        tools_by_name = _tool_by_name(tools)
        assistant_text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        reasoning_tokens = 0
        cached_tokens = 0
        cache_write_tokens = 0
        billed_cost = 0.0
        cost_source = "none"
        actual_model = self._model
        stop_reason = "stop"
        emitted_stream_event = False

        if os.environ.get("OPENSQUILLA_TRACE_ROUTING"):
            print(
                f"[CALLED] base={self._base_url} model={self._model} "
                f"n_messages={len(openai_messages)}",
                file=sys.stderr,
                flush=True,
            )
        cache_shape = _payload_cache_shape(payload, tools=tools)
        endpoint = self._api_url("/v1/chat/completions")
        trace = LLMTraceRecorder(
            provider=self._provider_kind,
            model=self._model,
            base_url=self._base_url,
            endpoint=endpoint,
            stream=True,
        )
        trace.record_request(
            payload=payload,
            headers=headers,
            metadata={
                "cache_shape": cache_shape,
                "timeout_seconds": cfg.timeout,
                "tools_count": len(tools or []),
                "request_proof": budget_decision.proof,
            },
        )
        if self._compat.log_payload_cache_shape:
            log.debug(
                "openrouter.payload_cache_shape",
                model=self._model,
                **cache_shape,
            )
        elif self._provider_kind == "dashscope":
            log.info(
                "dashscope.payload_cache_shape",
                model=self._model,
                **cache_shape,
            )

        try:
            async with httpx.AsyncClient(
                timeout=(
                    _stream_timeout(cfg.timeout)
                    if self._compat.stream_timeout_fallback
                    else cfg.timeout
                ),
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers=headers,
                    json=payload,
                ) as response:
                    if self._compat.attribution_response_headers:
                        attribution = {
                            name: response.headers[name]
                            for name in self._compat.attribution_response_headers
                            if name in response.headers
                        }
                        if attribution:
                            fallbacks_taken = _coerce_int(
                                attribution.get("x-litellm-attempted-fallbacks")
                            )
                            log_fn = log.warning if fallbacks_taken > 0 else log.info
                            log_fn(
                                "provider.gateway_attribution",
                                provider=self._provider_kind,
                                requested_model=self._model,
                                **{k.replace("-", "_"): v for k, v in attribution.items()},
                            )
                    if response.status_code != 200:
                        body = await response.aread()
                        message = _format_chat_http_error(
                            self._compat.display_name,
                            response.status_code,
                            body,
                        )
                        # Diagnostic: dump payload head (no auth headers)
                        # so 400s from picky upstreams are debuggable. Truncated
                        # to keep memory low.
                        _body_text = (
                            body.decode("utf-8", errors="replace")
                            if isinstance(body, bytes)
                            else str(body)
                        )
                        try:
                            _payload_head = json.dumps(
                                payload,
                                ensure_ascii=False,
                            )[:4000]
                        except Exception:  # noqa: BLE001
                            _payload_head = repr(payload)[:4000]
                        log.warning(
                            "provider.chat_http_error",
                            provider=self._provider_kind,
                            model=self._model,
                            status_code=response.status_code,
                            message=message,
                            response_body=_body_text[:2000],
                            request_payload_head=_payload_head,
                        )
                        trace.record_error(
                            code=str(response.status_code),
                            message=message,
                            status_code=response.status_code,
                            response_body=_body_text,
                            metadata={"cache_shape": cache_shape},
                        )
                        yield ErrorEvent(
                            message=message,
                            code=str(response.status_code),
                            retry_after_s=retry_after_from_headers(
                                response.status_code,
                                getattr(response, "headers", None),
                            ),
                        )
                        return

                    response_ids: set[str] = set()
                    trace_tool_calls: list[dict[str, Any]] = []
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        trace.record_chunk(chunk)
                        chunk_id = chunk.get("id")
                        if isinstance(chunk_id, str) and chunk_id:
                            response_ids.add(chunk_id)
                        chunk_model = chunk.get("model")
                        if chunk_model:
                            actual_model = chunk_model

                        # Usage may appear in the final chunk
                        if chunk.get("usage"):
                            (
                                input_tokens,
                                output_tokens,
                                reasoning_tokens,
                                cached_tokens,
                                cache_write_tokens,
                                raw_billed_cost,
                            ) = _usage_fields(chunk["usage"])
                            billed_cost, cost_source = _provider_billed_cost(
                                self._provider_kind,
                                raw_billed_cost,
                            )
                            _log_provider_cache_usage(
                                provider_kind=self._provider_kind,
                                model=self._model,
                                actual_model=actual_model,
                                input_tokens=input_tokens,
                                cached_tokens=cached_tokens,
                                cache_write_tokens=cache_write_tokens,
                                cache_shape=cache_shape,
                            )

                        for choice in chunk.get("choices", []):
                            finish = choice.get("finish_reason")
                            if finish:
                                stop_reason = finish

                            delta = choice.get("delta", {})

                            # Text content
                            text = delta.get("content")
                            if text:
                                emitted_stream_event = True
                                yield TextDeltaEvent(text=text)
                                assistant_text_parts.append(text)

                            # Reasoning content (always parsed, not gated on thinking).
                            # Streamed in real time as ReasoningDeltaEvent; the
                            # accumulator also retains the joined text for DoneEvent.
                            reasoning_details = delta.get("reasoning_details")
                            if reasoning_details:
                                for detail in reasoning_details:
                                    if isinstance(detail, dict):
                                        reasoning_event = reasoning.emit(detail.get("text", ""))
                                        if reasoning_event is not None:
                                            yield reasoning_event
                            reasoning_event = reasoning.emit(delta.get("reasoning_content"))
                            if reasoning_event is not None:
                                yield reasoning_event

                            # Gemini thought_signature on non-FC deltas
                            # (streamed thinking path): Gemini sends it on
                            # the top-level delta instead of attaching it to
                            # a tool_call. Keep it out of the tool accumulator.
                            ts_delta = delta.get("thought_signature")
                            if isinstance(ts_delta, str) and ts_delta:
                                streamed_thought_signature = ts_delta

                            # Tool calls (may stream over multiple chunks)
                            for tc in delta.get("tool_calls", []):
                                if (
                                    self._provider_kind == "dashscope"
                                    and isinstance(tc, Mapping)
                                    and _dashscope_tool_call_chunk_is_empty(tc)
                                ):
                                    log.warning(
                                        "dashscope.stream_tool_chunk_sanitized",
                                        model=self._model,
                                        reason="empty_tool_call_chunk",
                                    )
                                    continue
                                idx = _resolve_tool_call_index(tc, tools_acc)
                                function = tc.get("function", {}) or {}
                                for tool_event in tools_acc.append_or_start(
                                    idx,
                                    tool_call_id=tc.get("id"),
                                    tool_name=function.get("name", ""),
                                    fragment=function.get("arguments", ""),
                                ):
                                    emitted_stream_event = True
                                    yield tool_event

                                # Gemini thought_signature (OpenAI compat format):
                                # tool_calls[].extra_content.google.thought_signature
                                sig = (
                                    (tc.get("extra_content") or {})
                                    .get("google", {})
                                    .get("thought_signature")
                                )
                                if isinstance(sig, str) and sig:
                                    tools_acc.set_metadata(idx, "thought_signature", sig)

                    # Chat Completions has no per-call stop event: close every
                    # assembled call once the stream ends, running the
                    # provider-aware argument parser (including the DashScope
                    # JSON repair) over the accumulated raw fragments first.
                    for key, tool_use_id, tool_name, raw_arguments in (
                        tools_acc.pending_raw_arguments()
                    ):
                        args, arguments_valid, arguments_repaired = _parse_openai_tool_arguments(
                            provider_kind=self._provider_kind,
                            model=self._model,
                            tool_name=tool_name,
                            tool_use_id=tool_use_id,
                            raw_text=raw_arguments,
                            tools_by_name=tools_by_name,
                        )
                        trace_tool_calls.append(
                            {
                                "id": tool_use_id,
                                "name": tool_name,
                                "arguments_raw": raw_arguments,
                                "arguments_json_valid": arguments_valid,
                                "arguments_json_repaired": arguments_repaired,
                                "arguments": args,
                            }
                        )
                        for tool_event in tools_acc.finish_with_arguments(key, args):
                            emitted_stream_event = True
                            yield tool_event

                    # Last-resort MiniMax compatibility: some OpenRouter
                    # upstreams leak native MiniMax XML tool calls as text
                    # instead of structured tool_calls. Only synthesize calls
                    # for provider kinds known to leak the text protocol, when
                    # no structured calls arrived, tools were offered, and the
                    # parsed tool name is explicitly allowed by this turn.
                    if (
                        not tools_acc.has_calls
                        and tools
                        and assistant_text_parts
                        and self._compat.text_tool_synthesis
                    ):
                        full_text = "".join(assistant_text_parts)
                        for event in _synthesize_text_tool_events(
                            full_text,
                            tools,
                            provider_kind=self._provider_kind,
                            model=self._model,
                        ):
                            emitted_stream_event = True
                            yield event

                    # Assemble reasoning from the structured fields already
                    # streamed in real time via ReasoningDeltaEvent.
                    reasoning_text = reasoning.finalize()

                    # Fallback: <think> tag extraction from accumulated text.
                    # This format embeds reasoning inside the answer text, so it
                    # can only be recovered after the full text arrives — it is
                    # inherently non-streamable and stays a turn-end assembly.
                    caps = cfg.model_capabilities
                    if not reasoning_text and caps and caps.reasoning_format == "think_tags":
                        full_text = "".join(assistant_text_parts)
                        reasoning_text = _extract_think_tags(full_text) or None

                    # Gemini thought_signature: extract from the first tool call
                    # that carries one (Gemini attaches it to the first FC only).
                    # Fallback: when Gemini streams the signature on a non-FC
                    # text delta (no tool_call carries it), use the streamed one.
                    gemini_thought_sig = cast(
                        "str | None",
                        tools_acc.first_metadata("thought_signature"),
                    )
                    if gemini_thought_sig is None:
                        gemini_thought_sig = streamed_thought_signature

                    trace.record_response(
                        usage={
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "reasoning_tokens": reasoning_tokens,
                            "cached_tokens": cached_tokens,
                            "cache_write_tokens": cache_write_tokens,
                            "billed_cost": billed_cost,
                            "cost_source": cost_source,
                        },
                        stop_reason=stop_reason,
                        actual_model=actual_model,
                        assistant_text="".join(assistant_text_parts),
                        reasoning_content=reasoning_text or None,
                        tool_calls=trace_tool_calls,
                        response_ids=sorted(response_ids),
                        metadata={"cache_shape": cache_shape},
                    )
                    yield DoneEvent(
                        stop_reason=stop_reason,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_content=reasoning_text or None,
                        thinking_signature=gemini_thought_sig,
                        reasoning_tokens=reasoning_tokens,
                        cached_tokens=cached_tokens,
                        cache_write_tokens=cache_write_tokens,
                        billed_cost=billed_cost,
                        model=actual_model,
                        cost_source=cost_source,
                    )

        except httpx.TimeoutException as exc:
            trace.record_error(
                code="timeout",
                message=f"Request timed out: {exc}",
                metadata={"phase": "stream", "cache_shape": cache_shape},
            )
            if self._compat.stream_timeout_fallback and not emitted_stream_event:
                event_name = (
                    "openrouter.stream_timeout_fallback_started"
                    if self._provider_kind == "openrouter"
                    else "dashscope.non_stream_fallback_started"
                )
                log.warning(
                    event_name,
                    model=self._model,
                    timeout_seconds=cfg.timeout,
                    timeout_phase=type(exc).__name__,
                    error=str(exc) or repr(exc),
                )
                yield ProviderHeartbeatEvent(
                    phase="llm_fallback",
                    message=(
                        f"{_provider_display_name(self._provider_kind)} stream timed out; "
                        "retrying without streaming."
                    ),
                )
                try:
                    async for fallback_event in self._complete_non_stream(
                        payload=payload,
                        headers=headers,
                        cfg=cfg,
                        tools=tools,
                        timeout_exc=exc,
                    ):
                        yield fallback_event
                except Exception as fallback_exc:  # noqa: BLE001 - see contract note below
                    log.exception(
                        "provider.stream_internal_error",
                        provider=self._provider_kind,
                        model=self._model,
                    )
                    yield ErrorEvent(
                        message=f"Provider response handling failed: {fallback_exc}",
                        code="provider_internal",
                    )
                return
            yield ErrorEvent(message=f"Request timed out: {exc}", code="timeout")
        except httpx.RequestError as exc:
            trace.record_error(
                code="request_error",
                message=f"Request error: {exc}",
                metadata={"phase": "stream", "cache_shape": cache_shape},
            )
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")
        except Exception as exc:  # noqa: BLE001 - chat() contract: ErrorEvent instead of raising
            log.exception(
                "provider.stream_internal_error",
                provider=self._provider_kind,
                model=self._model,
            )
            yield ErrorEvent(
                message=f"Provider response handling failed: {exc}",
                code="provider_internal",
            )

    async def _complete_non_stream(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
        cfg: ChatConfig,
        tools: list[ToolDefinition] | None,
        timeout_exc: httpx.TimeoutException,
    ) -> AsyncIterator[StreamEvent]:
        fallback_payload = dict(payload)
        fallback_payload["stream"] = False
        fallback_payload.pop("stream_options", None)
        cache_shape = _payload_cache_shape(fallback_payload, tools=tools)
        fallback_headers = dict(headers)
        fallback_headers["Accept"] = "application/json"
        endpoint = self._api_url("/v1/chat/completions")
        trace = LLMTraceRecorder(
            provider=self._provider_kind,
            model=self._model,
            base_url=self._base_url,
            endpoint=endpoint,
            stream=False,
        )
        trace.record_request(
            payload=fallback_payload,
            headers=fallback_headers,
            metadata={
                "cache_shape": cache_shape,
                "timeout_seconds": cfg.timeout,
                "tools_count": len(tools or []),
                "fallback_from": "stream_timeout",
                "stream_error": str(timeout_exc),
            },
        )

        try:
            async with httpx.AsyncClient(
                timeout=cfg.timeout,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers=fallback_headers,
                    json=fallback_payload,
                )
        except httpx.TimeoutException:
            log.warning(
                "openrouter.non_stream_fallback_timeout",
                model=self._model,
                timeout_seconds=cfg.timeout,
                stream_error=str(timeout_exc),
            )
            trace.record_error(
                code="timeout",
                message=f"Request timed out: {timeout_exc}",
                metadata={"phase": "non_stream_fallback", "cache_shape": cache_shape},
            )
            yield ErrorEvent(message=f"Request timed out: {timeout_exc}", code="timeout")
            return
        except httpx.RequestError as exc:
            trace.record_error(
                code="request_error",
                message=f"Request error: {exc}",
                metadata={"phase": "non_stream_fallback", "cache_shape": cache_shape},
            )
            yield ErrorEvent(message=f"Request error: {exc}", code="request_error")
            return

        if response.status_code != 200:
            trace.record_error(
                code=str(response.status_code),
                message=_format_chat_http_error(
                    self._compat.display_name,
                    response.status_code,
                    response.text,
                ),
                status_code=response.status_code,
                response_body=response.text,
                metadata={"cache_shape": cache_shape},
            )
            yield ErrorEvent(
                message=_format_chat_http_error(
                    self._compat.display_name,
                    response.status_code,
                    response.text,
                ),
                code=str(response.status_code),
                retry_after_s=retry_after_from_headers(
                    response.status_code,
                    getattr(response, "headers", None),
                ),
            )
            return

        try:
            data = response.json()
        except json.JSONDecodeError:
            trace.record_error(
                code="invalid_json",
                message="Invalid JSON response from provider",
                response_body=response.text,
                metadata={"cache_shape": cache_shape},
            )
            yield ErrorEvent(message="Invalid JSON response from provider", code="invalid_json")
            return

        actual_model = data.get("model") or self._model
        (
            input_tokens,
            output_tokens,
            reasoning_tokens,
            cached_tokens,
            cache_write_tokens,
            raw_billed_cost,
        ) = _usage_fields(data.get("usage"))
        billed_cost, cost_source = _provider_billed_cost(self._provider_kind, raw_billed_cost)
        _log_provider_cache_usage(
            provider_kind=self._provider_kind,
            model=self._model,
            actual_model=actual_model,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_shape=cache_shape,
        )
        stop_reason = "stop"
        assistant_text_parts: list[str] = []
        reasoning = ReasoningAccumulator()
        tools_acc = ToolStreamAccumulator()
        trace_tool_calls: list[dict[str, Any]] = []
        tools_by_name = _tool_by_name(tools)

        for choice in data.get("choices", []):
            if choice.get("finish_reason"):
                stop_reason = choice["finish_reason"]
            message = choice.get("message") or {}

            text = message.get("content")
            if isinstance(text, str) and text:
                assistant_text_parts.append(text)
                yield TextDeltaEvent(text=text)

            reasoning_details = message.get("reasoning_details")
            if reasoning_details:
                for detail in reasoning_details:
                    if isinstance(detail, dict):
                        reasoning_event = reasoning.emit(detail.get("text", ""))
                        if reasoning_event is not None:
                            yield reasoning_event
            for key in ("reasoning_content", "reasoning"):
                reasoning_str = message.get(key)
                if isinstance(reasoning_str, str):
                    reasoning_event = reasoning.emit(reasoning_str)
                    if reasoning_event is not None:
                        yield reasoning_event

            for tc in message.get("tool_calls") or []:
                function = tc.get("function") or {}
                tool_use_id = tc.get("id") or f"call_{uuid4().hex[:12]}"
                tool_name = function.get("name") or ""
                call_key = tools_acc.next_int_key()
                for tool_event in tools_acc.start(
                    call_key,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                ):
                    yield tool_event
                arguments_text = function.get("arguments") or ""
                if arguments_text:
                    for tool_event in tools_acc.append(call_key, arguments_text):
                        yield tool_event
                sig = (tc.get("extra_content") or {}).get("google", {}).get("thought_signature")
                if isinstance(sig, str) and sig:
                    tools_acc.set_metadata(call_key, "thought_signature", sig)
                arguments, arguments_valid, arguments_repaired = _parse_openai_tool_arguments(
                    provider_kind=self._provider_kind,
                    model=self._model,
                    tool_name=tool_name,
                    tool_use_id=tool_use_id,
                    raw_text=arguments_text,
                    tools_by_name=tools_by_name,
                )
                trace_tool_calls.append(
                    {
                        "id": tool_use_id,
                        "name": tool_name,
                        "arguments_raw": arguments_text,
                        "arguments_json_valid": arguments_valid,
                        "arguments_json_repaired": arguments_repaired,
                        "arguments": arguments,
                    }
                )
                for tool_event in tools_acc.finish_with_arguments(call_key, arguments):
                    yield tool_event

        if (
            not tools_acc.has_calls
            and tools
            and assistant_text_parts
            and self._compat.text_tool_synthesis
        ):
            for event in _synthesize_text_tool_events(
                "".join(assistant_text_parts),
                tools,
                provider_kind=self._provider_kind,
                model=self._model,
            ):
                yield event

        reasoning_text = reasoning.finalize()
        if (
            not reasoning_text
            and cfg.model_capabilities
            and cfg.model_capabilities.reasoning_format == "think_tags"
        ):
            reasoning_text = _extract_think_tags("".join(assistant_text_parts)) or None

        trace.record_response(
            response=data,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "cached_tokens": cached_tokens,
                "cache_write_tokens": cache_write_tokens,
                "billed_cost": billed_cost,
                "cost_source": cost_source,
            },
            stop_reason=stop_reason,
            actual_model=actual_model,
            assistant_text="".join(assistant_text_parts),
            reasoning_content=reasoning_text or None,
            tool_calls=trace_tool_calls,
            response_ids=[str(data["id"])] if data.get("id") else [],
            metadata={"cache_shape": cache_shape},
        )
        yield DoneEvent(
            stop_reason=stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_content=reasoning_text or None,
            thinking_signature=cast(
                "str | None",
                tools_acc.first_metadata("thought_signature"),
            ),
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            billed_cost=billed_cost,
            model=actual_model,
            cost_source=cost_source,
        )

    async def list_models(self, *, raise_on_error: bool = False) -> list[ModelInfo]:
        """List available models.

        By default any auth/transport failure degrades to an empty list (the
        historical contract every runtime caller relies on). Pass
        ``raise_on_error=True`` to surface the underlying exception instead,
        so callers that must distinguish a wrong key from an empty catalog
        (e.g. onboarding discovery) can classify it.
        """
        headers = {"Authorization": f"Bearer {self._api_key}"}
        headers.update(openrouter_app_headers(self._base_url))
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                trust_env=_trust_env(),
                proxy=self._proxy,
            ) as client:
                resp = await client.get(self._api_url("/v1/models"), headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return [
                    ModelInfo(
                        provider=self._provider_kind,
                        model_id=m["id"],
                        display_name=m.get("name", m.get("id", "")),
                        context_window=m.get("context_length", 0),
                        max_output_tokens=(m.get("top_provider") or {}).get("max_completion_tokens")
                        or 0,
                    )
                    for m in data.get("data", [])
                ]
        except Exception:
            if raise_on_error:
                raise
            return []
