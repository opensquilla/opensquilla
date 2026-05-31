"""Query multiple search engines and emit a normalized JSON result list."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; OpenSquilla-multi-search-engine/0.1)"
)
TIMEOUT_S = 8.0


@dataclass
class Result:
    engine: str
    title: str
    url: str
    snippet: str
    rank: int


@dataclass
class EngineError:
    engine: str
    reason: str


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"},
        follow_redirects=True,
        timeout=TIMEOUT_S,
    )


def _ddg_search(query: str, limit: int) -> list[Result]:
    with _client() as client:
        response = client.post("https://html.duckduckgo.com/html/", data={"q": query})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[Result] = []
        for idx, item in enumerate(soup.select("div.result")[:limit], start=1):
            title_el = item.select_one("a.result__a")
            snippet_el = item.select_one("a.result__snippet")
            if title_el is None:
                continue
            results.append(
                Result(
                    engine="duckduckgo",
                    title=title_el.get_text(strip=True),
                    url=title_el.get("href", ""),
                    snippet=snippet_el.get_text(strip=True) if snippet_el is not None else "",
                    rank=idx,
                )
            )
        return results


_BRAVE_MAX_COUNT = 20  # Brave Web Search API hard-caps `count` at 20; >20 → HTTP 422.


def _brave_search(query: str, limit: int) -> list[Result]:
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("BRAVE_API_KEY")
    if not api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY/BRAVE_API_KEY not set; skipping")
    effective_count = min(max(limit, 1), _BRAVE_MAX_COUNT)
    if limit > _BRAVE_MAX_COUNT:
        print(
            f"[multi-search-engine] brave count clamped {limit}→{_BRAVE_MAX_COUNT} "
            f"(API hard-cap)",
            file=sys.stderr,
        )
    with _client() as client:
        response = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": effective_count},
            headers={"X-Subscription-Token": api_key},
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("web", {}).get("results", []) or []
        results: list[Result] = []
        for idx, item in enumerate(items[:limit], start=1):
            results.append(
                Result(
                    engine="brave",
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    rank=idx,
                )
            )
        return results


def _tavily_search(query: str, limit: int) -> list[Result]:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set; skipping")
    with _client() as client:
        response = client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": limit,
            },
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("results", []) or []
        results: list[Result] = []
        for idx, item in enumerate(items[:limit], start=1):
            results.append(
                Result(
                    engine="tavily",
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    rank=idx,
                )
            )
        return results


ENGINES: dict[str, Callable[[str, int], list[Result]]] = {
    "duckduckgo": _ddg_search,
    "brave": _brave_search,
    "tavily": _tavily_search,
}


def _normalize_query(query: str) -> str:
    """Extract the actual web query from structured planner output."""
    lines = [line.strip() for line in query.splitlines() if line.strip()]
    for line in lines:
        if line.upper().startswith("SEARCH_QUERY:"):
            extracted = line.split(":", 1)[1].strip()
            if extracted:
                return extracted
    return query.strip()


def search_all(
    query: str,
    engines: list[str],
    limit: int,
    strict: bool,
) -> dict[str, object]:
    normalized_query = _normalize_query(query)
    results: list[dict[str, object]] = []
    errors: list[EngineError] = []
    handlers: list[tuple[str, Callable[[str, int], list[Result]] | None, str | None]] = []
    for name in engines:
        handler = ENGINES.get(name)
        if handler is None:
            handlers.append((name, None, "unknown engine"))
            if strict:
                break
            continue
        handlers.append((name, handler, None))

    def _run_engine(handler: Callable[[str, int], list[Result]]) -> list[Result]:
        return handler(normalized_query, limit)

    max_workers = max(1, len(handlers))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            name: executor.submit(_run_engine, handler)
            for name, handler, known_error in handlers
            if handler is not None and known_error is None
        }

        for name, _handler, known_error in handlers:
            if known_error is not None:
                errors.append(EngineError(name, known_error))
                if strict:
                    break
                continue
            try:
                engine_results = futures[name].result()
            except Exception as exc:  # network, key missing, parser breaks — keep going
                errors.append(EngineError(name, str(exc)))
                if strict:
                    break
                continue
            for r in engine_results:
                results.append(r.__dict__)
    return {
        "query": normalized_query,
        "results": results,
        "errors": [e.__dict__ for e in errors],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-engine web search.")
    parser.add_argument("--query", required=True)
    parser.add_argument(
        "--engines",
        default="duckduckgo",
        help="Comma-separated engine list (duckduckgo,brave,tavily)",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--strict", action="store_true", help="Fail on first engine error")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="(default; kept for clarity)")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    payload = search_all(args.query, engines, args.limit, args.strict)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
