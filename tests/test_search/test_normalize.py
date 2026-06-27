from __future__ import annotations

from opensquilla.search.normalize import (
    canonicalize_query_key,
    canonicalize_url,
    dedupe_hits_by_canonical_url,
    extract_domain,
)
from opensquilla.search.types import SearchHit


def test_canonicalize_url_removes_fragments_and_tracking_params() -> None:
    url = "HTTPS://Example.com:443/a/../b/?utm_source=x&b=2&a=1#section"

    assert canonicalize_url(url) == "https://example.com/b?a=1&b=2"


def test_canonicalize_url_preserves_malformed_port_without_crashing() -> None:
    url = "http://Example.com:bad/path?utm_source=x&a=1#frag"

    assert canonicalize_url(url) == "http://example.com:bad/path?a=1"


def test_extract_domain_lowercases_hostname() -> None:
    assert extract_domain("https://Docs.Python.org/3/") == "docs.python.org"


def test_canonicalize_query_key_collapses_whitespace_and_case() -> None:
    assert canonicalize_query_key("  Python   Release Notes  ") == "python release notes"


def test_dedupe_hits_by_canonical_url_keeps_first_ranked_hit() -> None:
    first = SearchHit(
        title="First",
        url="https://example.com/path?utm_campaign=x",
        canonical_url="https://example.com/path",
        domain="example.com",
        provider="tavily",
        snippet="first",
        rank=1,
    )
    duplicate = SearchHit(
        title="Duplicate",
        url="https://example.com/path#frag",
        canonical_url="https://example.com/path",
        domain="example.com",
        provider="brave",
        snippet="duplicate",
        rank=2,
    )

    hits, duplicate_count = dedupe_hits_by_canonical_url([first, duplicate])

    assert hits == [first]
    assert duplicate_count == 1
