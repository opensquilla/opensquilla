from __future__ import annotations

from opensquilla.sandbox.operation_profile import (
    classify_command,
    package_bundle_for_manager,
    shell_command_approval_variants,
)


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
        ("python.cmd", "-m", "pip", "install", "requests"),
        ("uv", "pip", "install", "--no-cache-dir", "requests"),
    ):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "python"
        assert profile.needs_network is True


def test_classify_python_package_install_in_powershell_call_operator() -> None:
    script = (
        '& "D:\\opensquilla\\.tmp\\proj\\.venv\\Scripts\\python.exe" '
        "-m pip install --no-cache-dir httpx[http2] pendulum"
    )
    for command in (
        ("sh", "-lc", script),
        ("powershell", "-Command", script),
        ("pwsh", "-c", script),
    ):
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == "python"
        assert profile.needs_network is True


def test_classify_python_package_install_in_windows_shell_host_wrapper() -> None:
    script = (
        '& "D:\\opensquilla\\.tmp\\proj\\.venv\\Scripts\\python.exe" '
        "-m pip install --no-cache-dir httpx[http2] pendulum"
    )
    profile = classify_command(
        (
            "D:\\opensquilla\\.venv\\Scripts\\python.exe",
            "-c",
            "windows sandbox shell host expects powershell path and command",
            "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            script,
        )
    )

    assert profile.name == "package_install"
    assert profile.package_manager == "python"
    assert profile.needs_network is True


def test_classify_rewritten_python_package_install_in_windows_shell_host_wrapper() -> None:
    script = (
        "Invoke-OpenSquillaPythonProcess "
        "-FilePath 'D:\\opensquilla\\.tmp\\proj\\.venv\\Scripts\\python.exe' "
        "-Arguments @('-m','pip','install','--no-cache-dir','httpx[http2]','pendulum')"
    )
    profile = classify_command(
        (
            "D:\\opensquilla\\.venv\\Scripts\\python.exe",
            "-c",
            "windows sandbox shell host expects powershell path and command",
            "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            script,
        )
    )

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


def test_classify_node_package_install_behind_timeout_wrapper() -> None:
    profile = classify_command(("timeout", "30", "npm", "install", "lodash"))

    assert profile.name == "package_install"
    assert profile.package_manager == "node"
    assert profile.needs_network is True


def test_npm_run_install_is_not_package_install() -> None:
    profile = classify_command(("npm", "run", "install"))
    assert profile.name == "unknown_shell"
    assert profile.package_manager is None


def test_classify_host_software_managers_require_host_access() -> None:
    for command in (
        ("winget", "install", "Tencent.QQ.NT"),
        ("winget", "list"),
        ("sh", "-lc", "winget install Tencent.QQ.NT"),
        ("powershell", "-NoProfile", "-Command", "winget install Tencent.QQ.NT"),
        ("sh", "-lc", 'cmd /c "winget install Tencent.QQ.NT"'),
        ("choco", "upgrade", "git", "-y"),
        ("scoop", "install", "7zip"),
        ("brew", "install", "ripgrep"),
        ("apt-get", "install", "-y", "tmux"),
        ("sudo", "dnf", "install", "git"),
        ("msiexec", "/i", "C:\\Users\\me\\Downloads\\app.msi", "/qn"),
    ):
        profile = classify_command(command)
        assert profile.host_effect == "software_management"


def test_shell_command_approval_variants_expose_wrapped_host_command() -> None:
    variants = shell_command_approval_variants(
        'powershell -NoProfile -Command "winget install Tencent.QQ.NT"'
    )

    assert "winget install Tencent.QQ.NT" in variants


def test_classify_host_installer_artifacts_require_host_access() -> None:
    for command in (
        ("C:\\Users\\me\\Downloads\\QQNTSetup.exe", "/S"),
        ("Start-Process", "C:\\Users\\me\\Downloads\\tool.appinstaller", "-Wait"),
        ("open", "/Users/me/Downloads/App.pkg"),
    ):
        profile = classify_command(command)
        assert profile.host_effect == "software_management"


