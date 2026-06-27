from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opensquilla.observability import install_telemetry as telemetry

TEST_ENDPOINT = "https://telemetry.example.test/v1/install"
PRODUCTION_ENDPOINT = "https://telemetry.opensquilla.ai/v1/install"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_endpoint_uploads_install_once_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.delenv(telemetry.TELEMETRY_ENDPOINT_ENV, raising=False)
    monkeypatch.delenv(telemetry.TELEMETRY_DISABLED_ENV, raising=False)
    state_path = tmp_path / "install_telemetry.json"
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> tuple[bool, str | None]:
        calls.append((endpoint, payload))
        return True, None

    monkeypatch.setattr(telemetry, "_post_payload", fake_post)

    first = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")
    second = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert first.sent is True
    assert first.uploaded is True
    assert first.event == "install"
    assert second.sent is False
    assert second.skipped_reason == "already_uploaded"
    assert len(calls) == 1
    endpoint, payload = calls[0]
    assert endpoint == PRODUCTION_ENDPOINT
    assert payload["event"] == "install"
    assert payload["opensquilla_version"] == "1.0.0"
    state = _load(state_path)
    assert state["uploaded_install"] is True
    assert state["uploaded_versions"] == ["1.0.0"]


def test_endpoint_empty_creates_install_id_without_upload(tmp_path, monkeypatch):
    monkeypatch.delenv(telemetry.TELEMETRY_ENDPOINT_ENV, raising=False)
    monkeypatch.delenv(telemetry.TELEMETRY_DISABLED_ENV, raising=False)
    monkeypatch.setattr(telemetry, "DEFAULT_TELEMETRY_ENDPOINT", "")
    state_path = tmp_path / "install_telemetry.json"

    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert result.sent is False
    assert result.uploaded is False
    assert result.event == "install"
    assert result.skipped_reason == "endpoint_empty"
    state = _load(state_path)
    assert state["install_id"]
    assert state["uploaded_install"] is False
    assert state["uploaded_versions"] == []
    assert state["last_skip_reason"] == "endpoint_empty"


def test_configured_endpoint_uploads_install_once_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> tuple[bool, str | None]:
        calls.append((endpoint, payload))
        return True, None

    monkeypatch.setattr(telemetry, "_post_payload", fake_post)

    first = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")
    second = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert first.sent is True
    assert first.uploaded is True
    assert first.event == "install"
    assert second.sent is False
    assert second.skipped_reason == "already_uploaded"
    assert len(calls) == 1
    endpoint, payload = calls[0]
    assert endpoint == TEST_ENDPOINT
    assert payload["event"] == "install"
    assert payload["opensquilla_version"] == "1.0.0"
    assert set(payload) == {
        "schema_version",
        "event",
        "install_id",
        "opensquilla_version",
        "install_method",
        "os",
        "os_version",
        "architecture",
        "python_version",
        "first_seen_at",
        "sent_at",
    }
    state = _load(state_path)
    assert state["uploaded_install"] is True
    assert state["uploaded_versions"] == ["1.0.0"]


def test_new_version_uploads_version_seen(tmp_path, monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"
    events: list[str] = []

    def fake_post(
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> tuple[bool, str | None]:
        events.append(str(payload["event"]))
        return True, None

    monkeypatch.setattr(telemetry, "_post_payload", fake_post)

    telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")
    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.1.0")

    assert result.sent is True
    assert result.uploaded is True
    assert result.event == "version_seen"
    assert events == ["install", "version_seen"]
    assert _load(state_path)["uploaded_versions"] == ["1.0.0", "1.1.0"]


def test_disabled_env_skips_without_creating_state(tmp_path, monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_DISABLED_ENV, "true")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"

    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert result.disabled is True
    assert result.sent is False
    assert result.skipped_reason == "disabled"
    assert not state_path.exists()


def test_upload_failure_does_not_mark_install_uploaded(tmp_path, monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"

    def fake_post(
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> tuple[bool, str | None]:
        return False, "network_down"

    monkeypatch.setattr(telemetry, "_post_payload", fake_post)

    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert result.sent is True
    assert result.uploaded is False
    assert result.error == "network_down"
    state = _load(state_path)
    assert state["uploaded_install"] is False
    assert state["uploaded_versions"] == []
    assert state["last_error"] == "network_down"


def test_desktop_env_sets_install_method(monkeypatch):
    monkeypatch.delenv(telemetry.TELEMETRY_INSTALL_METHOD_ENV, raising=False)
    monkeypatch.setenv("OPENSQUILLA_DESKTOP", "1")

    assert telemetry._detect_install_method() == "desktop"
