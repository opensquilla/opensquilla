"""Passive update-availability check.

Queries the public GitHub Releases API for the latest published OpenSquilla
release and compares it with the running version, so the Control UI (and the
``opensquilla version --check`` command) can show a friendly "a newer version
is available" notice. This is intentionally passive: it never downloads or
installs anything, never blocks startup, and never raises.

The result is cached under the state dir with a 24h TTL so the gateway does at
most one network call per day. The check honours the same disable switch as the
anonymous install telemetry (so a single env var silences all outbound
"phone-home" calls) plus a dedicated switch, and is skipped automatically in CI
and test environments.

The desktop Electron app handles updates natively (electron-updater), so the
in-app banner is suppressed there; this module is what powers the notice for
the browser / wheel / portable / Docker surfaces that share the same Control UI.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensquilla import __version__
from opensquilla.paths import default_opensquilla_home

log = logging.getLogger(__name__)

UPDATE_CHECK_SCHEMA_VERSION = 1
UPDATE_CHECK_STATE_FILE = "update_check.json"

# Dedicated switch plus the shared telemetry switch — either one disables the
# check, so users who opted out of telemetry get no surprise outbound calls.
UPDATE_CHECK_DISABLED_ENV = "OPENSQUILLA_UPDATE_CHECK_DISABLED"
TELEMETRY_DISABLED_ENV = "OPENSQUILLA_TELEMETRY_DISABLED"
UPDATE_CHECK_ENDPOINT_ENV = "OPENSQUILLA_UPDATE_CHECK_ENDPOINT"
TELEMETRY_TESTING_ENV = "OPENSQUILLA_TESTING"

# The releases/latest endpoint returns the most recent NON-draft, NON-prerelease
# release, which is exactly the stable channel a passive notice should point at.
DEFAULT_UPDATE_CHECK_ENDPOINT = (
    "https://api.github.com/repos/opensquilla/opensquilla/releases/latest"
)
DEFAULT_RELEASES_PAGE = "https://github.com/opensquilla/opensquilla/releases/latest"

DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_TIMEOUT_SECONDS = 3.0

_TRUE_VALUES = {"1", "true", "yes", "on"}
_AUTO_SKIP_ENV_VARS = ("GITHUB_ACTIONS", "PYTEST_CURRENT_TEST", TELEMETRY_TESTING_ENV)

# In-process cache of the last result so per-request bootstrap reads never touch
# disk or the network. Seeded from the state file on first read; refreshed by
# the background thread.
_CACHED_INFO: UpdateCheckInfo | None = None
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class UpdateCheckInfo:
    current_version: str
    latest_version: str | None
    update_available: bool
    release_url: str
    checked_at: str | None = None
    disabled: bool = False
    error: str | None = None
    from_cache: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        """The minimal shape injected into the Control UI bootstrap context."""
        return {
            "current": self.current_version,
            "latest": self.latest_version,
            "available": self.update_available,
            "url": self.release_url,
            "checkedAt": self.checked_at,
        }


# ── Public API ───────────────────────────────────────────────────────────────


def refresh_update_check(
    *,
    config: Any | None = None,
    state_path: str | Path | None = None,
    version: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    force: bool = False,
) -> UpdateCheckInfo:
    """Check for a newer release, using the cached result when still fresh.

    May perform one network call. Never raises. Writes the result to the cache
    file and the in-process cache. Pass ``force=True`` to bypass the TTL (used by
    ``opensquilla version --check``).
    """
    current = (version or __version__ or "unknown").strip() or "unknown"
    path = _state_path(config=config, explicit=state_path)

    skip_reason = _skip_reason()
    if skip_reason:
        info = UpdateCheckInfo(
            current_version=current,
            latest_version=None,
            update_available=False,
            release_url=_releases_page(),
            disabled=True,
        )
        _store_cache(info)
        return info

    try:
        state = _load_state(path)
        cached_latest = state.get("latest_version")
        checked_at = state.get("checked_at")
        if (
            not force
            and isinstance(cached_latest, str)
            and cached_latest
            and _is_fresh(state.get("checked_ts"), ttl_seconds)
        ):
            info = UpdateCheckInfo(
                current_version=current,
                latest_version=cached_latest,
                update_available=_is_newer(cached_latest, current),
                release_url=str(state.get("release_url") or _releases_page()),
                checked_at=checked_at if isinstance(checked_at, str) else None,
                from_cache=True,
            )
            _store_cache(info)
            return info

        latest, release_url, error = _fetch_latest_release(
            _endpoint(), current, timeout=DEFAULT_TIMEOUT_SECONDS
        )
        now_iso = _utc_now()
        if latest is None:
            # Network/parse failure: keep any previous cached value rather than
            # discard it, but record the error and timestamp.
            state["last_error"] = error or "fetch_failed"
            state["last_attempt_ts"] = _now_ts()
            _write_state(path, state)
            info = UpdateCheckInfo(
                current_version=current,
                latest_version=cached_latest if isinstance(cached_latest, str) else None,
                update_available=(
                    _is_newer(cached_latest, current)
                    if isinstance(cached_latest, str) and cached_latest
                    else False
                ),
                release_url=str(state.get("release_url") or _releases_page()),
                checked_at=checked_at if isinstance(checked_at, str) else None,
                error=error,
                from_cache=True,
            )
            _store_cache(info)
            return info

        resolved_url = release_url or _releases_page()
        state.update(
            {
                "schema_version": UPDATE_CHECK_SCHEMA_VERSION,
                "latest_version": latest,
                "release_url": resolved_url,
                "checked_at": now_iso,
                "checked_ts": _now_ts(),
                "last_attempt_ts": _now_ts(),
                "last_error": None,
            }
        )
        _write_state(path, state)
        info = UpdateCheckInfo(
            current_version=current,
            latest_version=latest,
            update_available=_is_newer(latest, current),
            release_url=resolved_url,
            checked_at=now_iso,
        )
        _store_cache(info)
        return info
    except Exception as exc:  # pragma: no cover - defensive guard
        log.debug("Update check failed: %s", exc, exc_info=True)
        return UpdateCheckInfo(
            current_version=current,
            latest_version=None,
            update_available=False,
            release_url=_releases_page(),
            error=str(exc),
        )


def get_cached_update_info(
    *,
    config: Any | None = None,
    state_path: str | Path | None = None,
    version: str | None = None,
) -> UpdateCheckInfo | None:
    """Return the last known update info WITHOUT any network call.

    Reads the in-process cache, falling back to the state file (so a freshly
    started process picks up the previous run's result instantly — important for
    the desktop app, which restarts on every launch). ``update_available`` is
    recomputed against the *current* running version so a just-upgraded build
    immediately stops showing the notice. Returns ``None`` when no check has ever
    completed.
    """
    current = (version or __version__ or "unknown").strip() or "unknown"
    if _skip_reason():
        _store_cache(
            UpdateCheckInfo(
                current_version=current,
                latest_version=None,
                update_available=False,
                release_url=_releases_page(),
                disabled=True,
            )
        )
        return None

    with _CACHE_LOCK:
        cached = _CACHED_INFO
    if cached is not None and cached.latest_version is not None:
        return _recompute(cached, current)

    path = _state_path(config=config, explicit=state_path)
    state = _load_state(path)
    latest = state.get("latest_version")
    if not isinstance(latest, str) or not latest:
        return None
    checked_at = state.get("checked_at")
    return UpdateCheckInfo(
        current_version=current,
        latest_version=latest,
        update_available=_is_newer(latest, current),
        release_url=str(state.get("release_url") or _releases_page()),
        checked_at=checked_at if isinstance(checked_at, str) else None,
        from_cache=True,
    )


def start_background_update_check(
    *,
    config: Any | None = None,
    state_path: str | Path | None = None,
    version: str | None = None,
) -> threading.Thread | None:
    """Run :func:`refresh_update_check` in a daemon thread (fire-and-forget).

    Returns the thread (so tests can join it) or ``None`` when the check is
    disabled. Never raises.
    """
    if _skip_reason():
        return None

    def _run() -> None:
        try:
            refresh_update_check(config=config, state_path=state_path, version=version)
        except Exception:  # pragma: no cover - defensive guard
            log.debug("Background update check failed", exc_info=True)

    try:
        thread = threading.Thread(
            target=_run, name="opensquilla-update-check", daemon=True
        )
        thread.start()
        return thread
    except Exception:  # pragma: no cover - thread spawn failure
        log.debug("Could not start update-check thread", exc_info=True)
        return None


# ── Internals ────────────────────────────────────────────────────────────────


def _store_cache(info: UpdateCheckInfo) -> None:
    global _CACHED_INFO
    with _CACHE_LOCK:
        _CACHED_INFO = info


def _recompute(info: UpdateCheckInfo, current: str) -> UpdateCheckInfo:
    if info.current_version == current:
        return info
    latest = info.latest_version
    return UpdateCheckInfo(
        current_version=current,
        latest_version=latest,
        update_available=_is_newer(latest, current) if latest else False,
        release_url=info.release_url,
        checked_at=info.checked_at,
        from_cache=True,
    )


def _state_path(*, config: Any | None, explicit: str | Path | None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    configured_state_dir = getattr(config, "state_dir", None)
    if isinstance(configured_state_dir, str) and configured_state_dir.strip():
        root = Path(configured_state_dir.strip()).expanduser()
    else:
        root = default_opensquilla_home() / "state"
    return root / UPDATE_CHECK_STATE_FILE


def _disabled() -> bool:
    for env_name in (UPDATE_CHECK_DISABLED_ENV, TELEMETRY_DISABLED_ENV):
        if os.environ.get(env_name, "").strip().lower() in _TRUE_VALUES:
            return True
    return False


def _skip_reason() -> str | None:
    if _disabled():
        return "disabled"
    for name in _AUTO_SKIP_ENV_VARS:
        value = os.environ.get(name, "")
        if name == "PYTEST_CURRENT_TEST":
            if value.strip():
                return f"environment:{name}"
            continue
        if value.strip().lower() in _TRUE_VALUES:
            return f"environment:{name}"
    return None


def _endpoint() -> str:
    return os.environ.get(
        UPDATE_CHECK_ENDPOINT_ENV, DEFAULT_UPDATE_CHECK_ENDPOINT
    ).strip()


def _releases_page() -> str:
    return DEFAULT_RELEASES_PAGE


def _now_ts() -> int:
    return int(datetime.now(UTC).timestamp())


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_fresh(checked_ts: object, ttl_seconds: int) -> bool:
    if not isinstance(checked_ts, (int, float)):
        return False
    return (_now_ts() - int(checked_ts)) < ttl_seconds


def _load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            log.debug("Update-check state unreadable; replacing", exc_info=True)
    return {"schema_version": UPDATE_CHECK_SCHEMA_VERSION}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _fetch_latest_release(
    endpoint: str,
    current_version: str,
    *,
    timeout: float,
) -> tuple[str | None, str | None, str | None]:
    """Return (tag_name_without_v, html_url, error). Network failures are soft."""
    if not endpoint:
        return None, None, "endpoint_empty"
    try:
        import httpx

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"opensquilla/{current_version}",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(endpoint, headers=headers)
        if response.status_code != 200:
            return None, None, f"http_status_{response.status_code}"
        payload = response.json()
    except Exception as exc:
        log.debug("Update-check fetch failed: %s", exc)
        return None, None, str(exc)

    if not isinstance(payload, dict):
        return None, None, "unexpected_payload"
    tag = payload.get("tag_name") or payload.get("name")
    if not isinstance(tag, str) or not tag.strip():
        return None, None, "missing_tag"
    html_url = payload.get("html_url")
    return (
        tag.strip().lstrip("vV"),
        html_url if isinstance(html_url, str) and html_url else None,
        None,
    )


_VERSION_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$")


def _version_key(value: str | None) -> tuple[tuple[int, int, int], int] | None:
    """Comparable key for a version string, or None when it should be ignored.

    Returns ((major, minor, patch), release_rank). A final release ranks above
    its own pre-release (rank 1 vs 0). Versions carrying build/local metadata
    (e.g. the ``0.0.0+unknown`` reported by editable/source checkouts) return
    None so dev installs are never nagged with an "update available" notice.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("vV")
    if not text or "+" in text:
        return None
    match = _VERSION_RE.match(text)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    remainder = (match.group(4) or "").strip()
    # Anything after the numeric core (rc1, a2, .dev3, -beta) marks a pre-release.
    release_rank = 0 if remainder else 1
    return (major, minor, patch), release_rank


def _is_newer(latest: str | None, current: str | None) -> bool:
    latest_key = _version_key(latest)
    current_key = _version_key(current)
    if latest_key is None or current_key is None:
        return False
    return latest_key > current_key