def test_classify_installer_downloads_require_host_access() -> None:
    for command in (
        (
            "curl.exe",
            "-L",
            "-o",
            "DingTalkSetup.exe",
            "https://dtapp-pub.dingtalk.com/desktop/Win/Release/DingTalkSetup.exe",
        ),
        (
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Invoke-WebRequest "
                "https://dtapp-pub.dingtalk.com/desktop/Win/Release/DingTalkSetup.exe "
                "-OutFile DingTalkSetup.exe"
            ),
        ),
        (
            "sh",
            "-lc",
            (
                "cmd /c \"curl.exe -L -o DingTalkSetup.exe "
                "https://dtapp-pub.dingtalk.com/desktop/Win/Release/DingTalkSetup.exe\""
            ),
        ),
        (
            "sh",
            "-lc",
            (
                "cmd /c \"cd /d C:\\Users\\lrk\\.opensquilla\\workspace && "
                "C:\\Windows\\System32\\curl.exe -L -o DingTalkSetup.exe "
                "https://dtapp-pub.dingtalk.com/desktop/Win/Release/DingTalkSetup.exe\""
            ),
        ),
    ):
        profile = classify_command(command)
        assert profile.name == "url_fetch"
        assert profile.needs_network is True
        assert profile.host_effect == "software_management"


def test_classify_host_environment_probes_require_host_access() -> None:
    for command in (
        ("where", "winget"),
        ("Get-Command", "winget", "-ErrorAction", "SilentlyContinue"),
        ("Test-Path", "C:\\Program Files\\Tencent\\QQ"),
        ("Test-Path", "C:\\Users\\me\\AppData\\Local\\Microsoft\\WindowsApps\\winget.exe"),
        ("reg", "query", "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"),
    ):
        profile = classify_command(command)
        assert profile.host_effect == "host_probe"


def test_classify_windows_installed_app_queries_require_host_access() -> None:
    for command in (
        ("Get-WmiObject", "Win32_Product"),
        ("Get-CimInstance", "Win32_Product"),
        ("Get-Package", "-Name", "DingTalk"),
        ("Get-AppxPackage", "-Name", "DingTalk"),
        (
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-ItemProperty HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
        ),
        (
            "sh",
            "-lc",
            (
                "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\"
                "CurrentVersion\\Uninstall\\* "
                "| Where-Object { $_.DisplayName -like '*DingTalk*' }"
            ),
        ),
        (
            "sh",
            "-lc",
            (
                "Get-ItemProperty HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\"
                "CurrentVersion\\Uninstall\\* "
                "| Where-Object { $_.DisplayName -like '*DingTalk*' }"
            ),
        ),
        ("Get-ChildItem", "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"),
    ):
        profile = classify_command(command)
        assert profile.host_effect == "host_probe"


def test_classify_windows_uninstall_actions_require_host_access() -> None:
    cases = {
        (
            "Start-Process",
            "C:\\Program Files\\DingTalk\\uninst.exe",
            "-Wait",
        ): "software_management",
        (
            "Start-Process",
            "-FilePath",
            "C:\\Program Files (x86)\\DingDing\\uninst.exe",
            "-Wait",
            "-NoNewWindow",
        ): "software_management",
        (
            "Start-Process",
            "C:\\Program Files\\DingTalk\\unins000.exe",
            "-Wait",
        ): "software_management",
        ("C:\\Program Files\\DingTalk\\uninstall.exe", "/S"): "software_management",
        ("sh", "-lc", '& "C:\\Program Files (x86)\\DingDing\\uninst.exe"'): "software_management",
        ("cmd", "/c", "C:\\Program Files\\DingTalk\\uninst.exe /S"): "software_management",
        ("Uninstall-Package", "-Name", "DingTalk", "-Force"): "software_management",
        ("Remove-AppxPackage", "DingTalk"): "software_management",
        ("control", "appwiz.cpl"): "software_management",
        ("Start-Process", "appwiz.cpl"): "software_management",
        (
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-WmiObject Win32_Product -Filter \"Name like '%DingTalk%'\").Uninstall()",
        ): "software_management",
    }
    for command, expected in cases.items():
        profile = classify_command(command)
        assert profile.host_effect == expected


