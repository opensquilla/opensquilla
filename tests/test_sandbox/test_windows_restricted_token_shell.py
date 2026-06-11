from __future__ import annotations

import sys


def test_windows_restricted_token_backend_uses_direct_powershell_argv() -> None:
    from opensquilla.tools.builtin import shell

    backend = type("Backend", (), {"name": "windows_restricted_token"})()
    runtime = type("Runtime", (), {"backend": backend})()

    argv = shell._sandbox_shell_backend_argv("echo ok", runtime)

    assert argv[0].lower().endswith("powershell.exe")
    assert argv[0] != sys.executable
    assert "-Command" in argv
    assert "echo ok" in argv
