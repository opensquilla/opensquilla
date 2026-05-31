from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.contracts import attachments
from opensquilla.gateway import attachment_ingest


def test_attachment_policy_is_shared_with_gateway_ingest() -> None:
    assert attachment_ingest.ALLOWED_MEDIA_TYPES is attachments.ALLOWED_MEDIA_TYPES
    assert attachment_ingest.MAX_ATTACHMENT_BYTES == attachments.MAX_ATTACHMENT_BYTES
    assert (
        attachment_ingest.attachment_size_limit_for_mime("application/pdf", staged=True)
        == attachments.MAX_STAGED_PDF_BYTES
    )


def test_channel_attachment_io_does_not_import_gateway_policy() -> None:
    imports = _imports_from(Path("src/opensquilla/channels/_attachment_io.py"))

    assert "opensquilla.gateway.attachment_ingest" not in imports
    assert "opensquilla.contracts.attachments" in imports


def test_policy_only_consumers_do_not_import_gateway_ingest() -> None:
    for relative in [
        "src/opensquilla/cli/attachments.py",
        "src/opensquilla/engine/runtime.py",
        "src/opensquilla/gateway/uploads.py",
    ]:
        imports = _imports_from(Path(relative))
        assert "opensquilla.gateway.attachment_ingest" not in imports
        assert "opensquilla.contracts.attachments" in imports


def _imports_from(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