def test_classify_host_process_management_requires_host_access() -> None:
    cases = {
        ("Get-Process", "DingTalk"): "host_probe",
        ("Stop-Process", "-Name", "DingTalk", "-Force"): "process_management",
        ("tasklist", "/FI", "IMAGENAME eq DingTalk.exe"): "host_probe",
        ("taskkill", "/IM", "DingTalk.exe", "/F"): "process_management",
    }
    for command, expected in cases.items():
        profile = classify_command(command)
        assert profile.host_effect == expected


def test_classify_installed_app_cleanup_requires_host_access() -> None:
    cases = {
        ("Remove-Item", "C:\\Program Files\\DingTalk", "-Recurse", "-Force"): "software_management",
        ("Remove-Item", "HKCU:\\Software\\DingTalk", "-Recurse", "-Force"): "registry_write",
        ("New-Item", "HKCU:\\Software\\DingTalk", "-Force"): "registry_write",
    }
    for command, expected in cases.items():
        profile = classify_command(command)
        assert profile.host_effect == expected


def test_classify_host_services_registry_and_system_settings_require_host_access() -> None:
    cases = {
        ("sc.exe", "create", "DemoSvc", "binPath=", "demo.exe"): "service_management",
        ("New-Service", "-Name", "DemoSvc", "-BinaryPathName", "demo.exe"): "service_management",
        ("systemctl", "restart", "docker"): "service_management",
        ("launchctl", "load", "~/Library/LaunchAgents/demo.plist"): "service_management",
        ("reg", "add", "HKCU\\Software\\Demo", "/v", "Enabled", "/d", "1"): "registry_write",
        ("Set-ItemProperty", "HKCU:\\Software\\Demo", "Enabled", "1"): "registry_write",
        ("Set-ExecutionPolicy", "RemoteSigned", "-Scope", "CurrentUser"): "system_settings",
        ("netsh", "advfirewall", "set", "allprofiles", "state", "off"): "system_settings",
        ("New-NetFirewallRule", "-DisplayName", "Demo", "-Action", "Allow"): "system_settings",
        ("setx", "PATH", "%PATH%;C:\\Tools"): "system_settings",
        ("pnputil", "/add-driver", "driver.inf", "/install"): "driver_management",
        (
            "dism",
            "/Online",
            "/Enable-Feature",
            "/FeatureName:VirtualMachinePlatform",
        ): "driver_management",
        ("bcdedit", "/set", "hypervisorlaunchtype", "auto"): "driver_management",
        ("wsl", "--install"): "driver_management",
    }
    for command, expected in cases.items():
        profile = classify_command(command)
        assert profile.host_effect == expected


def test_classify_global_developer_tool_installs_require_host_access() -> None:
    for command in (
        ("npm", "install", "-g", "typescript"),
        ("pnpm", "add", "--global", "vite"),
        ("pipx", "install", "black"),
        ("python", "-m", "pip", "install", "--user", "black"),
        ("gem", "install", "bundler"),
        ("cargo", "install", "cargo-edit"),
        ("go", "install", "example.com/cmd/tool@latest"),
        ("dotnet", "tool", "install", "-g", "dotnet-ef"),
    ):
        profile = classify_command(command)
        assert profile.host_effect == "global_tool_install"


def test_classify_project_dependency_installs_do_not_require_host_access() -> None:
    for command in (
        ("npm", "install"),
        ("pnpm", "add", "vite"),
        ("python", "-m", "pip", "install", "requests"),
        ("uv", "pip", "install", "requests"),
        ("cargo", "build"),
        ("go", "mod", "download"),
    ):
        profile = classify_command(command)
        assert profile.host_effect is None


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


