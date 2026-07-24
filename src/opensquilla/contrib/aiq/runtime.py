"""Lazy AIQ-repo runtime for the bridge tools.

Nothing here imports AIQ code at module-import time. The preferred remote
backend calls AIQ's authenticated MCP endpoint, preserving server-side schema,
authorization, and user identity without importing the OpenAI Agents SDK into
OpenSquilla. The local development fallback resolves the configured AIQ repo,
imports the tool module, and dispatches through ``FunctionTool.on_invoke_tool``.

Every unavailability mode (missing repo, missing AIQ dependencies, missing
Snowflake/Neo4j/API credentials) degrades to :class:`SafeToolError`, which the
dispatch pipeline converts into the standard five-key failure envelope.

Configuration (see ``opensquilla.toml.example``):

- ``AIQ_REPO_PATH`` env var, else ``[aiq] repo_path`` in the gateway TOML,
  else :data:`DEFAULT_REPO_PATH`.
- ``AIQ_USER_EMAIL`` env var, else ``[aiq] user_email`` — identity used for
  AIQ's per-user entitlement gates (e.g. MarketAxess CP+ authorisation).
- ``AIQ_MCP_URL`` env var, else ``[aiq] mcp_url`` — when set, use the
  provider-neutral MCP backend instead of importing AIQ locally.
- ``AIQ_MCP_BEARER_TOKEN`` — authenticated AIQ JWT for the MCP connection.
  It is intentionally environment-only and is never read from TOML.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tomllib
from importlib import import_module
from pathlib import Path
from typing import Any

import structlog

from opensquilla.tools.types import SafeToolError

log = structlog.get_logger(__name__)

DEFAULT_REPO_PATH = "/Users/alexandernanda/Desktop/cutedsl/aiq"
DEFAULT_MCP_TIMEOUT_SECONDS = 75.0

_mcp_client: Any | None = None
_mcp_connection_key: str | None = None
_mcp_connect_lock = asyncio.Lock()

_UNAVAILABLE_MESSAGE = (
    "The AIQ tool bridge is not available: {reason} Configure [aiq] repo_path in "
    "the gateway TOML (or the AIQ_REPO_PATH env var) to a checkout of the AIQ "
    "repo with its dependencies installed. Live market data additionally "
    "requires AIQ's own credentials (Snowflake, Neo4j, FRED, ...)."
)


def _gateway_toml_path() -> Path | None:
    """Mirror the gateway config load order for the raw TOML document."""

    override = os.environ.get("OPENSQUILLA_GATEWAY_CONFIG_PATH", "").strip()
    candidates = [Path(override)] if override else []
    candidates.append(Path.cwd() / "opensquilla.toml")
    home = os.environ.get("OPENSQUILLA_STATE_DIR", "").strip()
    base = Path(home) if home else Path.home() / ".opensquilla"
    candidates.append(base / "config.toml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _aiq_config_section() -> dict[str, Any]:
    path = _gateway_toml_path()
    if path is None:
        return {}
    try:
        with path.open("rb") as fh:
            document = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("contrib_aiq.config_read_failed", path=str(path), error=str(exc))
        return {}
    section = document.get("aiq")
    return section if isinstance(section, dict) else {}


def resolve_repo_path() -> Path:
    """AIQ repo path: ``AIQ_REPO_PATH`` env > ``[aiq] repo_path`` > default."""

    env_value = os.environ.get("AIQ_REPO_PATH", "").strip()
    if env_value:
        return Path(env_value).expanduser()
    config_value = str(_aiq_config_section().get("repo_path", "") or "").strip()
    if config_value:
        return Path(config_value).expanduser()
    return Path(DEFAULT_REPO_PATH)


def resolve_user_email() -> str:
    """Identity for AIQ per-user gates: env > ``[aiq] user_email`` > anonymous."""

    env_value = os.environ.get("AIQ_USER_EMAIL", "").strip()
    if env_value:
        return env_value
    return str(_aiq_config_section().get("user_email", "") or "").strip()


def resolve_mcp_url() -> str:
    """Remote AIQ MCP SSE URL; an empty string selects the local bridge."""

    env_value = os.environ.get("AIQ_MCP_URL", "").strip()
    if env_value:
        return env_value
    return str(_aiq_config_section().get("mcp_url", "") or "").strip()


def _resolve_mcp_bearer_token() -> str:
    """MCP credentials are environment-only so they never enter gateway TOML."""

    return os.environ.get("AIQ_MCP_BEARER_TOKEN", "").strip()


def _mcp_timeout_seconds() -> float:
    raw = os.environ.get("AIQ_MCP_TOOL_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_MCP_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise SafeToolError(
            "AIQ_MCP_TOOL_TIMEOUT_SECONDS must be a positive number."
        ) from exc
    if value <= 0:
        raise SafeToolError("AIQ_MCP_TOOL_TIMEOUT_SECONDS must be positive.")
    return value


async def _close_mcp_client_unlocked() -> None:
    global _mcp_client, _mcp_connection_key

    client, _mcp_client = _mcp_client, None
    _mcp_connection_key = None
    if client is not None:
        try:
            await client.close()
        except Exception:  # noqa: BLE001 - best-effort connection cleanup
            pass


async def close_aiq_mcp_client() -> None:
    """Close the cached remote AIQ connection (gateway/tests shutdown hook)."""

    async with _mcp_connect_lock:
        await _close_mcp_client_unlocked()


async def _get_aiq_mcp_client() -> Any:
    """Return one authenticated, reusable MCP client for the configured URL."""

    global _mcp_client, _mcp_connection_key

    url = resolve_mcp_url()
    token = _resolve_mcp_bearer_token()
    if not url:
        raise SafeToolError("AIQ MCP URL is not configured.")
    if not token:
        raise SafeToolError(
            "AIQ MCP is configured but AIQ_MCP_BEARER_TOKEN is missing."
        )
    connection_key = hashlib.sha256(f"{url}\0{token}".encode()).hexdigest()
    if _mcp_client is not None and _mcp_connection_key == connection_key:
        return _mcp_client

    async with _mcp_connect_lock:
        if _mcp_client is not None and _mcp_connection_key == connection_key:
            return _mcp_client
        await _close_mcp_client_unlocked()
        from opensquilla.mcp.sse import MCPSSEClient
        from opensquilla.mcp.types import MCPServerConfig

        client = MCPSSEClient(
            MCPServerConfig(
                name="aiq",
                transport="sse",
                url=url,
                headers={"Authorization": f"Bearer {token}"},
                tool_timeout_seconds=_mcp_timeout_seconds(),
            )
        )
        try:
            await client.connect()
        except Exception as exc:
            await client.close()
            raise SafeToolError(
                "The remote AIQ MCP tool service is unavailable. Verify the "
                "endpoint and refresh AIQ_MCP_BEARER_TOKEN."
            ) from exc
        _mcp_client = client
        _mcp_connection_key = connection_key
        return client


def _ensure_repo_on_path() -> Path:
    repo = resolve_repo_path()
    if not (repo / "lib" / "tools").is_dir():
        raise SafeToolError(
            _UNAVAILABLE_MESSAGE.format(
                reason=f"no AIQ repo found at {repo} (missing lib/tools).",
            )
        )
    repo_str = str(repo)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    return repo


def _load_function_tool(module_name: str, attr: str) -> Any:
    _ensure_repo_on_path()
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise SafeToolError(
            _UNAVAILABLE_MESSAGE.format(
                reason=f"importing {module_name} failed ({exc.name or exc}).",
            )
        ) from exc
    tool = getattr(module, attr, None)
    if tool is None or not hasattr(tool, "on_invoke_tool"):
        raise SafeToolError(
            f"AIQ tool {attr!r} was not found in {module_name} — the configured "
            "AIQ checkout may be older or newer than this bridge."
        )
    return tool


def _make_aiq_tool_context(tool_name: str, args_json: str) -> Any:
    """Minimal OpenAI Agents SDK ToolContext carrying a HumanUserProfile."""

    try:
        from agents.tool_context import ToolContext as AiqToolContext  # AIQ dependency
        from lib.agents.human_user_profile import HumanUserProfile  # AIQ repo
    except ImportError as exc:
        raise SafeToolError(
            _UNAVAILABLE_MESSAGE.format(
                reason=f"the AIQ runtime dependencies are incomplete ({exc}).",
            )
        ) from exc

    email = resolve_user_email()
    try:
        profile = HumanUserProfile(email=email)
    except ValueError:
        log.warning("contrib_aiq.invalid_user_email", email=email)
        profile = HumanUserProfile()
    return AiqToolContext(
        context=profile,
        tool_name=tool_name,
        tool_call_id="opensquilla-bridge",
        tool_arguments=args_json,
    )


def _sanitize_arguments(arguments: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Drop empty optional values so AIQ tool defaults apply.

    Models routinely send ``""``/``null`` for optional parameters; AIQ's own
    adapter treats empty strings as unset, and omitting the key entirely lets
    the tool's declared default take over.
    """

    return {
        key: value
        for key, value in arguments.items()
        if key in required or (value is not None and value != "")
    }


async def invoke_aiq_tool(
    name: str,
    module_name: str,
    attr: str,
    arguments: dict[str, Any],
    required: list[str],
) -> str:
    """Invoke one AIQ tool through MCP or the local FunctionTool fallback."""

    sanitized = _sanitize_arguments(arguments, required)
    if resolve_mcp_url():
        client = await _get_aiq_mcp_client()
        try:
            result = await client.call_tool(name, sanitized)
        except Exception as exc:
            # Drop a broken session so the next request can reconnect with a
            # refreshed JWT rather than reusing a poisoned transport.
            await close_aiq_mcp_client()
            raise SafeToolError(
                "The remote AIQ MCP tool call failed. Retry after refreshing "
                "AIQ_MCP_BEARER_TOKEN if it expired."
            ) from exc
        if result.is_error:
            raise SafeToolError(result.content or f"AIQ MCP tool {name!r} failed.")
        return result.content

    tool = _load_function_tool(module_name, attr)
    args_json = json.dumps(sanitized)
    ctx = _make_aiq_tool_context(name, args_json)
    result = await tool.on_invoke_tool(ctx=ctx, input=args_json)
    if isinstance(result, str):
        return result
    return json.dumps(result)
