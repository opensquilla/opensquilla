from __future__ import annotations

import socket
from importlib import import_module
from pathlib import Path

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.tools import ssrf
from opensquilla.tools.types import SSRFBlockedError

web_fetch_module = import_module("opensquilla.tools.builtin.web_fetch")


def _fake_getaddrinfo(ip: str):
    def resolver(hostname: str, port: int | None, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 443))]

    return resolver


@pytest.fixture(autouse=True)
def reset_trusted_fake_ip_cidrs():
    ssrf.configure_trusted_fake_ip_cidrs([])
    yield
    ssrf.configure_trusted_fake_ip_cidrs([])


def test_rfc2544_fake_ip_is_blocked_by_default(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("198.18.0.2"))

    with pytest.raises(SSRFBlockedError) as excinfo:
        ssrf.validate_http_url_for_fetch("https://github.com/OpenSquilla/opensquilla")

    assert "198.18.0.2" in str(excinfo.value)
    assert "198.18.0.0/15" in str(excinfo.value)


def test_rfc2544_fake_ip_can_be_explicitly_trusted(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("198.18.0.2"))

    ssrf.validate_http_url_for_fetch(
        "https://github.com/OpenSquilla/opensquilla",
        trusted_fake_ip_cidrs=["198.18.0.0/15"],
    )


def test_runtime_config_applies_to_web_fetch_guard(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("198.18.0.2"))
    ssrf.configure_trusted_fake_ip_cidrs(["198.18.0.0/15"])

    web_fetch_module._check_ssrf("https://github.com/OpenSquilla/opensquilla")


def test_trusted_fake_ip_never_allows_loopback(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))

    with pytest.raises(SSRFBlockedError) as excinfo:
        ssrf.validate_http_url_for_fetch(
            "https://example.com/",
            trusted_fake_ip_cidrs=["198.18.0.0/15"],
        )

    assert "127.0.0.1" in str(excinfo.value)


def test_gateway_config_accepts_rfc2544_trusted_fake_ip_cidr(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[tools]\ntrusted_fake_ip_cidrs = ["198.18.0.0/15"]\n',
        encoding="utf-8",
    )

    config = GatewayConfig.load(config_path)

    assert config.tools.trusted_fake_ip_cidrs == ["198.18.0.0/15"]


def test_gateway_config_rejects_non_fake_ip_trusted_cidr(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[tools]\ntrusted_fake_ip_cidrs = ["127.0.0.0/8"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="198.18.0.0/15"):
        GatewayConfig.load(config_path)
