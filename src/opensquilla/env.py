"""Unified .env file loader — single source of truth for API keys.

Precedence (highest to lowest):
1. os.environ (already set by shell / CI)
2. .env.test in current working directory during test runs
3. .env in current working directory
4. .env.test in current working directory outside test runs, for keys absent from .env
5. ~/.opensquilla/.env (global user config)

Existing environment variables are NEVER overridden.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog

from opensquilla.paths import default_opensquilla_home

log = structlog.get_logger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")


def trust_env() -> bool:
    """Return True when opensquilla's httpx clients should honor env proxy/TLS vars.

    Gated by ``OPENSQUILLA_TRUST_ENV``. Off by default — opensquilla defaults to
    deterministic, env-isolated networking so a stray HTTP_PROXY in a parent
    shell cannot silently reroute agent traffic. Set ``OPENSQUILLA_TRUST_ENV=1``
    (e.g. in ~/.opensquilla/.env) to opt in; required on WSL2 / corporate networks
    where the only route to external APIs is a shell-exported proxy.
    """
    return os.environ.get("OPENSQUILLA_TRUST_ENV", "").strip().lower() in _TRUTHY


def warn_if_proxy_ignored() -> None:
    """Log a one-time hint if env has HTTP(S)_PROXY but trust_env is off."""
    if trust_env():
        return
    present = [v for v in _PROXY_ENV_VARS if os.environ.get(v)]
    if present:
        log.warning(
            "env.proxy_ignored",
            vars=present,
            hint="Set OPENSQUILLA_TRUST_ENV=1 to let opensquilla honor env proxy settings.",
        )


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Skips comments and blank lines."""
    if not path.is_file():
        return {}
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            entries[key] = value
    return entries


def _is_test_env_enabled() -> bool:
    """Return True when local test env files should override local dev env files."""
    # PYTEST_CURRENT_TEST is unavailable during collection/import, so tests that
    # need import-time .env.test precedence should set OPENSQUILLA_TEST=1.
    if os.environ.get("OPENSQUILLA_TEST", "").strip().lower() in _TRUTHY:
        return True
    return "PYTEST_CURRENT_TEST" in os.environ


def load_env(cwd: str | Path | None = None) -> int:
    """Load .env files into os.environ with precedence rules.

    Returns the number of new variables injected.
    """
    candidates = []

    # 1. cwd/.env.test in test runs, otherwise cwd/.env wins for normal dev runs.
    work_dir = Path(cwd) if cwd else Path.cwd()
    local_names = (".env.test", ".env") if _is_test_env_enabled() else (".env", ".env.test")
    for name in local_names:
        candidates.append(work_dir / name)

    # 2. ~/.opensquilla/.env (global)
    candidates.append(default_opensquilla_home() / ".env")

    # Merge: first file wins per key, but os.environ always wins
    merged: dict[str, str] = {}
    for path in candidates:
        for key, value in _parse_env_file(path).items():
            if key not in merged:
                merged[key] = value
                log.debug("env.loaded", key=key, source=str(path))

    # Inject into os.environ — never override existing
    injected = 0
    for key, value in merged.items():
        if key not in os.environ:
            os.environ[key] = value
            injected += 1

    if injected:
        log.info("env.injected", count=injected)

    return injected
