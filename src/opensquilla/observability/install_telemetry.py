"""Anonymous installation telemetry.

The telemetry surface is intentionally narrow: it tracks installation instances
and version distribution, not users. The default endpoint points at the official
OpenSquilla collector and can be overridden or disabled by environment variable.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensquilla import __version__
from opensquilla.paths import default_opensquilla_home

log = logging.getLogger(__name__)

TELEMETRY_SCHEMA_VERSION = 1
TELEMETRY_STATE_FILE = "install_telemetry.json"
TELEMETRY_DISABLED_ENV = "OPENSQUILLA_TELEMETRY_DISABLED"
TELEMETRY_ENDPOINT_ENV = "OPENSQUILLA_TELEMETRY_ENDPOINT"
TELEMETRY_INSTALL_METHOD_ENV = "OPENSQUILLA_INSTALL_METHOD"

DEFAULT_TELEMETRY_ENDPOINT = "https://telemetry.opensquilla.ai/v1/install"
DEFAULT_TIMEOUT_SECONDS = 2.0

_TRUE_VALUES = {"1", "true", "yes", "on"}
_SUCCESS_STATUS_CODES = {200, 201, 202, 204}


@dataclass(frozen=True)
class InstallTelemetryResult:
    state_path: Path
    endpoint_configured: bool
    disabled: bool = False
    event: str | None = None
    sent: bool = False
    uploaded: bool = False
    skipped_reason: str | None = None
    error: str | None = None


def collect_install_telemetry(
    *,
    config: Any | None = None,
    state_path: str | Path | None = None,
    version: str | None = None,
) -> InstallTelemetryResult:
    """Collect and upload anonymous installation telemetry if needed.

    This function never raises. It is safe to call during gateway startup.
    """
    path = _state_path(config=config, explicit=state_path)
    endpoint = _endpoint()

    try:
        if _telemetry_disabled():
            return InstallTelemetryResult(
                state_path=path,
                endpoint_configured=bool(endpoint),
                disabled=True,
                skipped_reason="disabled",
            )

        current_version = (version or __version__ or "unknown").strip() or "unknown"
        state = _load_or_create_state(path)
        event = _next_event(state, current_version)
        if event is None:
            return InstallTelemetryResult(
                state_path=path,
                endpoint_configured=bool(endpoint),
                skipped_reason="already_uploaded",
            )

        if not endpoint:
            state["last_skip_reason"] = "endpoint_empty"
            _write_state(path, state)
            return InstallTelemetryResult(
                state_path=path,
                endpoint_configured=False,
                event=event,
                skipped_reason="endpoint_empty",
            )

        now = _utc_now()
        payload = _build_payload(
            state,
            event=event,
            current_version=current_version,
            sent_at=now,
        )
        state["last_attempt_at"] = now
        state["last_skip_reason"] = None
        uploaded, error = _post_payload(endpoint, payload, timeout=DEFAULT_TIMEOUT_SECONDS)
        if uploaded:
            state["last_success_at"] = now
            state["last_error"] = None
            state["uploaded_install"] = True
            _add_uploaded_version(state, current_version)
        else:
            state["last_error"] = error or "upload_failed"

        _write_state(path, state)
        return InstallTelemetryResult(
            state_path=path,
            endpoint_configured=True,
            event=event,
            sent=True,
            uploaded=uploaded,
            error=error,
        )
    except Exception as exc:  # pragma: no cover - defensive startup guard
        log.debug("Install telemetry skipped: %s", exc, exc_info=True)
        return InstallTelemetryResult(
            state_path=path,
            endpoint_configured=bool(endpoint),
            skipped_reason="error",
            error=str(exc),
        )


def _state_path(*, config: Any | None, explicit: str | Path | None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    configured_state_dir = getattr(config, "state_dir", None)
    if isinstance(configured_state_dir, str) and configured_state_dir.strip():
        root = Path(configured_state_dir.strip()).expanduser()
    else:
        root = default_opensquilla_home() / "state"
    return root / TELEMETRY_STATE_FILE


def _telemetry_disabled() -> bool:
    value = os.environ.get(TELEMETRY_DISABLED_ENV, "").strip().lower()
    return value in _TRUE_VALUES


def _endpoint() -> str:
    return os.environ.get(TELEMETRY_ENDPOINT_ENV, DEFAULT_TELEMETRY_ENDPOINT).strip()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_or_create_state(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _normalize_state(data)
        except (json.JSONDecodeError, OSError):
            log.debug("Install telemetry state unreadable; replacing", exc_info=True)
    return _new_state()


def _new_state() -> dict[str, Any]:
    now = _utc_now()
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "install_id": str(uuid.uuid4()),
        "first_seen_at": now,
        "uploaded_install": False,
        "uploaded_versions": [],
        "last_attempt_at": None,
        "last_success_at": None,
        "last_error": None,
        "last_skip_reason": None,
    }


def _normalize_state(data: dict[str, Any]) -> dict[str, Any]:
    state = dict(data)
    install_id = state.get("install_id")
    if not isinstance(install_id, str) or not install_id.strip():
        state["install_id"] = str(uuid.uuid4())
    first_seen = state.get("first_seen_at")
    if not isinstance(first_seen, str) or not first_seen.strip():
        state["first_seen_at"] = _utc_now()
    uploaded_versions = state.get("uploaded_versions")
    if not isinstance(uploaded_versions, list):
        uploaded_versions = []
    state["uploaded_versions"] = [
        str(item) for item in uploaded_versions if isinstance(item, str) and item.strip()
    ]
    state["schema_version"] = TELEMETRY_SCHEMA_VERSION
    state["uploaded_install"] = bool(state.get("uploaded_install"))
    state.setdefault("last_attempt_at", None)
    state.setdefault("last_success_at", None)
    state.setdefault("last_error", None)
    state.setdefault("last_skip_reason", None)
    return state


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
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


def _next_event(state: dict[str, Any], current_version: str) -> str | None:
    if not state.get("uploaded_install", False):
        return "install"
    uploaded_versions = set(state.get("uploaded_versions") or [])
    if current_version not in uploaded_versions:
        return "version_seen"
    return None


def _add_uploaded_version(state: dict[str, Any], current_version: str) -> None:
    versions = list(state.get("uploaded_versions") or [])
    if current_version not in versions:
        versions.append(current_version)
    state["uploaded_versions"] = versions


def _build_payload(
    state: dict[str, Any],
    *,
    event: str,
    current_version: str,
    sent_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "event": event,
        "install_id": state["install_id"],
        "opensquilla_version": current_version,
        "install_method": _detect_install_method(),
        "os": _safe_str(platform.system()),
        "os_version": _safe_str(platform.release()),
        "architecture": _safe_str(platform.machine()),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "first_seen_at": state["first_seen_at"],
        "sent_at": sent_at,
    }


def _safe_str(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _detect_install_method() -> str:
    explicit = os.environ.get(TELEMETRY_INSTALL_METHOD_ENV, "").strip().lower()
    if explicit in {"pip", "source", "docker", "desktop", "unknown"}:
        return explicit
    if os.environ.get("OPENSQUILLA_DESKTOP", "").strip().lower() in _TRUE_VALUES:
        return "desktop"
    if os.environ.get("OPENSQUILLA_RUNNING_IN_CONTAINER", "").strip().lower() in _TRUE_VALUES:
        return "docker"
    if Path("/.dockerenv").exists():
        return "docker"
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / ".git").exists():
        return "source"
    return "pip"


def _post_payload(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> tuple[bool, str | None]:
    try:
        import httpx

        with httpx.Client(timeout=timeout) as client:
            response = client.post(endpoint, json=payload)
        if response.status_code in _SUCCESS_STATUS_CODES:
            return True, None
        return False, f"http_status_{response.status_code}"
    except Exception as exc:
        log.debug("Install telemetry upload failed: %s", exc)
        return False, str(exc)
