from __future__ import annotations

from pathlib import Path


def test_workspace_root_is_rwx_and_cache_is_child(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_roots import workspace_write_roots

    roots = workspace_write_roots(tmp_path)

    assert roots.workspace == tmp_path
    assert tmp_path in roots.rwx_roots
    assert tmp_path / ".opensquilla-cache" in roots.rwx_roots


def test_python_runtime_roots_are_rx(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_roots import runtime_rx_roots

    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    roots = runtime_rx_roots(python)

    assert python.parent in roots
    assert tmp_path / ".venv" in roots


def test_python_runtime_roots_include_external_venv_base_runtime(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_roots import runtime_rx_roots

    python = tmp_path / "project" / ".venv" / "Scripts" / "python.exe"
    base_runtime = tmp_path / "runtime" / "python"
    python.parent.mkdir(parents=True)
    base_runtime.mkdir(parents=True)

    roots = runtime_rx_roots(python, base_prefix=base_runtime)

    assert python.parent in roots
    assert tmp_path / "project" / ".venv" in roots
    assert base_runtime in roots


def test_windows_platform_rx_roots_from_env(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_roots import windows_platform_rx_roots

    windows_root = tmp_path / "Windows"
    program_data = tmp_path / "ProgramData"
    program_files = tmp_path / "Program Files"
    program_files_x86 = tmp_path / "Program Files (x86)"

    roots = windows_platform_rx_roots(
        {
            "SystemRoot": str(windows_root),
            "ProgramData": str(program_data),
            "ProgramFiles": str(program_files),
            "ProgramFiles(x86)": str(program_files_x86),
        }
    )

    assert windows_root in roots
    assert windows_root / "System32" in roots
    assert program_data in roots
    assert program_files in roots
    assert program_files_x86 in roots


def test_process_executable_rx_roots_include_executable_and_platform_roots(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend.windows_default_roots import process_executable_rx_roots

    windows_root = tmp_path / "Windows"
    powershell_root = windows_root / "System32" / "WindowsPowerShell" / "v1.0"
    powershell = powershell_root / "powershell.exe"

    roots = process_executable_rx_roots(
        (str(powershell), "-Command", "Write-Output ok"),
        {"SystemRoot": str(windows_root)},
    )

    assert powershell_root in roots
    assert powershell_root.parent in roots
    assert windows_root in roots
    assert windows_root / "System32" in roots


def test_opensquilla_state_protected_roots_are_sensitive(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_roots import (
        opensquilla_protected_roots,
        windows_sensitive_marker,
    )

    roots = opensquilla_protected_roots(tmp_path)

    assert tmp_path / ".opensquilla" / "sandbox" in roots
    assert tmp_path / ".opensquilla" / "sandbox-secrets" in roots
    assert (
        windows_sensitive_marker(
            tmp_path / ".opensquilla" / "sandbox" / "setup_marker.json",
            home=tmp_path,
        )
        == "opensquilla_sandbox_state"
    )


def test_windows_user_secret_roots_are_sensitive(tmp_path: Path) -> None:
    from opensquilla.sandbox.backend.windows_default_roots import windows_sensitive_marker

    assert windows_sensitive_marker(tmp_path / ".ssh" / "id_rsa", home=tmp_path) == "user_secret"
    assert (
        windows_sensitive_marker(tmp_path / ".aws" / "credentials", home=tmp_path)
        == "user_secret"
    )
    assert (
        windows_sensitive_marker(tmp_path / ".config" / "gh" / "hosts.yml", home=tmp_path)
        == "user_secret"
    )


def test_windows_system_roots_are_write_sensitive() -> None:
    from opensquilla.sandbox.backend.windows_default_roots import windows_sensitive_marker

    assert (
        windows_sensitive_marker(Path("C:/Windows/System32"), home=Path("C:/Users/me"))
        == "windows_system"
    )
    assert (
        windows_sensitive_marker(Path("C:/Program Files/App"), home=Path("C:/Users/me"))
        == "windows_system"
    )
