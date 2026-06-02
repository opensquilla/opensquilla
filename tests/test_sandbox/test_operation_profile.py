from __future__ import annotations

from opensquilla.sandbox.operation_profile import classify_command


def test_classify_python_package_install() -> None:
    profile = classify_command(("python", "-m", "pip", "install", "requests"))
    assert profile.name == "package_install"
    assert profile.package_manager == "python"
    assert profile.needs_network is True


def test_classify_node_package_install() -> None:
    profile = classify_command(("npm", "install"))
    assert profile.name == "package_install"
    assert profile.package_manager == "node"


def test_classify_url_fetch() -> None:
    profile = classify_command(("curl", "https://example.com/index.html"))
    assert profile.name == "network_fetch"
    assert profile.requested_domains == ("example.com",)


def test_classify_destructive_shell() -> None:
    profile = classify_command(("rm", "-rf", "dist"))
    assert profile.name == "destructive_shell"
    assert profile.high_impact is True


def test_unknown_shell_is_conservative() -> None:
    profile = classify_command(("sh", "-lc", "complex $(unknown)"))
    assert profile.name == "unknown_shell"
