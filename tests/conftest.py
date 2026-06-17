from __future__ import annotations

import builtins
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PYTEST_STATE_ROOT = Path(tempfile.gettempdir()) / f"opensquilla-pytest-{os.getpid()}"

os.environ.setdefault("OPENSQUILLA_STATE_DIR", str(_PYTEST_STATE_ROOT / "state"))
os.environ.setdefault("OPENSQUILLA_LOG_DIR", str(_PYTEST_STATE_ROOT / "logs"))
os.environ.setdefault("OPENSQUILLA_TURN_CALL_LOG", "0")

_REAL_OPEN = builtins.open
_REAL_PATH_READ_TEXT = Path.read_text


def _utf8_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    if "b" not in mode and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    return _REAL_OPEN(file, mode, *args, **kwargs)


def _utf8_path_read_text(
    self: Path,
    encoding: str | None = None,
    errors: str | None = None,
) -> str:
    return _REAL_PATH_READ_TEXT(self, encoding=encoding or "utf-8", errors=errors)


builtins.open = _utf8_open  # type: ignore[assignment]
Path.read_text = _utf8_path_read_text  # type: ignore[assignment]

_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "BRAVE_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)

_LIVE_MARKERS = (
    "llm",
    "llm_smoke",
    "llm_costly",
    "llm_tools",
    "llm_embedding",
    "llm_reasoning",
    "llm_gateway",
    "llm_image",
    "llm_router_acc",
    "live_channel",
)


@pytest.fixture(autouse=True)
def _isolate_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Keep default tests offline even when the developer shell has API keys."""
    if any(request.node.get_closest_marker(marker) for marker in _LIVE_MARKERS):
        return
    for env_key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(env_key, raising=False)
