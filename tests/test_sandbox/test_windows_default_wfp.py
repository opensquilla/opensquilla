from __future__ import annotations

import sys

import pytest

from opensquilla.sandbox.backend.windows_default_wfp import WFP_FILTER_SPECS


def test_wfp_filter_specs_have_unique_keys_and_names() -> None:
    keys = [spec.key for spec in WFP_FILTER_SPECS]
    names = [spec.name for spec in WFP_FILTER_SPECS]

    assert len(keys) == len(set(keys))
    assert len(names) == len(set(names))


def test_wfp_filter_specs_cover_dns_icmp_and_smb() -> None:
    names = {spec.name for spec in WFP_FILTER_SPECS}

    assert "opensquilla_wfp_icmp_connect_v4" in names
    assert "opensquilla_wfp_icmp_connect_v6" in names
    assert "opensquilla_wfp_dns_53_v4" in names
    assert "opensquilla_wfp_dns_853_v6" in names
    assert "opensquilla_wfp_smb_445_v4" in names
    assert "opensquilla_wfp_smb_139_v6" in names


def test_wfp_filter_specs_cover_loopback_non_proxy_ports() -> None:
    from opensquilla.sandbox.backend.windows_default_wfp import wfp_filter_specs

    specs = wfp_filter_specs((48123,))
    by_name = {spec.name: spec for spec in specs}

    assert "opensquilla_wfp_loopback_udp_v4" in by_name
    assert "opensquilla_wfp_loopback_udp_v6" in by_name
    assert by_name["opensquilla_wfp_loopback_tcp_except_proxy_v4"].conditions == (
        "user",
        "loopback",
        "tcp",
        "remote_port_not:48123",
    )
    assert by_name["opensquilla_wfp_loopback_tcp_except_proxy_v6"].conditions == (
        "user",
        "loopback",
        "tcp",
        "remote_port_not:48123",
    )


def test_wfp_filter_specs_are_scoped_to_user_condition() -> None:
    assert all("user" in spec.conditions for spec in WFP_FILTER_SPECS)


def test_install_wfp_filters_calls_native_installer(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_wfp as mod

    calls: list[tuple[str, tuple[int, ...]]] = []
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(
        mod,
        "_install_wfp_filters_native",
        lambda sid, *, allowed_proxy_ports=(48123,): calls.append((sid, allowed_proxy_ports)),
    )

    mod.install_wfp_filters_for_user("S-1-5-21-100-200-300-400")

    assert calls == [("S-1-5-21-100-200-300-400", (48123,))]


def test_native_installer_orchestrates_persistent_filters(monkeypatch) -> None:
    from opensquilla.sandbox.backend import windows_default_wfp as mod

    events: list[tuple[str, str]] = []

    class _FakeUserMatchCondition:
        blob = object()

        def __init__(self, native, sid) -> None:
            events.append(("user", sid))

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            events.append(("user_cleanup", ""))

    class _FakeNative:
        def open_engine(self):
            events.append(("open", "engine"))
            return "engine"

        def close_engine(self, engine) -> None:
            events.append(("close", engine))

        def begin_transaction(self, engine) -> None:
            events.append(("begin", engine))

        def commit_transaction(self, engine) -> None:
            events.append(("commit", engine))

        def abort_transaction(self, engine) -> None:
            events.append(("abort", engine))

        def ensure_provider(self, engine) -> None:
            events.append(("provider", engine))

        def ensure_sublayer(self, engine) -> None:
            events.append(("sublayer", engine))

        def delete_filter_if_present(self, engine, key) -> None:
            events.append(("delete", engine))

        def add_filter(self, engine, spec, user_condition) -> None:
            events.append(("add", spec.name))

    monkeypatch.setattr(mod, "_WfpNative", _FakeNative)
    monkeypatch.setattr(mod, "_UserMatchCondition", _FakeUserMatchCondition)
    monkeypatch.setattr(mod, "_guid", lambda value: value)

    mod._install_wfp_filters_native(
        "S-1-5-21-100-200-300-400",
        allowed_proxy_ports=(48123,),
    )

    specs = mod.wfp_filter_specs((48123,))

    assert events[:4] == [
        ("open", "engine"),
        ("begin", "engine"),
        ("provider", "engine"),
        ("sublayer", "engine"),
    ]
    assert events.count(("delete", "engine")) == len(specs)
    assert [event for event in events if event[0] == "add"] == [
        ("add", spec.name) for spec in specs
    ]
    assert events[-3:] == [
        ("user_cleanup", ""),
        ("commit", "engine"),
        ("close", "engine"),
    ]
    assert ("abort", "engine") not in events


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows WFP only")
def test_wfp_native_installer_rejects_empty_sid() -> None:
    from opensquilla.sandbox.backend.windows_default_wfp import install_wfp_filters_for_user

    with pytest.raises(Exception, match="offline SID"):
        install_wfp_filters_for_user("")
