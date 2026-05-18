from __future__ import annotations

import ast
import base64
import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import httpx
import pytest

from opensquilla.tools.builtin import web
from opensquilla.tools.types import ToolError, UnsupportedURLSchemeError

HttpRequestCallable = Callable[..., Awaitable[str]]
WEB_TOOL = Path(__file__).resolve().parents[2] / "src/opensquilla/tools/builtin/web.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def test_http_request_routes_url_scheme_validation_through_ssrf_boundary() -> None:
    imports = _imports_from(WEB_TOOL)

    assert ("opensquilla.tools.ssrf", "validate_http_url_scheme") in imports
    assert ("opensquilla.tools.ssrf", "validate_http_url_for_fetch") not in imports
    assert ("urllib.parse", "urlparse") not in imports


def _original_http_request() -> HttpRequestCallable:
    return cast(HttpRequestCallable, web.http_request.__wrapped__.__wrapped__)


def _patch_response(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, **kwargs: object) -> httpx.Response:
            return response

    monkeypatch.setattr(web.httpx, "AsyncClient", FakeAsyncClient)


@pytest.mark.asyncio
async def test_http_request_preserves_non_http_scheme_error_message() -> None:
    with pytest.raises(UnsupportedURLSchemeError, match="ftp://example.test/file"):
        await _original_http_request()(url="ftp://example.test/file")


@pytest.mark.asyncio
async def test_http_request_returns_body_base64_for_octet_stream_invalid_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"\xff\xfe\x00PDF"
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            headers={"content-type": "application/octet-stream"},
            request=httpx.Request("GET", "https://example.test/file"),
        ),
    )

    payload = json.loads(await _original_http_request()(url="https://example.test/file"))

    assert payload["content_type"] == "application/octet-stream"
    assert payload["body"] is None
    assert base64.b64decode(payload["body_base64"]) == raw
    assert payload["body_base64_truncated"] is False


@pytest.mark.asyncio
async def test_http_request_returns_text_body_for_json_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=b'{"ok":true}',
            headers={"content-type": "application/json; charset=utf-8"},
            request=httpx.Request("GET", "https://example.test/data"),
        ),
    )

    payload = json.loads(await _original_http_request()(url="https://example.test/data"))

    assert payload["body"] == '{"ok":true}'
    assert base64.b64decode(payload["body_base64"]) == b'{"ok":true}'
    assert payload["body_truncated"] is False


@pytest.mark.asyncio
async def test_http_request_keeps_body_base64_for_misleading_text_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"\xff\xfe\x00PDF"
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            headers={"content-type": "text/plain; charset=utf-8"},
            request=httpx.Request("GET", "https://example.test/mislabelled"),
        ),
    )

    payload = json.loads(await _original_http_request()(url="https://example.test/mislabelled"))

    assert payload["body"] is not None
    assert "\ufffd" in payload["body"]
    assert base64.b64decode(payload["body_base64"]) == raw


@pytest.mark.asyncio
async def test_http_request_uses_body_base64_when_content_type_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"\x00\x01\x02"
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            request=httpx.Request("GET", "https://example.test/blob"),
        ),
    )

    payload = json.loads(await _original_http_request()(url="https://example.test/blob"))

    assert payload["content_type"] == ""
    assert payload["body"] is None
    assert base64.b64decode(payload["body_base64"]) == raw


@pytest.mark.asyncio
async def test_http_request_saves_large_binary_response_without_returning_base64(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = b"x" * 1_000_001
    monkeypatch.chdir(tmp_path)
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            headers={"content-type": "application/octet-stream"},
            request=httpx.Request("GET", "https://example.test/large"),
        ),
    )

    payload = json.loads(await _original_http_request()(url="https://example.test/large"))

    digest = hashlib.sha256(raw).hexdigest()
    saved_path = tmp_path / ".fetch" / f"{digest}.bin"
    assert Path(payload["path"]) == saved_path
    assert saved_path.read_bytes() == raw
    assert payload["size"] == len(raw)
    assert payload["sha256"] == digest
    assert payload["body_saved"] is True
    assert payload["body"] is None
    assert payload["body_base64"] is None
    assert payload["body_base64_truncated"] is False


@pytest.mark.asyncio
async def test_http_request_saves_large_text_response_without_returning_full_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = b"<feed>" + (b"a" * 60_000) + b"</feed>"
    monkeypatch.chdir(tmp_path)
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            headers={"content-type": "application/xml"},
            request=httpx.Request("GET", "https://example.test/feed"),
        ),
    )

    payload = json.loads(await _original_http_request()(url="https://example.test/feed"))

    digest = hashlib.sha256(raw).hexdigest()
    saved_path = tmp_path / ".fetch" / f"{digest}.bin"
    assert Path(payload["path"]) == saved_path
    assert saved_path.read_bytes() == raw
    assert payload["size"] == len(raw)
    assert payload["sha256"] == digest
    assert payload["body_saved"] is True
    assert payload["body"] is None
    assert payload["body_base64"] is None
    assert payload["body_truncated"] is False
    assert payload["body_base64_truncated"] is False
    assert payload["body_preview"].startswith("<feed>")
    assert len(payload["body_preview"]) == 10_000
    assert payload["body_omitted_reason"] == "saved_to_file"


@pytest.mark.asyncio
async def test_http_request_output_path_saves_inside_fetch_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = b'{"ok":true}'
    monkeypatch.chdir(tmp_path)
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "https://example.test/data"),
        ),
    )

    payload = json.loads(
        await _original_http_request()(
            url="https://example.test/data",
            output_path="raw.json",
        )
    )

    saved_path = tmp_path / ".fetch" / "raw.json"
    assert Path(payload["path"]) == saved_path
    assert saved_path.read_bytes() == raw
    assert payload["body_saved"] is True
    assert payload["body"] is None
    assert payload["body_base64"] is None


@pytest.mark.asyncio
async def test_http_request_output_path_rejects_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = b'{"ok":true}'
    monkeypatch.chdir(tmp_path)
    existing_path = tmp_path / ".fetch" / "raw.json"
    existing_path.parent.mkdir()
    existing_path.write_bytes(b"keep")
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "https://example.test/data"),
        ),
    )

    with pytest.raises(ToolError, match="output_path already exists"):
        await _original_http_request()(
            url="https://example.test/data",
            output_path="raw.json",
        )

    assert existing_path.read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_http_request_output_path_rejects_fetch_directory_escape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=b"escape",
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", "https://example.test/data"),
        ),
    )

    with pytest.raises(ToolError, match="output_path must stay inside"):
        await _original_http_request()(
            url="https://example.test/data",
            output_path="../escape.txt",
        )
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.asyncio
async def test_http_request_reuses_content_hash_path_for_repeated_large_fetches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = b"x" * 60_000
    monkeypatch.chdir(tmp_path)
    _patch_response(
        monkeypatch,
        httpx.Response(
            200,
            content=raw,
            headers={"content-type": "application/octet-stream"},
            request=httpx.Request("GET", "https://example.test/blob"),
        ),
    )

    first = json.loads(await _original_http_request()(url="https://example.test/blob"))
    second = json.loads(await _original_http_request()(url="https://example.test/blob"))

    assert first["path"] == second["path"]
    assert Path(first["path"]).read_bytes() == raw
