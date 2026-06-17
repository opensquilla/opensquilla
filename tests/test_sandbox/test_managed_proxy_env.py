from __future__ import annotations

from opensquilla.sandbox.managed_proxy_env import (
    ALLOW_LOCAL_BINDING_ENV_KEY,
    DEFAULT_NO_PROXY_VALUE,
    NO_PROXY_ENV_KEYS,
    PROXY_ACTIVE_ENV_KEY,
    PROXY_CONTROL_ENV,
    PROXY_ENV_KEYS,
    managed_proxy_env,
    managed_proxy_env_allowlist,
)


def test_managed_proxy_env_matches_codex_proxy_controls_without_windows_git() -> None:
    env = managed_proxy_env("127.0.0.1", 48123)

    for key in PROXY_ENV_KEYS:
        assert env[key] == "http://127.0.0.1:48123"
    for key in NO_PROXY_ENV_KEYS:
        assert env[key] == DEFAULT_NO_PROXY_VALUE
    for key, value in PROXY_CONTROL_ENV:
        assert env[key] == value

    assert env[PROXY_ACTIVE_ENV_KEY] == "1"
    assert env[ALLOW_LOCAL_BINDING_ENV_KEY] == "0"
    assert env["NODE_USE_ENV_PROXY"] == "1"
    assert env["ELECTRON_GET_USE_PROXY"] == "true"
    assert env["OPENSQUILLA_SANDBOX_NETWORK"] == "proxy_allowlist"
    assert "GIT_CONFIG_COUNT" not in env
    assert "GIT_CONFIG_KEY_0" not in env
    assert "GIT_CONFIG_VALUE_0" not in env


def test_windows_managed_proxy_env_adds_only_windows_git_override() -> None:
    env = managed_proxy_env("127.0.0.1", 48123, windows_git_ssl_backend=True)

    assert env["HTTP_PROXY"] == "http://127.0.0.1:48123"
    assert env["CODEX_NETWORK_PROXY_ACTIVE"] == "1"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.sslBackend"
    assert env["GIT_CONFIG_VALUE_0"] == "openssl"


def test_managed_proxy_env_allowlist_contains_all_generated_keys() -> None:
    env = managed_proxy_env("127.0.0.1", 48123, windows_git_ssl_backend=True)

    assert set(env).issubset(set(managed_proxy_env_allowlist(include_windows_git=True)))
    assert "GIT_CONFIG_KEY_0" not in managed_proxy_env_allowlist()


def test_linux_proxy_modules_stay_aligned_with_common_proxy_env() -> None:
    from opensquilla.sandbox.backend import linux_proxy_bridge, linux_proxy_routing

    assert linux_proxy_routing.PROXY_ENV_KEYS == PROXY_ENV_KEYS
    assert linux_proxy_routing.NO_PROXY_ENV_KEYS == NO_PROXY_ENV_KEYS
    assert linux_proxy_routing.PROXY_CONTROL_ENV == PROXY_CONTROL_ENV
    assert linux_proxy_routing.DEFAULT_NO_PROXY_VALUE == DEFAULT_NO_PROXY_VALUE

    assert linux_proxy_bridge.PROXY_ENV_KEYS == PROXY_ENV_KEYS
    assert linux_proxy_bridge.NO_PROXY_ENV_KEYS == NO_PROXY_ENV_KEYS
    assert linux_proxy_bridge.PROXY_CONTROL_ENV == PROXY_CONTROL_ENV
    assert linux_proxy_bridge.DEFAULT_NO_PROXY_VALUE == DEFAULT_NO_PROXY_VALUE
