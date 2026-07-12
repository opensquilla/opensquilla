from __future__ import annotations

import io
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from opensquilla.tools.builtin import media
from opensquilla.tools.ssrf import environment_proxy_url
from opensquilla.tools.types import SafeToolError, ToolContext, ToolError, current_tool_context


def _write_pdf(path: Path) -> None:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(240, 160))
    pdf.drawString(32, 120, "Accuracy")
    pdf.rect(40, 30, 40, 70, fill=1)
    pdf.rect(100, 30, 40, 95, fill=1)
    pdf.save()
    path.write_bytes(buffer.getvalue())


@pytest.mark.asyncio
async def test_image_tool_renders_workspace_pdf_before_vision_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "figure.pdf"
    _write_pdf(pdf_path)
    seen: dict[str, str] = {}

    async def fake_vision(b64_data: str, media_type: str, prompt: str) -> str:
        seen["media_type"] = media_type
        seen["prompt"] = prompt
        seen["payload_prefix"] = b64_data[:16]
        return "rendered chart"

    monkeypatch.setattr(media, "_call_vision_provider", fake_vision)

    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    try:
        result = json.loads(await media.image("/workspace/figure.pdf", "describe the chart"))
    finally:
        current_tool_context.reset(token)

    assert result["description"] == "rendered chart"
    assert result["path"] == "/workspace/figure.pdf"
    assert seen == {
        "media_type": "image/png",
        "prompt": "describe the chart",
        "payload_prefix": seen["payload_prefix"],
    }
    assert seen["payload_prefix"]


@pytest.mark.asyncio
async def test_image_tool_reports_attachment_display_name_as_safe_path_error(
    tmp_path: Path,
) -> None:
    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    try:
        with pytest.raises(SafeToolError) as exc_info:
            await media.image(
                "ab367eca88278bd6905ff705e3fee0b2907b86fbda389d9ed3f9c9d86f4603f5.png",
                "describe this image",
            )
    finally:
        current_tool_context.reset(token)

    message = exc_info.value.user_message
    assert "not accessible by the image tool" in message
    assert "local file path or HTTP(S) URL" in message
    assert "chat attachment" in message


@pytest.mark.asyncio
async def test_image_tool_reports_unsupported_format_as_safe_error(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("not an image", encoding="utf-8")

    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    try:
        with pytest.raises(SafeToolError) as exc_info:
            await media.image("notes.txt", "describe this image")
    finally:
        current_tool_context.reset(token)

    assert "Unsupported image format" in exc_info.value.user_message


@pytest.mark.asyncio
async def test_image_tool_reports_corrupt_image_as_safe_error(tmp_path: Path) -> None:
    source = tmp_path / "broken.png"
    source.write_bytes(b"not a png")

    token = current_tool_context.set(ToolContext(workspace_dir=str(tmp_path)))
    try:
        with pytest.raises(SafeToolError) as exc_info:
            await media.image("broken.png", "describe this image")
    finally:
        current_tool_context.reset(token)

    assert "corrupt or unreadable" in exc_info.value.user_message


_INTERNAL_SECRET = b"INTERNAL-METADATA-SECRET-169.254.169.254"
_PUBLIC_IP = "93.184.216.34"


class _SecretHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib API name
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(_INTERNAL_SECRET)))
        self.end_headers()
        self.wfile.write(_INTERNAL_SECRET)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture()
def loopback_server():
    server = HTTPServer(("127.0.0.1", 0), _SecretHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_fetch_image_url_pins_vetted_ip_against_dns_rebind(
    monkeypatch: pytest.MonkeyPatch, loopback_server: int
) -> None:
    port = loopback_server
    counter = {"n": 0}
    real = socket.getaddrinfo

    def rebinding_getaddrinfo(host, req_port, *args, **kwargs):
        host_str = host.decode("ascii") if isinstance(host, bytes) else host
        if host_str != "rebind.test":
            return real(host, req_port, *args, **kwargs)
        counter["n"] += 1
        # First resolution (the guard) sees a public IP; every later resolution
        # rebinds to loopback — the connection must never follow it.
        if counter["n"] == 1:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_IP, req_port or 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)

    try:
        image_bytes, _ = await media._fetch_image_url(f"http://rebind.test:{port}/metadata.png")
    except ToolError:
        return
    assert image_bytes != _INTERNAL_SECRET


@pytest.mark.asyncio
async def test_fetch_image_url_resolves_relative_redirect_against_logical_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    requested: list[str] = []

    class RedirectingClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> RedirectingClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            requested.append(url)
            if len(requested) == 1:
                return httpx.Response(
                    302,
                    headers={"location": "/image.png"},
                    request=httpx.Request("GET", "https://93.184.216.34/start"),
                )
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=b"png-bytes",
                request=httpx.Request("GET", "https://93.184.216.34/image.png"),
            )

    monkeypatch.setattr(media, "validate_http_url_for_fetch", lambda url: ["93.184.216.34"])
    monkeypatch.setattr(httpx, "AsyncClient", RedirectingClient)
    monkeypatch.setattr(
        "opensquilla.tools.ssrf.pinned_transport", lambda *args, **kwargs: object()
    )

    image_bytes, media_type = await media._fetch_image_url(
        "https://images.example.test/start"
    )

    assert requested == [
        "https://images.example.test/start",
        "https://images.example.test/image.png",
    ]
    assert image_bytes == b"png-bytes"
    assert media_type == "image/png"


@pytest.mark.asyncio
async def test_fetch_image_url_uses_opted_in_environment_proxy_with_pinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API name
            seen["path"] = self.path
            seen["host"] = self.headers.get("Host", "")
            if self.path.startswith("http://127.0.0.1:"):
                payload = b"proxied-png"
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(502)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    proxy = HTTPServer(("127.0.0.1", 0), ProxyHandler)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    port = int(proxy.server_address[1])
    try:
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "NO_PROXY",
            "no_proxy",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv("REQUEST_METHOD", raising=False)
        monkeypatch.setenv("OPENSQUILLA_TRUST_ENV", "1")
        proxy_url = f"http://127.0.0.1:{port}"
        target_url = f"http://proxy-target.test:{port}/image.png"
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        assert environment_proxy_url(target_url) == proxy_url
        monkeypatch.setattr(media, "validate_http_url_for_fetch", lambda url: ["127.0.0.1"])

        image_bytes, media_type = await media._fetch_image_url(target_url)
    finally:
        proxy.shutdown()
        proxy.server_close()

    assert image_bytes == b"proxied-png"
    assert media_type == "image/png"
    assert seen["path"].startswith(f"http://127.0.0.1:{port}/")
    assert seen["host"] == f"proxy-target.test:{port}"
