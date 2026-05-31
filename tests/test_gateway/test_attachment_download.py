from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.attachment_refs import write_transcript_material


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

    from opensquilla.gateway.attachments import register_attachment_routes
    from opensquilla.gateway.config import AttachmentsConfig, AuthConfig, GatewayConfig
    from opensquilla.gateway.middleware import AuthMiddleware

    config = GatewayConfig(
        auth=AuthConfig(mode="token", token="secret"),
        attachments=AttachmentsConfig(media_root=str(tmp_path)),
    )
    app = Starlette(debug=False)
    register_attachment_routes(
        app,
        config=config,
        session_manager=_FakeSessionManager("session-1"),
    )
    app.add_middleware(AuthMiddleware, config=config)
    return app


def test_transcript_attachment_download_requires_auth_and_session_scope(tmp_path: Path) -> None:
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    sha, _path, _wrote = write_transcript_material(
        media_root=tmp_path,
        session_id="session-1",
        payload=b"hello attachment",
    )

    with TestClient(_app(tmp_path)) as client:
        unauthenticated = client.get(
            f"/api/v1/attachments/{sha}?sessionKey=agent:main:webchat:ok"
        )
        wrong_session = client.get(
            f"/api/v1/attachments/{sha}?sessionKey=agent:main:webchat:other",
            headers={"Authorization": "Bearer secret"},
        )
        missing_session = client.get(
            f"/api/v1/attachments/{sha}",
            headers={"Authorization": "Bearer secret"},
        )

    assert unauthenticated.status_code == 401
    assert wrong_session.status_code == 404
    assert missing_session.status_code == 404


def test_transcript_attachment_download_serves_file_response(tmp_path: Path) -> None:
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    sha, _path, _wrote = write_transcript_material(
        media_root=tmp_path,
        session_id="session-1",
        payload=b"hello attachment",
    )

    with TestClient(_app(tmp_path)) as client:
        response = client.get(
            (
                f"/api/v1/attachments/{sha}?sessionKey=agent:main:webchat:ok"
                "&name=note%20final.txt&mime=text%2Fplain"
            ),
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 200
    assert response.content == b"hello attachment"
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]
    assert "note%20final.txt" in response.headers["content-disposition"]


def test_transcript_attachment_download_reports_missing_and_integrity_errors(
    tmp_path: Path,
) -> None:
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    sha, path, _wrote = write_transcript_material(
        media_root=tmp_path,
        session_id="session-1",
        payload=b"hello attachment",
    )
    path.write_bytes(b"tampered")

    with TestClient(_app(tmp_path)) as client:
        missing = client.get(
            "/api/v1/attachments/" + ("0" * 64) + "?sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )
        mismatch = client.get(
            f"/api/v1/attachments/{sha}?sessionKey=agent:main:webchat:ok",
            headers={"Authorization": "Bearer secret"},
        )

    assert missing.status_code == 404
    assert mismatch.status_code == 409
