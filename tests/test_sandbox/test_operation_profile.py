from __future__ import annotations

from opensquilla.sandbox.operation_profile import classify_command, package_bundle_for_manager


def test_classify_python_package_install() -> None:
    for command in (
        ("python", "-m", "pip", "install", "requests"),
        ("pip", "install", "requests"),
    ):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "python"
        assert profile.needs_network is True


def test_classify_python_package_install_variants() -> None:
    for command in (
        ("python3", "-m", "pip", "install", "requests"),
        ("python3.11", "-m", "pip", "install", "requests"),
        ("/usr/bin/python3", "-m", "pip", "install", "requests"),
    ):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "python"
        assert profile.needs_network is True


def test_pip_help_install_is_not_package_install() -> None:
    profile = classify_command(("pip", "help", "install"))
    assert profile.name == "unknown_shell"
    assert profile.package_manager is None


def test_classify_node_package_install() -> None:
    profile = classify_command(("npm", "install"))
    assert profile.name == "package_install"
    assert profile.package_manager == "node"


def test_classify_alternate_node_package_installers() -> None:
    for command in (
        ("npm", "ci"),
        ("pnpm", "install"),
        ("pnpm", "add", "vite"),
        ("yarn", "install"),
        ("yarn", "add", "vite"),
    ):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "node"
        assert profile.needs_network is True


def test_npm_run_install_is_not_package_install() -> None:
    profile = classify_command(("npm", "run", "install"))
    assert profile.name == "unknown_shell"
    assert profile.package_manager is None


def test_classify_rust_package_install() -> None:
    for command in (
        ("cargo", "build"),
        ("cargo", "test"),
        ("cargo", "install", "cargo-edit"),
    ):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "rust"
        assert profile.needs_network is True


def test_cargo_help_install_is_not_package_install() -> None:
    profile = classify_command(("cargo", "help", "install"))
    assert profile.name == "unknown_shell"
    assert profile.package_manager is None


def test_classify_go_package_install() -> None:
    for command in (
        ("go", "get", "example.com/mod"),
        ("go", "install", "example.com/cmd/tool"),
        ("go", "mod", "download"),
        ("go", "mod", "tidy"),
    ):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "go"
        assert profile.needs_network is True


def test_go_help_commands_are_not_package_install() -> None:
    for command in (("go", "help", "install"), ("go", "help", "get")):
        profile = classify_command(command)
        assert profile.name == "unknown_shell"
        assert profile.package_manager is None


def test_classify_url_fetch() -> None:
    profile = classify_command(("curl", "https://example.com/index.html"))
    assert profile.name == "url_fetch"
    assert profile.requested_domains == ("example.com",)


def test_classify_url_fetch_normalizes_url_punctuation() -> None:
    for url in (
        "https://example.com?x=1",
        "https://example.com#fragment",
        "https://example.com).",
        "<https://example.com>",
        "`https://example.com`",
        "https://example.com],",
    ):
        profile = classify_command(("curl", url))
        assert profile.name == "url_fetch"
        assert profile.requested_domains == ("example.com",)


def test_classify_destructive_shell() -> None:
    profile = classify_command(("rm", "-rf", "dist"))
    assert profile.name == "destructive_shell"
    assert profile.high_impact is True


def test_destructive_command_tracks_obvious_write_target_paths() -> None:
    profile = classify_command(("rm", "-f", "/tmp/outside.txt"))

    assert profile.name == "destructive_shell"
    assert profile.high_impact is True
    assert profile.requested_write_paths == ("/tmp/outside.txt",)


def test_top_level_destructive_command_dominates_url_detection() -> None:
    profile = classify_command(("rm", "-rf", "https://example.com"))
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


def test_workspace_read_tracks_obvious_path_arguments() -> None:
    profile = classify_command(("ls", "/tmp/outside"))
    assert profile.name == "workspace_read"
    assert profile.requested_paths == ("/tmp/outside",)


def test_copy_command_tracks_source_read_and_destination_write_paths() -> None:
    profile = classify_command(
        ("cp", "/workspace-src/opensquilla/LICENSE", "/workspace/opensquilla-license.txt")
    )

    assert profile.name == "path_transfer"
    assert profile.requested_paths == ("/workspace-src/opensquilla/LICENSE",)
    assert profile.requested_write_paths == ("/workspace/opensquilla-license.txt",)


def test_move_command_treats_source_and_destination_as_write_paths() -> None:
    profile = classify_command(("mv", "/tmp/outside.txt", "/workspace/outside.txt"))

    assert profile.name == "path_transfer"
    assert profile.requested_paths == ()
    assert profile.requested_write_paths == ("/tmp/outside.txt", "/workspace/outside.txt")


