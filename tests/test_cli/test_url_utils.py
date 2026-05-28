from __future__ import annotations

from opensquilla.cli.url_utils import normalize_gateway_url


def test_normalize_gateway_url_preserves_query_and_fragment() -> None:
    assert (
        normalize_gateway_url("https://gateway.example.com/ws?token=abc#trace")
        == "wss://gateway.example.com/ws?token=abc#trace"
    )


def test_normalize_gateway_url_adds_ws_path_without_dropping_query() -> None:
    assert normalize_gateway_url("gateway.example.com?token=abc") == "ws://gateway.example.com/ws?token=abc"
