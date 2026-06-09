from __future__ import annotations

from opensquilla.tools.builtin.code_exec import _append_code_exec_sandbox_network_hint
from opensquilla.tools.builtin.shell import (
    _SANDBOX_NETWORK_HINT,
    _append_sandbox_network_hint,
)


def test_sandbox_network_hint_is_appended_to_dns_failures() -> None:
    output = "curl: (6) Could not resolve host: export.arxiv.org\n"

    hinted = _append_sandbox_network_hint(output)

    assert _SANDBOX_NETWORK_HINT in hinted
    assert "sandbox_network" in hinted
    assert "managed proxy" in hinted
    assert "http_request" not in hinted
    assert "web_fetch" not in hinted


def test_sandbox_network_hint_is_not_duplicated() -> None:
    output = f"getaddrinfo failed\n{_SANDBOX_NETWORK_HINT}\n"

    hinted = _append_sandbox_network_hint(output)

    assert hinted.count(_SANDBOX_NETWORK_HINT) == 1


def test_code_exec_hint_uses_combined_stdout_and_stderr() -> None:
    stdout = (
        "urllib.error.URLError: "
        "<urlopen error [Errno -3] Temporary failure in name resolution>\n"
    )
    stderr = "cleanup warning\n"

    hinted = _append_code_exec_sandbox_network_hint(stdout=stdout, stderr=stderr)

    assert "cleanup warning" in hinted
    assert _SANDBOX_NETWORK_HINT in hinted