def test_shell_wrapper_preserves_workspace_read_path_arguments() -> None:
    profile = classify_command(("sh", "-lc", "ls /tmp/outside"))
    assert profile.name == "workspace_read"
    assert profile.requested_paths == ("/tmp/outside",)


def test_shell_wrapper_preserves_windows_read_path_arguments() -> None:
    profile = classify_command(("sh", "-lc", r"ls C:\workspace\outside"))
    assert profile.name == "workspace_read"
    assert profile.requested_paths == (r"C:\workspace\outside",)


def test_shell_wrapper_preserves_copy_source_and_destination_paths() -> None:
    profile = classify_command(
        ("sh", "-lc", "cp /workspace-src/opensquilla/LICENSE /workspace/license.txt")
    )

    assert profile.name == "path_transfer"
    assert profile.requested_paths == ("/workspace-src/opensquilla/LICENSE",)
    assert profile.requested_write_paths == ("/workspace/license.txt",)


def test_shell_wrapper_preserves_windows_copy_paths() -> None:
    profile = classify_command(
        (
            "sh",
            "-lc",
            r"cp C:\workspace\outside\notes.txt C:\workspace\target\notes.txt",
        )
    )

    assert profile.name == "path_transfer"
    assert profile.requested_paths == (r"C:\workspace\outside\notes.txt",)
    assert profile.requested_write_paths == (
        r"C:\workspace\target\notes.txt",
    )


def test_shell_wrapper_preserves_move_write_paths() -> None:
    profile = classify_command(("sh", "-lc", "mv /tmp/outside.txt /workspace/outside.txt"))

    assert profile.name == "path_transfer"
    assert profile.requested_paths == ()
    assert profile.requested_write_paths == ("/tmp/outside.txt", "/workspace/outside.txt")


def test_unknown_shell_is_conservative() -> None:
    profile = classify_command(("sh", "-lc", "complex $(unknown)"))
    assert profile.name == "unknown_shell"


def test_shell_wrapper_with_url_detects_network() -> None:
    profile = classify_command(("sh", "-lc", "curl https://example.com"))
    assert profile.name == "url_fetch"
    assert profile.needs_network is True
    assert profile.requested_domains == ("example.com",)


def test_shell_wrapper_preserves_paths_when_network_command_follows() -> None:
    profile = classify_command(("sh", "-lc", "cat /mnt/data/input && curl https://example.com"))

    assert profile.name == "url_fetch"
    assert profile.needs_network is True
    assert profile.requested_domains == ("example.com",)
    assert profile.requested_paths == ("/mnt/data/input",)


def test_shell_wrapper_with_url_text_is_not_network() -> None:
    profile = classify_command(("sh", "-lc", "echo https://example.com"))
    assert profile.name == "unknown_shell"
    assert profile.needs_network is False


def test_shell_wrapper_with_package_install_detects_network() -> None:
    profile = classify_command(("sh", "-lc", "pip install requests"))
    assert profile.name == "package_install"
    assert profile.needs_network is True
    assert profile.package_manager == "python"


def test_shell_wrapper_preserves_obvious_destructive_impact() -> None:
    profile = classify_command(("sh", "-lc", "rm -rf dist && curl https://example.com"))
    assert profile.name == "destructive_shell"
    assert profile.high_impact is True
    assert profile.needs_network is True
    assert profile.requested_domains == ("example.com",)


def test_shell_wrapper_preserves_destructive_write_target_paths() -> None:
    profile = classify_command(("sh", "-lc", "rm -f /tmp/outside.txt"))

    assert profile.name == "destructive_shell"
    assert profile.high_impact is True
    assert profile.requested_write_paths == ("/tmp/outside.txt",)


def test_shell_wrapper_finds_c_option_after_long_options() -> None:
    profile = classify_command(("bash", "--norc", "-c", "rm -rf dist"))
    assert profile.name == "destructive_shell"
    assert profile.high_impact is True


def test_shell_wrapper_detects_adjacent_separator_destructive_command() -> None:
    profile = classify_command(("sh", "-lc", "echo ok;rm -rf dist"))
    assert profile.name == "destructive_shell"
    assert profile.high_impact is True


def test_shell_wrapper_detects_env_prefixed_destructive_command() -> None:
    profile = classify_command(("sh", "-lc", "X=1 rm -rf dist"))
    assert profile.name == "destructive_shell"
    assert profile.high_impact is True


def test_package_bundle_for_manager() -> None:
    assert package_bundle_for_manager("python") == "python-package-install"
    assert package_bundle_for_manager("node") == "node-package-install"
    assert package_bundle_for_manager("rust") == "rust-package-install"
    assert package_bundle_for_manager("go") == "go-package-install"
    assert package_bundle_for_manager(None) is None
    assert package_bundle_for_manager("unknown") is None