def test_shell_wrapper_tracks_windows_delete_paths() -> None:
    for command in (
        r'del "C:\Users\me\outside-sandbox-smoke.txt"',
        r"Remove-Item C:\Users\me\outside-sandbox-smoke.txt -Force",
        r"Remove-Item -LiteralPath C:\Users\me\outside-sandbox-smoke.txt -Force",
    ):
        profile = classify_command(("sh", "-lc", command))

        assert profile.name == "destructive_shell"
        assert profile.high_impact is True
        assert profile.requested_write_paths == (
            r"C:\Users\me\outside-sandbox-smoke.txt",
        )


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


def test_classify_python_environment_creation() -> None:
    for command in (
        ("python", "-m", "venv", "/tmp/proj/.venv"),
        ("python3", "-m", "venv", "/tmp/proj/.venv"),
        ("virtualenv", "/tmp/proj/.venv"),
        ("uv", "venv", "/tmp/proj/.venv"),
        ("python", "-m", "venv", ".venv"),
        ("virtualenv", ".venv"),
        ("uv", "venv", ".venv"),
    ):
        profile = classify_command(command)
        assert profile.name == "create_env"
        assert profile.package_manager == "python"
        assert profile.requested_write_paths == (
            "/tmp/proj/.venv" if "/tmp/proj/.venv" in command else ".venv",
        )


def test_classify_python_environment_creation_with_prompt_option_and_relative_target() -> None:
    profile = classify_command(("python", "-m", "venv", "--prompt", "name", ".venv"))

    assert profile.name == "create_env"
    assert profile.package_manager == "python"
    assert profile.requested_write_paths == (".venv",)


def test_python_environment_create_help_or_version_is_not_classified_as_create_env() -> None:
    for command in (
        ("python", "-m", "venv", "--help"),
        ("python", "-m", "venv", "--version"),
        ("virtualenv", "--help"),
        ("uv", "venv", "--help"),
        ("virtualenv", "-V"),
    ):
        profile = classify_command(command)

        assert profile.name != "create_env"


def test_python_environment_create_with_version_named_target() -> None:
    for command in (
        ("python", "-m", "venv", "version"),
        ("virtualenv", "version"),
        ("uv", "venv", "version"),
    ):
        profile = classify_command(command)

        assert profile.name == "create_env"
        assert profile.package_manager == "python"
        assert profile.requested_write_paths == ("version",)


def test_classify_additional_package_managers() -> None:
    cases = {
        ("poetry", "install"): "python",
        ("rye", "sync"): "python",
        ("pixi", "install"): "python",
        ("bun", "install"): "node",
        ("composer", "install"): "php",
        ("mvn", "package"): "java",
        ("gradle", "build"): "java",
        ("./gradlew", "build"): "java",
    }
    for command, manager in cases.items():
        profile = classify_command(command)
        assert profile.name == "package_install"
        assert profile.package_manager == manager
        assert profile.needs_network is True


def test_shell_wrapper_merges_create_env_and_install_packages() -> None:
    profile = classify_command(
        (
            "sh",
            "-lc",
            "python -m venv /tmp/proj/.venv && "
            "/tmp/proj/.venv/bin/python -m pip install requests",
        )
    )

    assert profile.name == "package_install"
    assert profile.package_manager == "python"
    assert profile.requested_write_paths == ("/tmp/proj/.venv",)


def test_shell_wrapper_merges_relative_create_env_and_install_packages() -> None:
    profile = classify_command(
        (
            "sh",
            "-lc",
            "python -m venv .venv && .venv/bin/python -m pip install requests",
        )
    )

    assert profile.name == "package_install"
    assert profile.package_manager == "python"
    assert profile.requested_write_paths == (".venv",)


def test_package_bundle_for_manager() -> None:
    assert package_bundle_for_manager("python") == "python-package-install"
    assert package_bundle_for_manager("node") == "node-package-install"
    assert package_bundle_for_manager("rust") == "rust-package-install"
    assert package_bundle_for_manager("go") == "go-package-install"
    assert package_bundle_for_manager("java") == "java-package-install"
    assert package_bundle_for_manager("php") == "php-package-install"
    assert package_bundle_for_manager(None) is None
    assert package_bundle_for_manager("unknown") is None
