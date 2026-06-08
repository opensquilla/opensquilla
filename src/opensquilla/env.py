"""Unified .env file loader — single source of truth for API keys.

Precedence (highest to lowest):
1. os.environ (already set by shell / CI)
2. .env in current working directory
3. .env in the resolved OpenSquilla home
   (default: ``~/.opensquilla/profiles/<profile>/.env`` when multi-instance
   mode is active via ``OPENSQUILLA_HOME`` / ``OPENSQUILLA_PROFILE``, or
   ``~/.opensquilla/.env`` for the single-instance fallback)

Existing environment variables are NEVER overridden.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Deliberately do NOT use structlog here: load_env() can run from inside
# a Typer sub-command that is about to print a machine-readable JSON
# payload on stdout (e.g. `opensquilla gateway status --json`), and
# structlog's logger factory is configured at module-import time by
# other opensquilla submodules. Routing through it would mix log lines
# with the JSON. Printing to stderr keeps the contract clean.

_TRUTHY = {"1", "true", "yes", "on"}
_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")


def _debug(message: str) -> None:
    # Verbose diagnostic — never on stdout, never raises.
    print(f"opensquilla.env: {message}", file=sys.stderr)


def trust_env() -> bool:
    """Return True when opensquilla's httpx clients should honor env proxy/TLS vars.

    Gated by ``OPENSQUILLA TRUST_ENV``. Off by default — opensquilla defaults to
    deterministic, env-isolated networking so a stray HTTP_PROXY in a parent
    shell cannot silently reroute agent traffic. Set ``OPENSQUILLA TRUST_ENV=1``
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
        _debug(
            "env proxy ignored (set OPENSQUILLA_TRUST_ENV=1 to honor "
            f"HTTP_PROXY/HTTPS_PROXY): {present}"
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


def load_env(
    cwd: str | Path | None = None,
    home: str | Path | None = None,
) -> int:
    """Load .env files into os.environ with precedence rules.

    Parameters
    ----------
    cwd
        Override the working directory whose ``.env`` / ``.env.test`` is the
        first candidate. Defaults to :func:`os.getcwd`.
    home
        Override the OpenSquilla home whose ``.env`` is the second candidate.
        The caller — i.e. ``cli.main._profile_callback`` — is expected to
        pass the home resolved *after* the active profile is known, so the
        selected profile's ``.env`` is loaded instead of the legacy
        ``~/.opensquilla/.env``.

        When ``None`` (the default for backwards-compat callers), the home is
        resolved via :func:`opensquilla.paths.default_opensquilla_home` at
        call time. Callers that have already resolved the active profile
        should pass it explicitly.

    Returns the number of new variables injected.
    """
    # Import here to avoid an import cycle: opensquilla.paths -> opensquilla.env
    # when env.py is imported during paths.py module init.
    from opensquilla.paths import default_opensquilla_home

    candidates: list[Path] = []

    # 1. cwd/.env (or cwd/.env.test as alias for dev)
    work_dir = Path(cwd) if cwd else Path.cwd()
    for name in (".env", ".env.test"):
        candidates.append(work_dir / name)

    # 2. <home>/.env — caller-supplied (profile-aware) or resolved at call
    #    time. Resolving at call time keeps backwards-compat for any code
    #    that calls load_env() before the CLI profile is known; for the
    #    CLI, _profile_callback supplies the resolved home explicitly.
    resolved_home = Path(home) if home is not None else default_opensquilla_home()
    candidates.append(resolved_home / ".env")

    # Merge: first file wins per key, but os.environ always wins
    merged: dict[str, str] = {}
    for path in candidates:
        for key, value in _parse_env_file(path).items():
            if key not in merged:
                merged[key] = value
                _debug(f"loaded key={key!r} from {path}")

    # Inject into os.environ — never override existing
    injected = 0
    for key, value in merged.items():
        if key not in os.environ:
            os.environ[key] = value
            injected += 1

    if injected:
        _debug(f"injected {injected} new variable(s) into os.environ")

    return injected

