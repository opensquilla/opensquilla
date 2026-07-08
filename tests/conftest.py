from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PYTEST_STATE_ROOT = Path(tempfile.gettempdir()) / f"opensquilla-pytest-{os.getpid()}"

os.environ.setdefault("OPENSQUILLA_STATE_DIR", str(_PYTEST_STATE_ROOT / "state"))
os.environ.setdefault("OPENSQUILLA_LOG_DIR", str(_PYTEST_STATE_ROOT / "logs"))
os.environ.setdefault("OPENSQUILLA_TURN_CALL_LOG", "0")

_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ARK_API_KEY",
    "BOCHA_SEARCH_API_KEY",
    "BRAVE_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "BYTEPLUS_API_KEY",
    "DEEPSEEK_API_KEY",
    "EXA_API_KEY",
    "FIRECRAWL_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "IQS_SEARCH_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TAVILY_API_KEY",
    "TENCENT_TOKEN_PLAN_API_KEY",
    "TENCENT_TOKENHUB_API_KEY",
    "TENCENT_TOKENHUB_INTL_API_KEY",
    "VOLCENGINE_API_KEY",
    "VOLC_ARK_API_KEY",
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
    "live_search",
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
