from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from opensquilla.observability import install_telemetry as telemetry
from opensquilla.observability import network_policy

TEST_ENDPOINT = "https://telemetry.example.test/v1/install"
PRODUCTION_ENDPOINT = "https://telemetry.opensquilla.ai/v1/install"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _enable_telemetry_for_test(monkeypatch):
    monkeypatch.delenv(
        network_policy.NETWORK_OBSERVABILITY_DISABLED_ENV,
        raising=False,
    )
    monkeypatch.delenv(telemetry.TELEMETRY_DISABLED_ENV, raising=False)
    monkeypatch.delenv(
        network_policy.LEGACY_UPDATE_CHECK_DISABLED_ENV,
        raising=False,
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv(telemetry.TELEMETRY_TESTING_ENV, raising=False)


def _set_stable_sources(
    monkeypatch,
    *,
    macs: list[str] | None = None,
    ips: list[str] | None = None,
) -> None:
    monkeypatch.setattr(telemetry, "_collect_mac_address_candidates", lambda: macs or [])
    monkeypatch.setattr(telemetry, "_collect_ip_address_candidates", lambda: ips or [])


def test_default_endpoint_uploads_install_once_and_dedupes(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.delenv(telemetry.TELEMETRY_ENDPOINT_ENV, raising=False)
    _set_stable_sources(monkeypatch, macs=["02:00:00:00:00:01"])
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
    assert state["install_id"] == telemetry._stable_install_id("mac", ["020000000001"])
    assert state["install_id_source"] == "stable-v2-mac"
    assert state["uploaded_install"] is True
    assert state["uploaded_versions"] == ["1.0.0"]


def test_endpoint_empty_creates_install_id_without_upload(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.delenv(telemetry.TELEMETRY_ENDPOINT_ENV, raising=False)
    monkeypatch.setattr(telemetry, "DEFAULT_TELEMETRY_ENDPOINT", "")
    _set_stable_sources(monkeypatch, macs=["02:00:00:00:00:02"])
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
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    _set_stable_sources(monkeypatch, macs=["02:00:00:00:00:03"])
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
        "ci_environment",
    }
    assert payload["ci_environment"] is False
    state = _load(state_path)
    assert state["uploaded_install"] is True
    assert state["uploaded_versions"] == ["1.0.0"]


def test_new_version_uploads_version_seen(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    _set_stable_sources(monkeypatch, macs=["02:00:00:00:00:04"])
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
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_DISABLED_ENV, "true")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"

    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert result.disabled is True
    assert result.sent is False
    assert result.skipped_reason == "disabled"
    assert not state_path.exists()


def test_privacy_config_disable_skips_without_creating_state(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"
    config = SimpleNamespace(
        privacy=SimpleNamespace(disable_network_observability=True),
    )

    result = telemetry.collect_install_telemetry(
        config=config,
        state_path=state_path,
        version="1.0.0",
    )

    assert result.disabled is True
    assert result.sent is False
    assert result.skipped_reason == "disabled"
    assert not state_path.exists()


def test_github_actions_env_skips_without_creating_state(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"

    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert result.disabled is True
    assert result.sent is False
    assert result.skipped_reason == "environment:GITHUB_ACTIONS"
    assert not state_path.exists()


def test_pytest_current_test_env_skips_without_creating_state(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_file.py::test_name (call)")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"

    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert result.disabled is True
    assert result.sent is False
    assert result.skipped_reason == "environment:PYTEST_CURRENT_TEST"
    assert not state_path.exists()


def test_opensquilla_testing_env_skips_without_creating_state(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_TESTING_ENV, "true")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    state_path = tmp_path / "install_telemetry.json"

    result = telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    assert result.disabled is True
    assert result.sent is False
    assert result.skipped_reason == "environment:OPENSQUILLA_TESTING"
    assert not state_path.exists()


def test_payload_marks_ci_environment_when_detected(monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    payload = telemetry._build_payload(
        {
            "install_id": "stable-install-id",
            "first_seen_at": "2026-06-29T00:00:00Z",
        },
        event="install",
        current_version="1.0.0",
        sent_at="2026-06-29T00:00:01Z",
    )

    assert payload["ci_environment"] is True


def test_upload_failure_does_not_mark_install_uploaded(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    _set_stable_sources(monkeypatch, macs=["02:00:00:00:00:05"])
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
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.delenv(telemetry.TELEMETRY_INSTALL_METHOD_ENV, raising=False)
    monkeypatch.setenv("OPENSQUILLA_DESKTOP", "1")

    assert telemetry._detect_install_method() == "desktop"


def test_mac_addresses_generate_stable_install_id(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    _set_stable_sources(
        monkeypatch,
        macs=["02:00:00:00:00:0A", "ff:ff:ff:ff:ff:ff", "01:00:5e:00:00:fb"],
        ips=["10.0.0.5"],
    )
    state_path = tmp_path / "install_telemetry.json"
    calls: list[dict[str, Any]] = []

    def fake_post(
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> tuple[bool, str | None]:
        calls.append(payload)
        return True, None

    monkeypatch.setattr(telemetry, "_post_payload", fake_post)

    telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    expected = telemetry._stable_install_id("mac", ["02000000000a"])
    state = _load(state_path)
    assert state["install_id"] == expected
    assert state["install_id_source"] == "stable-v2-mac"
    assert calls[0]["install_id"] == expected


def test_mac_address_order_does_not_change_install_id():
    first = telemetry._normalized_mac_addresses(
        ["02:00:00:00:00:0b", "02:00:00:00:00:0a"]
    )
    second = telemetry._normalized_mac_addresses(
        ["02:00:00:00:00:0A", "02:00:00:00:00:0B"]
    )

    assert first == ["02000000000a", "02000000000b"]
    assert telemetry._stable_install_id("mac", first) == telemetry._stable_install_id(
        "mac",
        second,
    )


def test_ip_fallback_generates_stable_install_id_when_no_usable_mac(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, TEST_ENDPOINT)
    _set_stable_sources(
        monkeypatch,
        macs=["00:00:00:00:00:00", "01:00:5e:00:00:fb"],
        ips=["127.0.0.1", "169.254.10.20", "10.0.0.8"],
    )
    state_path = tmp_path / "install_telemetry.json"

    monkeypatch.setattr(telemetry, "_post_payload", lambda *args, **kwargs: (True, None))

    telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    state = _load(state_path)
    assert state["install_id"] == telemetry._stable_install_id("ip", ["10.0.0.8"])
    assert state["install_id_source"] == "stable-v2-ip"


def test_loopback_endpoint_host_does_not_influence_install_id(tmp_path, monkeypatch):
    _enable_telemetry_for_test(monkeypatch)
    monkeypatch.setenv(
        telemetry.TELEMETRY_ENDPOINT_ENV,
        "http://127.0.0.1:8787/v1/install",
    )
    _set_stable_sources(monkeypatch, macs=[], ips=["127.0.0.1", "10.0.0.9"])
    state_path = tmp_path / "install_telemetry.json"
    calls: list[dict[str, Any]] = []

    def fake_post(
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> tuple[bool, str | None]:
        calls.append(payload)
        return True, None

    monkeypatch.setattr(telemetry, "_post_payload", fake_post)

    telemetry.collect_install_telemetry(state_path=state_path, version="1.0.0")

    expected = telemetry._stable_install_id("ip", ["10.0.0.9"])
    assert _load(state_path)["install_id"] == expected
    assert calls[0]["install_id"] == expected
