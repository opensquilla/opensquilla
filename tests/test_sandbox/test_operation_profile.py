from __future__ import annotations

from opensquilla.sandbox.operation_profile import classify_command, package_bundle_for_manager


def test_classify_python_package_install() -> None:
    profile = classify_command(("python", "-m", "pip", "install", "requests"))
    assert profile.name == "package_install"
    assert profile.package_manager == "python"
    assert profile.needs_network is True


def test_classify_node_package_install() -> None:
    profile = classify_command(("npm", "install"))
    assert profile.name == "package_install"
    assert profile.package_manager == "node"


def test_classify_alternate_node_package_installers() -> None:
    for command in (("pnpm", "install"), ("yarn", "install")):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "node"
        assert profile.needs_network is True


def test_classify_rust_package_install() -> None:
    profile = classify_command(("cargo", "build"))
    assert profile.name == "package_install"
    assert profile.package_manager == "rust"
    assert profile.needs_network is True


def test_classify_go_package_install() -> None:
    profile = classify_command(("go", "mod", "download"))
    assert profile.name == "package_install"
    assert profile.package_manager == "go"
    assert profile.needs_network is True


def test_classify_url_fetch() -> None:
    profile = classify_command(("curl", "https://example.com/index.html"))
    assert profile.name == "network_fetch"
    assert profile.requested_domains == ("example.com",)


def test_classify_destructive_shell() -> None:
    profile = classify_command(("rm", "-rf", "dist"))
    assert profile.name == "destructive_shell"
    assert profile.high_impact is True


def test_classify_destructive_shell_without_flags() -> None:
    for command in (("rm", "dist"), ("del", "dist"), ("erase", "dist")):
        profile = classify_command(command)
        assert profile.name == "destructive_shell"
        assert profile.high_impact is True


def test_classify_workspace_read() -> None:
    profile = classify_command(("rg", "needle"))
    assert profile.name == "workspace_read"


def test_unknown_shell_is_conservative() -> None:
    profile = classify_command(("sh", "-lc", "complex $(unknown)"))
    assert profile.name == "unknown_shell"


def test_package_bundle_for_manager() -> None:
    assert package_bundle_for_manager("python") == "python-package-install"
    assert package_bundle_for_manager("node") == "node-package-install"
    assert package_bundle_for_manager("rust") == "rust-package-install"
    assert package_bundle_for_manager("go") == "go-package-install"
    assert package_bundle_for_manager(None) is None
    assert package_bundle_for_manager("unknown") is None
