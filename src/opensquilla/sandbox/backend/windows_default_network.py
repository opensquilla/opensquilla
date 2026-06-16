"""Windows managed-network boundary helpers for windows_default."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

FIREWALL_RULE_VERSION = 3
WFP_RULE_VERSION = 2
NETWORK_SETUP_VERSION = 1

PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "YARN_HTTP_PROXY",
    "YARN_HTTPS_PROXY",
    "npm_config_http_proxy",
    "npm_config_https_proxy",
    "npm_config_proxy",
    "NPM_CONFIG_HTTP_PROXY",
    "NPM_CONFIG_HTTPS_PROXY",
    "NPM_CONFIG_PROXY",
    "BUNDLE_HTTP_PROXY",
    "BUNDLE_HTTPS_PROXY",
    "PIP_PROXY",
    "DOCKER_HTTP_PROXY",
    "DOCKER_HTTPS_PROXY",
    "WS_PROXY",
    "WSS_PROXY",
    "ws_proxy",
    "wss_proxy",
    "ALL_PROXY",
    "all_proxy",
    "FTP_PROXY",
    "ftp_proxy",
)

NO_PROXY_ENV_KEYS = (
    "NO_PROXY",
    "no_proxy",
    "npm_config_noproxy",
    "NPM_CONFIG_NOPROXY",
    "YARN_NO_PROXY",
    "BUNDLE_NO_PROXY",
)

DEFAULT_NO_PROXY_VALUE = (
    "localhost,127.0.0.1,::1,"
    "10.0.0.0/8,"
    "172.16.0.0/12,"
    "192.168.0.0/16"
)

LOOPBACK_PROXY_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class WindowsNetworkSetup:
    offline_user_sid: str
    allowed_proxy_ports: tuple[int, ...]
    allow_local_binding: bool
    firewall_rule_version: int
    wfp_rule_version: int
    offline_username: str | None = None
    protected_password: str | None = None
    network_setup_version: int = NETWORK_SETUP_VERSION

    def is_current_for_ports(self, ports: tuple[int, ...]) -> bool:
        return (
            bool(self.offline_user_sid)
            and self.allowed_proxy_ports == tuple(sorted(set(ports)))
            and self._firewall_rule_version_is_compatible()
            and self.wfp_rule_version == WFP_RULE_VERSION
            and self.network_setup_version == NETWORK_SETUP_VERSION
        )

    def _firewall_rule_version_is_compatible(self) -> bool:
        return self.firewall_rule_version == FIREWALL_RULE_VERSION

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "offlineUserSid": self.offline_user_sid,
            "allowedProxyPorts": list(self.allowed_proxy_ports),
            "allowLocalBinding": self.allow_local_binding,
            "firewallRuleVersion": self.firewall_rule_version,
            "wfpRuleVersion": self.wfp_rule_version,
            "networkSetupVersion": self.network_setup_version,
        }
        if self.offline_username:
            payload["offlineUsername"] = self.offline_username
        if self.protected_password:
            payload["protectedPassword"] = self.protected_password
        return payload


def network_proxy_env(host: str, port: int) -> dict[str, str]:
    proxy_url = f"http://{host}:{port}"
    env = {key: proxy_url for key in PROXY_ENV_KEYS}
    env.update({key: DEFAULT_NO_PROXY_VALUE for key in NO_PROXY_ENV_KEYS})
    env.update(
        {
            "NODE_USE_ENV_PROXY": "1",
            "ELECTRON_GET_USE_PROXY": "true",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.sslBackend",
            "GIT_CONFIG_VALUE_0": "openssl",
            "OPENSQUILLA_SANDBOX_NETWORK": "proxy_allowlist",
        }
    )
    return env


def proxy_ports_from_env(env: dict[str, str]) -> tuple[int, ...]:
    ports: set[int] = set()
    for key in PROXY_ENV_KEYS:
        value = env.get(key)
        if not value:
            continue
        port = loopback_proxy_port_from_url(value)
        if port is not None:
            ports.add(port)
    return tuple(sorted(ports))


def loopback_proxy_port_from_url(value: str) -> int | None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname
    if host not in LOOPBACK_PROXY_HOSTS or port is None:
        return None
    if not (1 <= int(port) <= 65535):
        return None
    return int(port)


def blocked_loopback_tcp_remote_ports(allowed_ports: tuple[int, ...]) -> tuple[str, ...]:
    ports = sorted({int(port) for port in allowed_ports if 1 <= int(port) <= 65535})
    ranges: list[str] = []
    start = 1
    for port in ports:
        if port > start:
            ranges.append(_port_range(start, port - 1))
        start = port + 1
    if start <= 65535:
        ranges.append(_port_range(start, 65535))
    return tuple(ranges)


def _port_range(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


__all__ = [
    "DEFAULT_NO_PROXY_VALUE",
    "FIREWALL_RULE_VERSION",
    "NETWORK_SETUP_VERSION",
    "NO_PROXY_ENV_KEYS",
    "PROXY_ENV_KEYS",
    "WFP_RULE_VERSION",
    "WindowsNetworkSetup",
    "blocked_loopback_tcp_remote_ports",
    "loopback_proxy_port_from_url",
    "network_proxy_env",
    "proxy_ports_from_env",
]
