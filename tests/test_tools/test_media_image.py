from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from opensquilla.tools.builtin import media
from opensquilla.tools.types import ToolContext, current_tool_context


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
