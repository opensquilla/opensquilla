"""Shared SSRF protection for URL-fetching tools."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlparse

from opensquilla.tools.types import SSRFBlockedError, UnsupportedURLSchemeError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

RFC2544_FAKE_IP_NETWORK = ipaddress.IPv4Network("198.18.0.0/15")

_HARD_BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_trusted_fake_ip_cidrs: tuple[IPNetwork, ...] = ()


def validate_trusted_fake_ip_cidrs(values: Iterable[str]) -> list[str]:
    """Return normalized fake-IP CIDRs or raise for unsafe entries."""
    networks: list[str] = []
    for raw in values:
        try:
            network = ipaddress.ip_network(str(raw).strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"trusted_fake_ip_cidrs entry {raw!r} is not a valid CIDR") from exc

        if not isinstance(network, ipaddress.IPv4Network) or not network.subnet_of(
            RFC2544_FAKE_IP_NETWORK
        ):
            raise ValueError(
                "trusted_fake_ip_cidrs may only contain subnets of "
                f"{RFC2544_FAKE_IP_NETWORK}; got {network}"
            )
        networks.append(str(network))
    return networks


def configure_trusted_fake_ip_cidrs(values: Iterable[str]) -> None:
    """Configure process-wide fake-IP CIDRs trusted by URL fetch guards."""
    global _trusted_fake_ip_cidrs
    normalized = validate_trusted_fake_ip_cidrs(values)
    _trusted_fake_ip_cidrs = tuple(ipaddress.ip_network(value) for value in normalized)


def get_trusted_fake_ip_cidrs() -> list[str]:
    """Return the process-wide trusted fake-IP CIDRs as normalized strings."""
    return [str(network) for network in _trusted_fake_ip_cidrs]


def validate_http_url_for_fetch(
    url: str,
    *,
    trusted_fake_ip_cidrs: Iterable[str] | None = None,
) -> None:
    """Validate that an HTTP(S) URL does not resolve to a blocked address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsupportedURLSchemeError("Only HTTP/HTTPS URLs are supported")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: no hostname")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from exc

    trusted_networks = (
        tuple(
            ipaddress.ip_network(value)
            for value in validate_trusted_fake_ip_cidrs(trusted_fake_ip_cidrs)
        )
        if trusted_fake_ip_cidrs is not None
        else _trusted_fake_ip_cidrs
    )

    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        block_reason = _hard_block_reason(addr)
        if block_reason is not None:
            raise SSRFBlockedError(_blocked_message(hostname, addr, block_reason))
        if _is_trusted_fake_ip(addr, trusted_networks):
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            reason = (
                f"reserved/private range; configure [tools].trusted_fake_ip_cidrs "
                f"with {RFC2544_FAKE_IP_NETWORK} only if this is fake-IP DNS"
                if addr in RFC2544_FAKE_IP_NETWORK
                else "private/internal range"
            )
            raise SSRFBlockedError(_blocked_message(hostname, addr, reason))


def _hard_block_reason(addr: IPAddress) -> str | None:
    for network in _HARD_BLOCKED_NETWORKS:
        if addr.version == network.version and addr in network:
            return f"hard-blocked network {network}"
    return None


def _is_trusted_fake_ip(addr: IPAddress, trusted_networks: tuple[IPNetwork, ...]) -> bool:
    return any(addr.version == network.version and addr in network for network in trusted_networks)


def _blocked_message(hostname: str, addr: IPAddress, reason: str) -> str:
    return f"Blocked: {hostname} resolves to {addr} ({reason})"
