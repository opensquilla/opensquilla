"""Lazy AIQ-repo runtime for the bridge tools.

Nothing here imports AIQ code at module-import time. When a bridged tool is
actually called, :func:`invoke_aiq_tool` resolves the configured AIQ repo
path, inserts it on ``sys.path``, imports the tool's module, and dispatches
through the OpenAI Agents SDK ``FunctionTool.on_invoke_tool`` seam — the same
entry point AIQ's own runtime uses, so each tool's argument parsing and
per-user entitlement gates stay intact.

Every unavailability mode (missing repo, missing AIQ dependencies, missing
Snowflake/Neo4j/API credentials) degrades to :class:`SafeToolError`, which the
dispatch pipeline converts into the standard five-key failure envelope.

Configuration (see ``opensquilla.toml.example``):

- ``AIQ_REPO_PATH`` env var, else ``[aiq] repo_path`` in the gateway TOML,
  else :data:`DEFAULT_REPO_PATH`.
- ``AIQ_USER_EMAIL`` env var, else ``[aiq] user_email`` — identity used for
  AIQ's per-user entitlement gates (e.g. MarketAxess CP+ authorisation).
"""

from __future__ import annotations

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
    """Invoke one AIQ FunctionTool and return its string payload."""

    tool = _load_function_tool(module_name, attr)
    args_json = json.dumps(_sanitize_arguments(arguments, required))
    ctx = _make_aiq_tool_context(name, args_json)
    result = await tool.on_invoke_tool(ctx=ctx, input=args_json)
    if isinstance(result, str):
        return result
    return json.dumps(result)
