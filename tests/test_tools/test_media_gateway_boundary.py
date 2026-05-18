"""Architecture guards for media tools decoupling."""

from __future__ import annotations

import ast
from pathlib import Path

MEDIA_TOOL = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "opensquilla"
    / "tools"
    / "builtin"
    / "media.py"
)
SSRF_TOOL = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "opensquilla"
    / "tools"
    / "ssrf.py"
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def test_media_tool_does_not_import_gateway() -> None:
    offenders = sorted(
        module
        for module in _imported_modules(MEDIA_TOOL)
        if module == "opensquilla.gateway" or module.startswith("opensquilla.gateway.")
    )

    assert offenders == []


def test_media_tool_source_does_not_reference_gateway_package() -> None:
    assert "opensquilla.gateway" not in MEDIA_TOOL.read_text(encoding="utf-8")


def test_media_tool_uses_shared_ssrf_validator_for_remote_urls() -> None:
    imports = _imports_from(MEDIA_TOOL)

    assert ("opensquilla.tools.ssrf", "validate_http_url_scheme") in imports
    assert ("opensquilla.tools.ssrf", "validate_http_url_for_fetch") in imports
    assert "socket" not in _imported_modules(MEDIA_TOOL)


def test_ssrf_tool_exposes_shared_http_scheme_validator() -> None:
    source = SSRF_TOOL.read_text(encoding="utf-8")
    assert "validate_http_url_scheme" in source
    assert "validate_http_url_for_fetch" in source
