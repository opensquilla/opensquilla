from __future__ import annotations

import httpx
import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.search.providers.brave import BraveSearchProvider
from opensquilla.search.providers.duckduckgo import DuckDuckGoProvider
from opensquilla.search.types import SearchResult
from opensquilla.tools.builtin import web


def test_gateway_config_accepts_search_api_key() -> None:
    config = GatewayConfig(search_api_key="brave-test-key")

    assert config.search_api_key == "brave-test-key"


def test_brave_provider_prefers_explicit_api_key(monkeypatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    provider = BraveSearchProvider(api_key="brave-test-key")

    assert provider._api_key == "brave-test-key"


def test_brave_provider_strips_trailing_paste_punctuation(monkeypatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    provider = BraveSearchProvider(api_key="brave-test-key、")

    assert provider._api_key == "brave-test-key"


def test_web_search_kwargs_pass_brave_api_key() -> None:
    web.configure_search("brave", api_key="brave-test-key")

    assert web._search_provider_kwargs("brave")["api_key"] == "brave-test-key"


def test_web_search_kwargs_pass_tavily_api_key() -> None:
    web.configure_search("tavily", api_key="tavily-test-key")

    assert web._search_provider_kwargs("tavily")["api_key"] == "tavily-test-key"


@pytest.mark.asyncio
async def test_brave_provider_maps_provider_source_and_published_at() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Brave title",
                            "url": "https://example.com/brave",
                            "description": "Brave snippet",
                            "age": "2026-06-19",
                        }
                    ]
                }
            },
        )

    provider = BraveSearchProvider(
        api_key="brave-test-key",
        transport=httpx.MockTransport(handler),
    )

    result = (await provider.search("brave"))[0]

    assert result.provider == "brave"
    assert result.source == "brave"
    assert result.published_at == "2026-06-19"


@pytest.mark.asyncio
async def test_duckduckgo_provider_maps_provider_and_source() -> None:
    html = """
    <html>
      <body>
        <div class="result">
          <h2 class="result__title"><a href="https://example.com/ddg">DDG title</a></h2>
          <a class="result__snippet">DDG snippet</a>
        </div>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    provider = DuckDuckGoProvider(transport=httpx.MockTransport(handler))

    result = (await provider.search("duck"))[0]

    assert result.provider == "duckduckgo"
    assert result.source == "duckduckgo"


def test_search_payload_keeps_lightweight_metadata() -> None:
    payload = web._search_payload(
        "python",
        "tavily",
        [
            SearchResult(
                title="Title",
                url="https://Docs.Python.org/3/?utm_source=x#intro",
                snippet="Snippet",
                provider="tavily",
                source="tavily",
                published_at="2026-06-19",
                score=0.9,
                content="Full content must stay out",
                raw_metadata={"debug": "must stay out"},
            )
        ],
    )

    result = payload["results"][0]
    assert result == {
        "title": "Title",
        "url": "https://Docs.Python.org/3/?utm_source=x#intro",
        "snippet": "Snippet",
        "provider": "tavily",
        "published_at": "2026-06-19",
        "score": 0.9,
        "domain": "docs.python.org",
        "canonical_url": "https://docs.python.org/3",
    }
