from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from opensquilla.artifacts import (
    ARTIFACT_THUMBNAIL_NAME,
    ArtifactStore,
    artifact_payload,
)


class _FakeSessionManager:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    async def get_session(self, session_key: str) -> object | None:
        if session_key == "agent:main:webchat:ok":
            return SimpleNamespace(session_id=self.session_id)
        return None


def _app(tmp_path: Path):
    pytest.importorskip("starlette.testclient")
    from starlette.applications import Starlette

    from opensquilla.gateway.artifacts import register_artifact_routes
    from opensquilla.gateway.config import AttachmentsConfig, AuthConfig, GatewayConfig
    from opensquilla.gateway.middleware import AuthMiddleware

    config = GatewayConfig(
        auth=AuthConfig(mode="token", token="secret"),
        attachments=AttachmentsConfig(media_root=str(tmp_path)),
    )
    app = Starlette(debug=False)
    register_artifact_routes(
        app,
        config=config,
        session_manager=_FakeSessionManager("session-1"),
    )
    app.add_middleware(AuthMiddleware, config=config)
    return app


def _png_bytes(width: int = 1024, height: int = 768) -> bytes:
    image = Image.new("RGB", (width, height), color=(180, 40, 90))
    # Add a little structure so the encoder produces a non-trivial-sized image.
    for x in range(0, width, 8):
        for y in range(0, height, 8):
            image.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _publish_image(tmp_path: Path):
    payload = _png_bytes()
    ref = ArtifactStore(tmp_path).publish_bytes(
        payload,
        session_id="session-1",
        session_key="agent:main:webchat:ok",
        name="render.png",
        mime="image/png",
        source="image_generate",
    )
    return ref, payload


def test_publishing_image_creates_smaller_webp_thumbnail(tmp_path: Path) -> None:
    ref, payload = _publish_image(tmp_path)

    assert ref.has_thumbnail is True
    thumb_path = ArtifactStore(tmp_path).thumbnail_path_for(ref)
    assert thumb_path.name == ARTIFACT_THUMBNAIL_NAME
    assert thumb_path.exists()

    thumb_bytes = thumb_path.read_bytes()
    assert thumb_bytes[:4] == b"RIFF"  # webp container magic
    assert b"WEBP" in thumb_bytes[:16]
    assert len(thumb_bytes) < len(payload)

    # The thumbnail must fit within the 512x512 bounding box, preserving aspect.
    with Image.open(io.BytesIO(thumb_bytes)) as decoded:
        assert decoded.width <= 512
        assert decoded.height <= 512
        assert max(decoded.width, decoded.height) == 512


def test_artifact_payload_exposes_thumbnail_url_only_when_present(tmp_path: Path) -> None:
    ref, _payload = _publish_image(tmp_path)

    payload = artifact_payload(ref)
    assert payload["thumbnail_url"] == f"{payload['download_url']}?variant=thumb"
    assert payload["thumbnail_url"] == f"/api/v1/artifacts/{ref.id}?variant=thumb"


def test_thumbnail_served_at_variant_thumb_and_is_smaller(tmp_path: Path) -> None:
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    ref, _payload = _publish_image(tmp_path)

    with TestClient(_app(tmp_path)) as client:
        full = client.get(
            f"/api/v1/artifacts/{ref.id}?sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )
        thumb = client.get(
            f"/api/v1/artifacts/{ref.id}?variant=thumb&sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )
        thumb_head = client.head(
            f"/api/v1/artifacts/{ref.id}?variant=thumb&sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )

    assert full.status_code == 200
    assert full.headers["content-type"].startswith("image/png")

    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/webp")
    assert thumb.content[:4] == b"RIFF"
    assert int(thumb.headers["content-length"]) < int(full.headers["content-length"])

    assert thumb_head.status_code == 200
    assert thumb_head.headers["content-type"].startswith("image/webp")


def test_non_image_artifact_has_no_thumbnail_and_falls_back(tmp_path: Path) -> None:
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    ref = ArtifactStore(tmp_path).publish_bytes(
        b"plain text deliverable contents",
        session_id="session-1",
        session_key="agent:main:webchat:ok",
        name="notes.txt",
        mime="text/plain",
        source="publish_artifact",
    )

    assert ref.has_thumbnail is False
    assert not ArtifactStore(tmp_path).thumbnail_path_for(ref).exists()
    assert "thumbnail_url" not in artifact_payload(ref)

    with TestClient(_app(tmp_path)) as client:
        thumb = client.get(
            f"/api/v1/artifacts/{ref.id}?variant=thumb&sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )

    # No thumbnail sidecar: the request transparently falls back to the full file.
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("text/plain")
    assert thumb.content == b"plain text deliverable contents"


def test_corrupt_image_still_publishes_without_thumbnail(tmp_path: Path) -> None:
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    # Claims to be a PNG but the bytes are not decodable as an image.
    ref = ArtifactStore(tmp_path).publish_bytes(
        b"\x89PNG\r\n\x1a\n not a real image body",
        session_id="session-1",
        session_key="agent:main:webchat:ok",
        name="broken.png",
        mime="image/png",
        source="image_generate",
    )

    assert ref.has_thumbnail is False
    assert not ArtifactStore(tmp_path).thumbnail_path_for(ref).exists()
    assert "thumbnail_url" not in artifact_payload(ref)

    with TestClient(_app(tmp_path)) as client:
        # The artifact is fully published and downloadable despite the bad image.
        full = client.get(
            f"/api/v1/artifacts/{ref.id}?sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )
        thumb = client.get(
            f"/api/v1/artifacts/{ref.id}?variant=thumb&sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )

    assert full.status_code == 200
    assert thumb.status_code == 200
    # Falls back to the full bytes since no thumbnail exists.
    assert thumb.headers["content-type"].startswith("image/png")


def test_old_artifact_without_thumbnail_field_round_trips(tmp_path: Path) -> None:
    # Simulate a meta.json written before the thumbnail feature existed.
    from opensquilla.artifacts import ArtifactRef

    legacy_meta = {
        "id": "art-legacyxxxxxxxxxxxxxxxxxxx",
        "sha256": "a" * 64,
        "name": "old.png",
        "mime": "image/png",
        "size": 123,
        "session_id": "session-1",
        "session_key": "agent:main:webchat:ok",
        "source": "image_generate",
        "created_at": "2025-01-01T00:00:00Z",
        "download_url": "/api/v1/artifacts/art-legacyxxxxxxxxxxxxxxxxxxx",
        "kind": "artifact_ref",
        "store": "artifacts",
    }
    ref = ArtifactRef.from_dict(legacy_meta)
    assert ref.has_thumbnail is False
    assert "thumbnail_url" not in artifact_payload(ref)
