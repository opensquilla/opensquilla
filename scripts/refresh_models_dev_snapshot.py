"""Refresh the vendored models.dev snapshot used by the model catalog.

Fetches https://models.dev/api.json (MIT-licensed, community-maintained),
trims it to the providers OpenSquilla registers, and writes the compact
snapshot consumed by ``opensquilla.provider.models_dev``.

Usage::

    uv run python scripts/refresh_models_dev_snapshot.py

Review the diff before committing — the snapshot is deliberately small and
human-reviewable so upstream data mistakes are caught at refresh time, not
at runtime.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx

API_URL = "https://models.dev/api.json"
SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "opensquilla"
    / "provider"
    / "models_dev_snapshot.json"
)

# OpenSquilla provider id -> models.dev provider ids (merged in order; the
# first source of a model id wins).
PROVIDER_SOURCES: dict[str, tuple[str, ...]] = {
    "openrouter": ("openrouter",),
    "openai": ("openai",),
    "openai_responses": ("openai",),
    "anthropic": ("anthropic",),
    "deepseek": ("deepseek",),
    "gemini": ("google",),
    "dashscope": ("alibaba-cn", "alibaba"),
    "bailian_coding": ("alibaba", "alibaba-cn"),
    "moonshot": ("moonshotai",),
    "zhipu": ("zhipuai", "zai"),
    "minimax": ("minimax",),
    "minimax_openai": ("minimax",),
    "minimax_cn": ("minimax",),
    "minimax_global": ("minimax",),
    "mistral": ("mistral",),
    "groq": ("groq",),
    "siliconflow": ("siliconflow",),
    "volcengine": ("volcengine",),
    "byteplus": ("byteplus",),
    "qianfan": ("qianfan", "baidu"),
    "azure": ("azure",),
}


def _trim_model(entry: dict) -> dict | None:
    limit = entry.get("limit") or {}
    context = int(limit.get("context") or 0)
    output = int(limit.get("output") or 0)
    if context <= 0 and output <= 0:
        return None
    # Self-contradictory upstream data (context smaller than max output —
    # e.g. models.dev's openrouter z-ai/glm-5.1 entry) would poison budget
    # resolution; drop it so lookups fall through to a consistent layer.
    if 0 < context < output:
        return None
    modalities = entry.get("modalities") or {}
    inputs = {str(item).lower() for item in modalities.get("input") or []}
    return {
        "ctx": context,
        "out": output,
        "reasoning": bool(entry.get("reasoning")),
        "tools": bool(entry.get("tool_call")),
        "vision": "image" in inputs,
    }


def main() -> int:
    data = httpx.get(API_URL, timeout=30.0, follow_redirects=True).json()
    providers: dict[str, dict[str, dict]] = {}
    for osq_id, sources in PROVIDER_SOURCES.items():
        table: dict[str, dict] = {}
        for source in sources:
            models = (data.get(source) or {}).get("models") or {}
            for model_id, entry in models.items():
                key = str(model_id).strip().lower()
                if key in table:
                    continue
                trimmed = _trim_model(entry)
                if trimmed is not None:
                    table[key] = trimmed
        if table:
            providers[osq_id] = dict(sorted(table.items()))

    snapshot = {
        "_source": API_URL,
        "_license": "MIT (models.dev, maintained by the SST team)",
        "_fetched": date.today().isoformat(),
        "providers": providers,
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=1, sort_keys=False) + "\n")
    total = sum(len(models) for models in providers.values())
    print(f"wrote {SNAPSHOT_PATH} ({len(providers)} providers, {total} models)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
