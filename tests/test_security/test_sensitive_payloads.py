from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.safety.sensitive_payloads import (
    sensitive_body_block,
    sensitive_body_marker,
    sensitive_url_marker,
)

ROOT = Path(__file__).resolve().parents[2]
CODE_EXEC = ROOT / "src/opensquilla/tools/builtin/code_exec.py"
MEDIA = ROOT / "src/opensquilla/tools/builtin/media.py"
SHELL = ROOT / "src/opensquilla/tools/builtin/shell.py"
WEB_FETCH = ROOT / "src/opensquilla/tools/builtin/web_fetch.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def test_sensitive_payload_helpers_detect_body_url_and_render_block() -> None:
    assert sensitive_body_marker("API_KEY=secret") == "secret_assignment"
    assert sensitive_url_marker("https://example.com/path?token=secret") == "sensitive_query"
    blocked = sensitive_body_block("web_search", "secret_assignment")
    assert "sensitive_payload" in blocked
    assert "web_search" in blocked


def test_tools_no_longer_import_sensitive_payloads_from_web_adapter() -> None:
    forbidden = {
        ("opensquilla.tools.builtin.web", "_sensitive_body_block"),
        ("opensquilla.tools.builtin.web", "_sensitive_body_marker"),
        ("opensquilla.tools.builtin.web", "_sensitive_url_marker"),
    }

    for path in (CODE_EXEC, MEDIA, SHELL, WEB_FETCH):
        assert not (forbidden & _imports_from(path))
        assert (
            "opensquilla.safety.sensitive_payloads",
            "sensitive_url_marker",
        ) in _imports_from(path)
